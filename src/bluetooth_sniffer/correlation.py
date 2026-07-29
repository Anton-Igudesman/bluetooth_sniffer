import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from collections.abc import Iterator

from .gatt_client import GattCharacteristicMapping
from .report_io import (
    field_error,
    required_integer,
    required_list,
    required_string,
    required_hex_bytes,
)

from .pcap_analysis import (
    ATT_NOTIFICATION_OPCODES,
    ATT_WRITE_OPCODES,
    AttPacket,
    read_att_packets,
)

type GattEventType = Literal["gatt.write", "gatt.notification"]
type JsonObject = dict[str, object]

GATT_EVENT_TYPES = {"gatt.write", "gatt.notification"}
GATT_MAPPING_EVENT_TYPE = "gatt.characteristic_mapped"

# Fixed ATT operations prevent identical payloads from matching when
# they belong to different kinds of BLE traffic
ATT_OPCODES_BY_EVENT: dict[GattEventType, frozenset[int]] = {
    "gatt.write": ATT_WRITE_OPCODES,
    "gatt.notification": ATT_NOTIFICATION_OPCODES,
}

# Callers can widen this when capture latency or clock difference requires
DEFAULT_CORRELATION_WINDOW = timedelta(seconds=2)

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

@dataclass(frozen=True)
class GattCorrelation:
    event: GattEvent
    mapping: GattCharacteristicMapping
    packet: AttPacket | None
    time_offset: timedelta | None
    
    @property
    def matched(self) -> bool:
        # Keep unmatched events in report - give callers a way
        # to cound which application actions appeared in the PCAP
        return self.packet is not None

def _required_uuid(
    record: JsonObject,
    key: str,
    path: Path,
    line_number: int,
) -> str:
    uuid_text = required_string(record, key, path, line_number)
    
    try:
        # Normalized UUIDs compare between profiles, application logs
        # and TShark even if an input used different letter casing
        return str(UUID(uuid_text))
    except ValueError as error:
        raise field_error(
            path,
            line_number,
            key,
            "a valid UUID",
        ) from error
        
def _required_string_tuple(
    record: JsonObject,
    key: str,
    path: Path,
    line_number: int,
) -> tuple[str, ...]:
    value = required_list(record, key, path, line_number)
    
    # The shared validator proves this is an array
    # Prevent non-string property from entering immutable GATT mapping
    if not all(isinstance(item, str) for item in value):
        raise field_error(
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
        
        timestamp_text = required_string(
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
        
        payload = required_hex_bytes(
            record,
            "payload_hex",
            path,
            line_number,
        )
        
        try:
            timestamp = datetime.fromisoformat(timestamp_text)
            
        except ValueError as error:
            raise _log_error(
                path,
                line_number,
                "invalid Gatt event value",
            ) from error
            
        if timestamp.utcoffset() is None:
            raise field_error(
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
        service_handle = required_integer(
            record,
            "service_handle",
            path,
            line_number,
        )
        declaration_handle = required_integer(
            record,
            "declaration_handle",
            path,
            line_number,
        )
        value_handle = required_integer(
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

def correlate_gatt_events(
    events: list[GattEvent],
    mappings: list[GattCharacteristicMapping],
    packets: list[AttPacket],
    max_time_delta: timedelta = DEFAULT_CORRELATION_WINDOW,
) -> list[GattCorrelation]:
    if max_time_delta < timedelta(0):
        raise ValueError("Correlation time window cannot be negative")
    
    if events and not packets:
        raise ValueError("Passive capture contains no decoded ATT packets for logged GATT events")
    
    mappings_by_uuid: dict[str, GattCharacteristicMapping] = {}
    
    for mapping in mappings:
        existing = mappings_by_uuid.get(mapping.characteristic_uuid)
        
        # Two handles for one UUID makes packet selection unsafe
        if existing is not None and existing != mapping:
            raise ValueError(
                f"Multiple ATT mappings exist for {mapping.characteristic_uuid}"
            )
            
        mappings_by_uuid[mapping.characteristic_uuid] = mapping
        
    correlations: list[GattCorrelation] = []
    used_frames: set[int] = set()
    
    # Process events chronologically - pair identical payloads w/ passive packets
    for event in sorted(events, key=lambda item: item.timestamp):
        mapping = mappings_by_uuid.get(event.characteristic_uuid)
        
        if mapping is None:
            raise ValueError(
                f"No ATT mapping exists for {event.characteristic_uuid}"
            )
            
        expected_opcodes = ATT_OPCODES_BY_EVENT[event.event_type]
        
        candidates = [
            packet
            for packet in packets
            if packet.frame_number not in used_frames
            and packet.opcode in expected_opcodes
            and packet.handle == mapping.value_handle
            and packet.value == event.payload
            and abs(packet.timestamp - event.timestamp) <= max_time_delta
        ]
        
        if not candidates:
            # Capture loss reporting application event
            correlations.append(
                GattCorrelation(
                    event=event,
                    mapping=mapping,
                    packet=None,
                    time_offset=None,
                )
            )
            continue
        
        # Timestamp proximity chooses strongest candidate - then frame number
        packet = min(
            candidates,
            key=lambda item: (
                abs(item.timestamp - event.timestamp),
                item.frame_number,
            ),
        )
        used_frames.add(packet.frame_number)
        
        correlations.append(
            GattCorrelation(
                event=event,
                mapping=mapping,
                packet=packet,
                time_offset=packet.timestamp - event.timestamp,
            )
        )
        
    return correlations

async def analyze_session(
    event_log_path: Path,
    pcap_path: Path,
    max_time_delta: timedelta = DEFAULT_CORRELATION_WINDOW,
) -> list[GattCorrelation]:
    # Keep session loading in boundary so live application
    # and offline analyzer are in sync
    events = read_gatt_events(event_log_path)
    mappings = read_gatt_mappings(event_log_path)
    
    # TShark reads finalized passive capture async because
    # it runs subprocess not in-process parsing
    packets = await read_att_packets(pcap_path)
    
    return correlate_gatt_events(
        events,
        mappings,
        packets,
        max_time_delta=max_time_delta,
    )