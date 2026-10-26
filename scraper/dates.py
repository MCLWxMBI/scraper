"""Date-only processing metadata, independent of the host's timezone."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo('Australia/Sydney')


def australian_today(now: datetime | None = None) -> date:
    instant = now if now is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('Processing date requires a timezone-aware instant.')
    return instant.astimezone(SYDNEY).date()
