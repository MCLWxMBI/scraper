"""Pydantic models for the ECHO opportunity contract and Claude extraction.

The extraction model permits a missing deadline. Composer exports a record only
after a deadline has been found and the complete opportunity validates.
"""

from __future__ import annotations

import re
from datetime import datetime
from dataclasses import dataclass
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Category = Literal[
    'Biodiversity & ecosystems',
    'Climate change',
    'First Nations & cultural heritage',
    'Water & resources',
    'Communities & environment',
]
Jurisdiction = Literal['Commonwealth', 'Victoria']
# A list keeps the API schema's array items typed; the local model enforces size.
Position = Annotated[list[float], Field(min_length=2, max_length=2)]
Ring = list[Position]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def _check_position(position: Position) -> None:
    longitude, latitude = position
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError('Coordinates must be [longitude, latitude] within geographic bounds')


def _check_polygon(rings: list[Ring]) -> None:
    if not rings:
        raise ValueError('A polygon must have an outer ring')
    for ring in rings:
        if len(ring) < 4 or ring[0] != ring[-1]:
            raise ValueError('Polygon rings need at least four positions and must be closed')
        for position in ring:
            _check_position(position)


class Point(ContractModel):
    type: Literal['Point']
    coordinates: Position

    @field_validator('coordinates')
    @classmethod
    def check_coordinates(cls, value: Position) -> Position:
        _check_position(value)
        return value


class Polygon(ContractModel):
    type: Literal['Polygon']
    coordinates: list[Ring]

    @field_validator('coordinates')
    @classmethod
    def check_coordinates(cls, value: list[Ring]) -> list[Ring]:
        _check_polygon(value)
        return value


class MultiPolygon(ContractModel):
    type: Literal['MultiPolygon']
    coordinates: list[list[Ring]]

    @field_validator('coordinates')
    @classmethod
    def check_coordinates(cls, value: list[list[Ring]]) -> list[list[Ring]]:
        if not value:
            raise ValueError('A multipolygon must contain at least one polygon')
        for polygon in value:
            _check_polygon(polygon)
        return value


class OpportunityLocation(ContractModel):
    label: NonemptyText
    geometry: Point | Polygon | MultiPolygon


class OpportunityFields(ContractModel):
    """Fields inferred by Claude; identity, source URL and full text belong to Python."""

    title: NonemptyText
    sourceOrg: NonemptyText
    jurisdiction: Jurisdiction
    startDate: str | None = Field(default=None, description='Opening instant in UTC ending in Z, or null')
    submissionDeadline: str | None = Field(
        default=None,
        description=('Explicit or contextually inferred participation closing timestamp in UTC ending in Z; '
                     'a stated engagement range may supply its ending month. For month precision use '
                     'the first day at 00:00:00Z; null only without reasonably supported timing.'),
    )
    submissionDeadlinePrecision: Literal['datetime', 'month'] = Field(
        default='datetime', description=('month for a stated or contextually inferred closing month/year; '
                                         'otherwise datetime'),
    )
    category: Annotated[list[Category], Field(min_length=1)]
    tags: list[NonemptyText] | None = None
    summary: NonemptyText | None = None
    location: OpportunityLocation | None = None

    @model_validator(mode='before')
    @classmethod
    def normalize_month(cls, value):
        if isinstance(value, dict) and isinstance(value.get('submissionDeadline'), str):
            deadline = value['submissionDeadline']
            if re.fullmatch(r'\d{4}-\d{2}', deadline):
                if value.get('submissionDeadlinePrecision', 'month') != 'month':
                    raise ValueError('A year-month deadline requires month precision')
                value = {**value, 'submissionDeadline': deadline + '-01T00:00:00Z',
                         'submissionDeadlinePrecision': 'month'}
        return value

    @field_validator('startDate', 'submissionDeadline')
    @classmethod
    def check_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z', value):
                raise ValueError('Timestamp must be ISO 8601 UTC ending in Z, including a time')
            datetime.fromisoformat(value)
        return value

    @field_validator('category')
    @classmethod
    def check_categories(cls, value: list[Category]) -> list[Category]:
        if len(value) != len(set(value)):
            raise ValueError('Categories must be unique')
        return value

    @field_validator('tags')
    @classmethod
    def check_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            if len(value) != len({tag.casefold() for tag in value}):
                raise ValueError('Tags must be unique ignoring case')
            if any(tag.casefold() == 'invite-only' and tag != 'Invite-only' for tag in value):
                raise ValueError('Use the canonical Invite-only tag')
        return value or None

    @model_validator(mode='after')
    def check_date_order(self) -> Self:
        deadline = (datetime.fromisoformat(self.submissionDeadline)
                    if self.submissionDeadline is not None else None)
        if self.submissionDeadlinePrecision == 'month':
            if deadline is None or (deadline.day, deadline.hour, deadline.minute,
                                    deadline.second, deadline.microsecond) != (1, 0, 0, 0, 0):
                raise ValueError('Month deadline must be the first day at midnight UTC')
        if self.startDate is not None and deadline is not None:
            start = datetime.fromisoformat(self.startDate)
            reversed_dates = ((start.year, start.month) > (deadline.year, deadline.month)
                              if self.submissionDeadlinePrecision == 'month' else start > deadline)
            if reversed_dates:
                raise ValueError('startDate must not be later than submissionDeadline')
        return self


class Opportunity(OpportunityFields):
    """Complete contract record. A deadline is mandatory at this export boundary."""

    submissionDeadline: str
    id: Annotated[str, StringConstraints(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')]
    fullText: Annotated[list[NonemptyText], Field(min_length=1)]
    sourceUrl: NonemptyText

    @field_validator('sourceUrl')
    @classmethod
    def check_source_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
                or parts.password is not None or any(character.isspace() for character in value)):
            raise ValueError('sourceUrl must be an absolute HTTPS URL without credentials or whitespace')
        return value

    def to_record(self) -> dict:
        """Retain required null fields while omitting absent optional fields."""
        record = self.model_dump(mode='json')
        for field in ('summary', 'location'):
            if record[field] is None:
                del record[field]
        return record


@dataclass(frozen=True)
class Source:
    """A discovered URL and its extraction-routing name."""

    name: str
    url: str
