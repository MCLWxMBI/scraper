"""Project paths and local environment loading; supplied variables win."""

from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
SQL_DIR = PROJECT_DIR / 'sql'


class ConfigurationError(RuntimeError):
    """A configuration failure safe to display without secrets."""


def load_environment() -> None:
    try:
        load_dotenv(PROJECT_DIR / '.env', override=False)
    except (OSError, UnicodeError):
        raise ConfigurationError('Could not read project environment configuration.') from None


