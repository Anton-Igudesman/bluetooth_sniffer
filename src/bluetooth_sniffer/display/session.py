from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LiveSessionPaths:
    directory: Path
    event_log: Path
    pcap: Path
    correlation_report: Path


def create_live_session_paths(
    capture_directory: Path,
    device_address: str,
    *,
    started_at: datetime | None = None,
) -> LiveSessionPaths:
    """Create one session directory and return all of its artifact paths."""
    address_token = "".join(
        character.lower()
        for character in device_address
        if character.isalnum()
    )

    if not address_token:
        raise ValueError("Device address must contain letters or numbers")

    timestamp = started_at or datetime.now(UTC)

    if timestamp.utcoffset() is None:
        raise ValueError("Session start time must be timezone-aware")

    timestamp_token = timestamp.astimezone(UTC).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    directory_name = f"touchscreen-{timestamp_token}-{address_token}"
    capture_directory.mkdir(parents=True, exist_ok=True)

    # Reserve the directory atomically. A suffix handles a clock collision
    # without appending new JSONL records to an earlier evidence bundle.
    for collision_number in range(1000):
        suffix = "" if collision_number == 0 else f"-{collision_number}"
        directory = capture_directory / f"{directory_name}{suffix}"

        try:
            directory.mkdir()
        except FileExistsError:
            continue

        break
    else:
        raise FileExistsError(
            f"Could not reserve a unique session directory in "
            f"{capture_directory}"
        )

    return LiveSessionPaths(
        directory=directory,
        event_log=directory / "session.jsonl",
        pcap=directory / "capture.pcap",
        correlation_report=directory / "correlation.json",
    )
