"""Claude clients using local API keys or refreshable GitHub OIDC credentials."""

import json
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from anthropic import Anthropic
from anthropic.lib.credentials import WorkloadIdentityCredentials

from scraper.config import ConfigurationError
from scraper.structuring import CLAUDE_TIMEOUT_SECONDS

FEDERATION_VARIABLES = (
    'ANTHROPIC_ORGANIZATION_ID',
    'ANTHROPIC_FEDERATION_RULE_ID',
    'ANTHROPIC_SERVICE_ACCOUNT_ID',
    'ANTHROPIC_WORKSPACE_ID',
)
OIDC_AUDIENCE = 'https://api.anthropic.com'
OIDC_TIMEOUT_SECONDS = 10


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward GitHub's bearer credential to a redirect destination.
        return None


def _github_identity_token() -> str:
    """Fetch on demand; the SDK invokes this again when credentials expire."""
    try:
        parts = urlsplit(os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'])
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise ValueError('Invalid identity endpoint')
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if key != 'audience']
        url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                         urlencode([*query, ('audience', OIDC_AUDIENCE)]), ''))
        request = Request(url, headers={
            'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN'],
            'Accept': 'application/json',
        })
        with build_opener(_NoRedirects()).open(request, timeout=OIDC_TIMEOUT_SECONDS) as response:
            token = json.load(response)['value']
        if not isinstance(token, str) or not token.strip():
            raise ValueError('Missing identity token')
        return token.strip()
    except Exception:
        raise ConfigurationError('Could not obtain GitHub OIDC identity token.') from None


class _SafeFederationCredentials(WorkloadIdentityCredentials):
    def __call__(self, *, force_refresh=False):
        try:
            return super().__call__(force_refresh=force_refresh)
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError('Anthropic OIDC token exchange failed; check federation configuration.') from None


def create_claude_client() -> Anthropic:
    """Return a context-managed client; the caller loads .env before calling."""
    federation = {name: os.environ.get(name, '').strip() for name in FEDERATION_VARIABLES}
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if any(federation.values()):
        required = (*FEDERATION_VARIABLES, 'ACTIONS_ID_TOKEN_REQUEST_URL', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN')
        missing = [name for name in required if not os.environ.get(name, '').strip()]
        if missing:
            raise ConfigurationError('Incomplete OIDC configuration: set ' + ', '.join(missing) + '.')
        if api_key or os.environ.get('ANTHROPIC_AUTH_TOKEN', '').strip():
            raise ConfigurationError('OIDC conflicts with static credentials; unset ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN.')
        credentials = _SafeFederationCredentials(
            identity_token_provider=_github_identity_token,
            organization_id=federation['ANTHROPIC_ORGANIZATION_ID'],
            federation_rule_id=federation['ANTHROPIC_FEDERATION_RULE_ID'],
            service_account_id=federation['ANTHROPIC_SERVICE_ACCOUNT_ID'],
            workspace_id=federation['ANTHROPIC_WORKSPACE_ID'],
        )
        try:
            return Anthropic(credentials=credentials, max_retries=0, timeout=CLAUDE_TIMEOUT_SECONDS)
        except Exception:
            credentials.close()
            raise ConfigurationError('Could not initialize Anthropic OIDC client.') from None
    if not api_key:
        raise ConfigurationError('Set ANTHROPIC_API_KEY in .env or the environment, or configure Anthropic OIDC.')
    return Anthropic(api_key=api_key, max_retries=0, timeout=CLAUDE_TIMEOUT_SECONDS)
