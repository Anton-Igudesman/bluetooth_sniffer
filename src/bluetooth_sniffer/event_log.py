import json
from datetime import UTC, datetime
from pathlib import Path

type EventValue = str | int | float | bool | None | tuple[str, ...]

class EventLogger:
    def __init__(self, output_path: Path | None) -> None:
        self.output_path = output_path
        
    def record(self, event_type: str, **fields: EventValue) -> None:
        reserved_fields = {"timestamp", "event"} & fields.keys()
        
        # All log entries have same timestamp and event-type structure
        if reserved_fields:
            names = ", ".join(sorted(reserved_fields))
            raise ValueError(f"Reserved event fields cannot be replaced: {names}")
        
        # Handle None-type for event-producing code
        if self.output_path is None:
            return
        
        event: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event_type,
            **fields,
        }
        
        # Make sure log write will succeed
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Each append produces one independently readable JSONL record
        with self.output_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(event) + "\n")