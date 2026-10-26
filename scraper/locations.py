"""Resolve affected geography from official APIs, without Claude calls or caching."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Literal
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from pydantic import Field
from scraper.models import ContractModel, NonemptyText, OpportunityLocation

GA_LAYER = 'https://services.ga.gov.au/gis/rest/services/Composite_Gazetteer_of_Australia/MapServer/0'
ABS_ROOT = 'https://geo.abs.gov.au/arcgis/rest/services/ASGS2026'
STATES = {'ACT': 'Australian Capital Territory', 'NSW': 'New South Wales',
          'NT': 'Northern Territory', 'QLD': 'Queensland', 'SA': 'South Australia',
          'TAS': 'Tasmania', 'VIC': 'Victoria', 'WA': 'Western Australia'}


class LocationError(RuntimeError):
    """Operational geographic failure: do not save a partial opportunity."""


class GeographicScope(ContractModel):
    name: NonemptyText
    entityType: Literal['site', 'locality', 'local_government_area', 'state', 'national', 'river', 'other']
    representation: Literal['site_point', 'representative_point', 'boundary', 'unsupported']
    role: Literal['affected', 'office', 'venue', 'incidental']
    label: NonemptyText
    evidence: NonemptyText = Field(description='Exact excerpt from articleText identifying the affected geography')
    state: Literal['ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA'] | None = None
    stateEvidence: NonemptyText | None = Field(default=None, description='Exact article excerpt supporting state, or null')
    approximate: bool = False


@dataclass(frozen=True)
class GeographicCandidate:
    id: str
    name: str
    entity_type: str
    representation: str
    geometry: dict
    source_url: str
    dataset: str
    state: str | None = None


def _name(value: str) -> str:
    return ' '.join(re.findall(r'\w+', value.casefold()))


def _mentions(name: str, text: str) -> bool:
    return bool(re.search(r'(?<!\w)' + re.escape(_name(name)) + r'(?!\w)', _name(text)))


def _base_name(value: str) -> str:
    # ABS locality labels carry disambiguating state/LGA suffixes. They are
    # matched only alongside returned state attributes, never by fuzzy ranking.
    return _name(re.sub(r'\s*\([^)]*\)\s*$', '', value))


def _sql(value: str) -> str:
    return "'" + value.replace("'", "''").upper() + "'"


def fetch_geojson(url: str, params: dict) -> dict:
    """Two bounded attempts; no response cache and no arbitrary article URLs."""
    request = Request(url + '/query?' + urlencode(params),
                      headers={'User-Agent': 'ECHO-consultation-scraper/0.1', 'Accept': 'application/geo+json, application/json'})
    for attempt in range(2):
        try:
            with urlopen(request, timeout=20) as response:
                if response.geturl().split('/gis/rest/')[0] != request.full_url.split('/gis/rest/')[0] and not response.geturl().startswith(ABS_ROOT + '/'):
                    raise LocationError('Geographic service redirected outside the approved endpoint.')
                raw = response.read(20 * 1024 * 1024 + 1)
                if len(raw) > 20 * 1024 * 1024:
                    raise LocationError('Geographic response exceeded the download limit.')
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get('error') or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
                    raise LocationError('Geographic service returned a malformed response.')
                crs = data.get('crs')
                if crs is not None:
                    properties = crs.get('properties') if isinstance(crs, dict) else None
                    if not isinstance(properties, dict) or properties.get('name') not in {
                        'urn:ogc:def:crs:OGC:1.3:CRS84', 'urn:ogc:def:crs:EPSG::4326', 'EPSG:4326'}:
                        raise LocationError('Geographic service did not return WGS84.')
                return data
        except (OSError, URLError, ValueError, LocationError):
            if attempt == 1:
                raise LocationError('Geographic lookup failed after two attempts.') from None
            time.sleep(0.5)
    raise AssertionError('Unreachable')


class LocationResolver:
    def __init__(self, *, fetch=fetch_geojson, supplied=(), offline=False):
        self.fetch = fetch
        self.supplied = tuple(supplied)
        self.offline = offline

    def _lookup(self, scope: GeographicScope) -> list[GeographicCandidate]:
        # A supplied candidate is trusted input from code, never model output.
        supplied = [c for c in self.supplied if _name(c.name) == _name(scope.name)
                    and c.entity_type == scope.entityType and c.representation == scope.representation
                    and (scope.state is None or c.state == scope.state)]
        if supplied or self.offline:
            return supplied
        if scope.representation == 'boundary' and scope.entityType in {'locality', 'local_government_area', 'state'}:
            layer = {'locality': 'SAL', 'local_government_area': 'LGA', 'state': 'STE'}[scope.entityType]
            field = 'STATE_NAME_2026' if layer == 'STE' else layer + '_NAME_2026'
            identifier = 'STATE_CODE_2026' if layer == 'STE' else layer + '_CODE_2026'
            where = f'(UPPER({field}) = {_sql(scope.name)} OR UPPER({field}) LIKE {_sql(scope.name + " (%")})'
            if scope.state:
                where += f' AND UPPER(STATE_NAME_2026) = {_sql(STATES[scope.state])}'
            url = f'{ABS_ROOT}/{layer}/MapServer/0'
            dataset = 'ABS ASGS 2026 ' + layer
        elif scope.entityType == 'locality' and scope.representation == 'representative_point':
            field, identifier = 'name', 'id'
            where = f'UPPER(name) = {_sql(scope.name)}'
            if scope.state:
                where += f' AND UPPER(authority) = {_sql(scope.state)}'
            url, dataset = GA_LAYER, 'GA Composite Gazetteer of Australia'
        else:
            # Exact site footprints/coordinates, river areas and national
            # boundaries require supplied verified data, not a gazetteer point.
            return []
        data = self.fetch(url, dict(where=where, outFields='*', returnGeometry='true',
                                   outSR='4326', f='geojson', resultRecordCount=100))
        if not isinstance(data, dict) or data.get('error') or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
            raise LocationError('Malformed geographic feature collection.')
        metadata = data.get('properties') or {}
        if not isinstance(metadata, dict):
            raise LocationError('Malformed geographic collection metadata.')
        if data.get('exceededTransferLimit') or metadata.get('exceededTransferLimit'):
            raise LocationError('Geographic results were truncated; refusing a partial match.')
        candidates = []
        for feature in data['features']:
            try:
                if not isinstance(feature, dict) or feature.get('type') != 'Feature':
                    raise ValueError('Malformed feature')
                properties = {k.casefold(): v for k, v in feature['properties'].items()}
                name = properties[field.casefold()]
                state = (properties.get('authority') if url == GA_LAYER else next(
                    (code for code, value in STATES.items() if value == properties.get('state_name_2026')), None))
                if not isinstance(name, str):
                    raise ValueError('Missing name')
                if (_name(name) != _name(scope.name) and not (url != GA_LAYER and _base_name(name) == _base_name(scope.name))) or (scope.state and state != scope.state):
                    continue
                if url == GA_LAYER:
                    kind = str(properties.get('feature', '')).casefold()
                    if kind not in {'locality', 'bounded locality', 'gazetted locality', 'populated locality',
                                    'suburb', 'town', 'city', 'populated place'}:
                        continue
                candidate_id = properties[identifier.casefold()]
                if type(candidate_id) not in (int, str) or not str(candidate_id).strip():
                    raise ValueError('Missing feature identifier')
                version = (dataset + ' supply_date=' + str(properties.get('supply_date', 'unknown'))
                           if url == GA_LAYER else dataset)
                candidates.append(GeographicCandidate(str(candidate_id), name,
                    scope.entityType, scope.representation, feature['geometry'], url, version, state))
            except (KeyError, TypeError, ValueError, AttributeError):
                raise LocationError('Malformed geographic feature.') from None
        return candidates

    def resolve(self, scopes: list[GeographicScope], text: str, *, diagnostic=None) -> OpportunityLocation | None:
        def log(outcome, **fields):
            if diagnostic:
                # Keep short source evidence, never complete article bodies.
                if 'evidence' in fields:
                    fields['evidence'] = fields['evidence'][:400]
                diagnostic(outcome=outcome, **fields)
        selected = []
        seen = set()
        for scope in scopes:
            if scope.role != 'affected':
                log('ignored', reason=scope.role)
                continue
            if scope.evidence not in text or not _mentions(scope.name, scope.evidence):
                raise LocationError('Affected-place evidence does not match the article.')
            if scope.state and (not scope.stateEvidence or scope.stateEvidence not in text or not any(
                re.search(r'\b' + re.escape(value) + r'\b', scope.stateEvidence, re.I)
                for value in (scope.state, STATES[scope.state]))):
                raise LocationError('State qualifier is not supported by article evidence.')
            if scope.representation == 'unsupported':
                log('no_location', reason='unsupported representation', evidence=scope.evidence)
                return None
            if not _mentions(scope.name, scope.label) or '<' in scope.label or '>' in scope.label:
                raise LocationError('Location label does not identify the affected place.')
            try:
                candidates = self._lookup(scope)
                unique = {}
                for item in candidates:
                    key = (item.dataset, item.id)
                    if key in unique and unique[key] != item:
                        raise LocationError('Conflicting geographic records share a candidate ID.')
                    unique[key] = item
                if len(unique) != 1:
                    log('no_location', reason='ambiguous match' if unique else 'no supplied offline match' if self.offline else 'no verified match', evidence=scope.evidence)
                    return None
                candidate = next(iter(unique.values()))
                provider = urlsplit(candidate.source_url)
                if (not candidate.dataset or not candidate.id or provider.scheme != 'https'
                        or not provider.hostname or provider.username or provider.password):
                    raise ValueError('Candidate provenance is missing')
                geometry = candidate.geometry
                expected = {'Point'} if scope.representation in {'site_point', 'representative_point'} else {'Polygon', 'MultiPolygon'}
                if geometry.get('type') not in expected:
                    raise ValueError('Geometry does not represent the requested scope')
                label = ('Approximate location: ' if scope.approximate else '') + scope.label
                if scope.representation == 'representative_point':
                    label += ' (representative location)'
                location = OpportunityLocation.model_validate(dict(label=label, geometry=geometry))
            except (ValueError, TypeError, AttributeError):
                raise LocationError('Invalid verified geographic geometry.') from None
            key = (candidate.dataset, candidate.id)
            if key not in seen:
                selected.append(location)
                seen.add(key)
            log('resolved', candidate_id=candidate.id, provider_url=provider._replace(query='', fragment='').geturl(),
                dataset=candidate.dataset, evidence=scope.evidence)
        if not selected:
            log('no_location', reason='no affected geography')
            return None
        if len(selected) == 1:
            return selected[0]
        if any(location.geometry.type == 'Point' for location in selected):
            log('no_location', reason='multiple points or mixed representations are unsupported')
            return None
        polygons = []
        for location in selected:
            geometry = location.geometry
            polygons.extend([geometry.coordinates] if geometry.type == 'Polygon' else geometry.coordinates)
        try:
            combined = OpportunityLocation.model_validate(dict(label='; '.join(loc.label for loc in selected),
                geometry=dict(type='MultiPolygon', coordinates=polygons)))
        except ValueError:
            log('no_location', reason='area combination is not a valid MultiPolygon')
            return None
        return combined
