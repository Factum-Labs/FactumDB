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
    """datetime -> the stored form, e.g. 2026-09-23T10:15:00Z.

    A datetime with no timezone is treated as UTC rather than as local time.
    Guessing a local zone would put the wrong instant in the database with
    nothing to show it had happened.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def from_text(text: str) -> datetime:
    """The stored form -> a timezone-aware datetime in UTC."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
