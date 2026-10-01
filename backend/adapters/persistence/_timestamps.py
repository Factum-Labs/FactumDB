"""Converting datetimes to and from the text SQLite stores.

SQLite has no date type, so timestamps are kept as ISO-8601 text in UTC.
That form sorts correctly as plain text and stays readable to anyone opening
the database directly, which matters when the point of the tool is showing
its working.

Kept in one place because the case, evidence and tool run repositories all
need it and they must agree on the format exactly.
"""

from datetime import datetime, timezone


def to_text(value: datetime) -> str:
    """datetime -> the stored form, e.g. 2026-09-23T10:15:00.000000Z.

    A datetime with no timezone is treated as UTC rather than as local time.
    Guessing a local zone would put the wrong instant in the database with
    nothing to show it had happened.

    The microseconds are always written, even when they are zero. Plain
    isoformat() leaves them out for a whole second, and then the text no
    longer sorts in time order: "10:00:00.500000Z" sorts before "10:00:00Z"
    because "." comes before "Z". Every ORDER BY on a timestamp column relies
    on the text sorting correctly.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    utc = value.astimezone(timezone.utc)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def from_text(text: str) -> datetime:
    """The stored form -> a timezone-aware datetime in UTC."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
