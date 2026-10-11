"""Validated account preferences and presentation-only time conversion."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Literal, TypedDict, cast


class Preferences(TypedDict):
    lock_minutes: int
    time_mode: Literal["utc", "local", "custom"]
    utc_offset_minutes: int


DEFAULTS: Preferences = {
    "lock_minutes": 15,
    "time_mode": "utc",
    "utc_offset_minutes": 0,
}


def validate_preferences(value: Mapping[str, object]) -> Preferences:
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError("Unsupported preference fields")
    if type(value["lock_minutes"]) is not int or value["lock_minutes"] not in (0, 1, 5, 15, 30, 60):
        raise ValueError("Choose a supported inactivity timeout")
    if value["time_mode"] not in ("utc", "local", "custom"):
        raise ValueError("Choose UTC, local or custom time")
    offset = value["utc_offset_minutes"]
    if type(offset) is not int or not -720 <= offset <= 840:
        raise ValueError("UTC offset must be between -12:00 and +14:00")
    return cast(Preferences, dict(value))


def time_label(preferences: Preferences) -> str:
    mode = preferences["time_mode"]
    if mode == "utc":
        return "UTC"
    if mode == "local":
        return "Local system timezone (offset shown per timestamp)"
    offset = preferences["utc_offset_minutes"]
    return f"UTC{'+' if offset >= 0 else '-'}{abs(offset) // 60:02}:{abs(offset) % 60:02}"


def display_time(value: object, preferences: Preferences) -> object:
    if not isinstance(value, str):
        return value
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            return value  # Never invent a timezone for an unknown evidence time.
        if preferences["time_mode"] == "local":
            return moment.astimezone().isoformat()
        offset = preferences["utc_offset_minutes"] if preferences["time_mode"] == "custom" else 0
        return moment.astimezone(timezone(timedelta(minutes=offset))).isoformat()
    except ValueError:
        return value


def report_times(
    tables: Mapping[str, Sequence[Mapping[str, object]]], preferences: Preferences
) -> dict[str, list[dict[str, object]]]:
    return {
        table: [
            {"row": index, "field": field, "display": display_time(value, preferences)}
            for index, row in enumerate(rows)
            for field, value in row.items()
            if field
            in {
                "event_time_utc",
                "commit_timestamp",
                "started_at",
                "finished_at",
                "created_at",
                "registered_at",
                "verified_at",
            }
            and value is not None
        ]
        for table, rows in tables.items()
    }
