import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from collections.abc import Iterator

from .gatt_client import GattCharacteristicMapping

type GattEventType = Literal["gatt.write", "gatt.notification"]
type JsonObject = dict[str, object]

GATT_EVENT_TYPES = {"gatt.write", "gatt.notification"}
GATT_MAPPING_EVENT_TYPE = "gatt.characteristic_mapped"

@dataclass(frozen=True)
class GattEvent:
    timestamp: datetime
    event_type: GattEventType
    characteristic_uuid: str
    payload: bytes

def _log_error(
    path: Path,
    line_number: int,
    message: str,
) -> ValueError:
    # Centralize JSONL source so parsing failure identifies
    # exact session file and line that couldn't be analyzed
    return ValueError(f"{path}:{line_number}: {message}")

def _field_error(
    path: Path,
    line_number: int,
    key: str,
    requirement: str,
) -> ValueError:
    # Every JSONL validation failure should identify the exact file, line,
    # field, and requirement so damaged session data can be corrected
    return _log_error(
        path,
        line_number,
        f"{key} must be {requirement}"
    )
    
def _required_string(
    record: JsonObject,
    key: str,
    path: Path,
    line_number: int,
) -> str:
    value = record.get(key)
    
    if not isinstance(value, str):
        raise _field_error(
            path,
            line_number,
            key,
            "a string",
        )
    return value

def _required_uuid(
    record: JsonObject,
    key: str,
    path: Path,
    line_number: int,
) -> str:
    uuid_text = _required_string(record, key, path, line_number)
    
    try:
        # Normalized UUIDs compare between profiles, application logs
        # and TShark even if an input used different letter casing
        return str(UUID(uuid_text))
    except ValueError as error:
        raise _field_error(
            path,
            line_number,
            key,
            "a valid UUID",
        ) from error

def _required_integer(
    record: JsonObject,
    key: str,
    path: Path,
    line_number: int,
) -> int:
    value = record.get(key)
    
    # Python treats bool as int, but T/F are not valid ATT handles
    if isinstance(value, bool) or not isinstance(value, int):
        raise _field_error(
            path,
            line_number,
            key,
            "an integer",
        )
        
    return value
        
def _required_string_tuple(
    record: JsonObject,
    key: str,
    path: Path,
    line_number: int,
) -> tuple[str, ...]:
    value = record.get(key)
    
    # JSON stored characteristic props as array
    # Mapping object uses a tuple so props can't change after
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise _field_error(
            path,
            line_number,
            key,
            "a list of strings",
        )
        
    return tuple(value)

def _read_json_records(
    path: Path,
) -> Iterator[tuple[int, JsonObject]]:
    if not path.is_file():
        raise FileNotFoundError(f"Event log was not found: {path}")
    
    with path.open(encoding="utf-8") as log_file:
        for line_number, line in enumerate(log_file, start=1):
            if not line.strip():
                continue
            
            try:
                decoded: object = json.loads(line)
            except json.JSONDecodeError as error:
                # Preserve line number because each JSON line is
                # an independent session record
                raise _log_error(
                    path,
                    line_number,
                    "invalid JSON event",
                ) from error
                
            if not isinstance(decoded, dict):
                raise _log_error(
                    path,
                    line_number,
                    "event must be a JSON object",
                )
                
            # Event and mapping loaders receive the same validated record
            # shape while retaining original line for validation errors
            yield line_number, cast(JsonObject, decoded)

def read_gatt_events(path: Path) -> list[GattEvent]:
    
    events: list[GattEvent] = []
    
    for line_number, record in _read_json_records(path):
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
        
        characteristic_uuid = _required_uuid(
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
            payload = bytes.fromhex(payload_hex)
            
        except ValueError as error:
            raise _log_error(
                path,
                line_number,
                "invalid Gatt event value",
            ) from error
            
        if timestamp.utcoffset() is None:
            raise _field_error(
                path,
                line_number,
                "timestamp",
                "a timezone-aware value",
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

def read_gatt_mappings(
    path: Path,
) -> list[GattCharacteristicMapping]:
    mappings: list[GattCharacteristicMapping] = []
    
    for line_number, record in _read_json_records(path):
        # Only mapping events describe how application UUID corresponds w/ 
        # temp ATT handle present in Nordic capture
        if record.get("event") != GATT_MAPPING_EVENT_TYPE:
            continue
        
        service_uuid = _required_uuid(
            record,
            "service_uuid",
            path,
            line_number,
        )
        characteristic_uuid = _required_uuid(
            record,
            "characteristic_uuid",
            path,
            line_number,
        )
        service_handle = _required_integer(
            record,
            "service_handle",
            path,
            line_number,
        )
        declaration_handle = _required_integer(
            record,
            "declaration_handle",
            path,
            line_number,
        )
        value_handle = _required_integer(
            record,
            "value_handle",
            path,
            line_number,
        )
        
        # GATT operations use vlaue handle after declaration
        if value_handle != declaration_handle + 1:
            raise _log_error(
                path,
                line_number,
                (
                    f"value_handle {value_handle} does not immediately follow"
                    f" declaration_handle {declaration_handle}"
                ),
            )
            
        mappings.append(
            GattCharacteristicMapping(
                service_uuid=service_uuid,
                service_handle=service_handle,
                characteristic_uuid=characteristic_uuid,
                declaration_handle=declaration_handle,
                value_handle=value_handle,
                properties=_required_string_tuple(
                    record,
                    "properties",
                    path,
                    line_number,
                ),
            )
        )
    return mappings