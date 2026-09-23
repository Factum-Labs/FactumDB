"""Shared model validation."""

def _required(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def _sha256(value: str) -> str:
    cleaned = value.lower()
    if len(cleaned) != 64 or any(c not in "0123456789abcdef" for c in cleaned):
        raise ValueError("sha256 must be a 64-character hexadecimal digest")
    return cleaned
