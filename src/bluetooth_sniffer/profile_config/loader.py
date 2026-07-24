import tomllib
from pathlib import Path
from uuid import UUID

from .model import ProtocolProfile

def _required_string(
    data: dict[str, object], # loaded profile
    key: str,
    path: Path,
) -> str:
    # A missing key returns None and fails the same check as invalid value
    value = data.get(key)

    # Validate external value and narrow its type from object to str
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {key} must be a non-empty string")

    return value.strip()

def _required_uuid(
    data: dict[str, object],
    key: str,
    path: Path,
) -> str:
    value = _required_string(data, key, path)

    try:
        # Normalize valid UUIDs so later comparisons use one representation
        return str(UUID(value))

    except ValueError as error:
        # Point the user to the exact profile setting that needs correction
        raise ValueError(f"{path}: {key} must be a valid UUID") from error

def load_profile(path: Path) -> ProtocolProfile:
    # tomllib.load() rejects a non-byte stream
    with path.open("rb") as profile_file:
        data: dict[str, object] = tomllib.load(profile_file)

    # Construct the profile only after every required value passes validation
    return ProtocolProfile(
        name=_required_string(data, "name", path),
        service_uuid=_required_uuid(data, "service_uuid", path),
        rx_uuid=_required_uuid(data, "rx_uuid", path),
        tx_uuid=_required_uuid(data, "tx_uuid", path),
    )