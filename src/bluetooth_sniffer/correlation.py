import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

type GattEventType = Literal["gatt.write", "gatt.notification"]
type JsonObject = dict[str, object]

GATT_EVENT_TYPES = {"gatt.write", "gatt.notification"}

@dataclass(frozen=True)
class GattEvent:
    timestamp: datetime
    event_type: GattEventType
    characteristic_uuid: str
    payload: bytes
    
def _required_string(
    record: JsonObject,
    key: str,
    path: Path,
    line_number: int,
) -> str:
    value = record.get(key)
    
    if not isinstance(value, str):
        raise ValueError(
            f"{path}: {line_number}: {key} must be a string"
        )
        
    return value

def read_gatt_events(path: Path) -> list[GattEvent]:
    if not path.is_file():
        raise FileNotFoundError(f"Event log was not found: {path}")
    
    events: list[GattEvent] = []
    
    with path.open(encoding="utf-8") as log_file:
        for line_number, line in enumerate(log_file, start=1):
            if not line.strip():
                continue
            
            try:
                decoded: object = json.loads(line)
                
            except json.JSONDecodeError as error:
                # Identify broken line w/out hiding original JSON parsing failure
                raise ValueError(
                    f"{path}:{line_number}: invalid JSON event"
                ) from error
                
            if not isinstance(decoded, dict):
                raise ValueError(
                    f"{path}:{line_number}: event must be a JSON object"
                )
                
            record = cast(JsonObject, decoded)
            event_type = record.get("event")
            
            # Connection/capture records don't participate in payload correlation
            if event_type not in GATT_EVENT_TYPES:
                continue
            
            timestamp_text = _required_string(
                record,
                "timestamp",
                path,
                line_number,
            )
            
            characteristic_uuid_text = _required_string(
                record,
                "characteristic_uuid",
                path,
                line_number,
            )
            
            payload_hex = _required_string(
                record,
                "payload_hex",
                path,
                line_number,
            )
            
            try:
                timestamp = datetime.fromisoformat(timestamp_text)
                characteristic_uuid = str(UUID(characteristic_uuid_text))
                payload = bytes.fromhex(payload_hex)
                
            except ValueError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid GATT event value"
                ) from error
                
            if timestamp.utcoffset() is None:
                raise ValueError(
                    f"{path}:{line_number}: timestamp must include a timezone"
                )
                
            events.append(
                GattEvent(
                    timestamp=timestamp.astimezone(UTC),
                    event_type=cast(GattEventType, event_type),
                    characteristic_uuid=characteristic_uuid,
                    payload=payload,
                )
            )
            
    return events