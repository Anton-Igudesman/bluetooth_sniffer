from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ..report_io import (
    field_error,
    read_correlation_report,
    required_boolean,
    required_hex_bytes,
    required_integer,
    required_object,
    required_string,
    required_list,
)

@dataclass(frozen=True)
class CorrelationSummary:
    event_count: int
    matched_count: int
    unmatched_count: int

def decode_utf8(payload: bytes) -> str | None:
    try:
        # Only label the complete payload as text when every byte forms valid UTF-8.
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    
@dataclass(frozen=True)
class CorrelationEvent:
    matched: bool
    event_type: str
    characteristic_uuid: str
    payload: bytes
    frame_number: int | None
    rssi: int | None
    
    @property
    def payload_hex(self) -> str:
        return self.payload.hex(" ")
    
    @property
    def payload_text(self) -> str | None:
        return decode_utf8(self.payload)
        
@dataclass(frozen=True)
class CorrelationReport:
    summary: CorrelationSummary
    events: tuple[CorrelationEvent, ...]
        
def _correlation_event_from_record(
    record: dict[str, object],
    path: Path,
) -> CorrelationEvent:
    matched = required_boolean(record, "matched", path)
    event_record = required_object(record, "event", path)
    
    event_type = required_string(event_record, "event_type", path)
    characteristic_uuid = required_string(
        event_record,
        "characteristic_uuid",
        path,
    )
    payload = required_hex_bytes(event_record, "payload_hex", path)
    
    packet_value = record.get("packet")
    packet_record = (
        None
        if packet_value is None
        else required_object(record, "packet", path)
    )
    
    # A matched event needs passive packet to prove the match
    if matched != (packet_record is not None):
        raise field_error(
            path,
            None,
            "matched",
            "consistent with packet availability",
        )
        
    frame_number = (
        required_integer(packet_record, "frame_number", path)
        if packet_record is not None
        else None
    )
    rssi = (
        required_integer(packet_record, "rssi", path)
        if packet_record is not None
        else None
    )
    
    return CorrelationEvent(
        matched=matched,
        event_type=event_type,
        characteristic_uuid=characteristic_uuid,
        payload=payload,
        frame_number=frame_number,
        rssi=rssi,
    )
    
def _correlation_events_from_report(
    report: dict[str, object],
    path: Path,
) -> tuple[CorrelationEvent, ...]:
    records = required_list(report, "correlations", path)
    events: list[CorrelationEvent] = []
    
    for index, record in enumerate(records):
        # Array entries have no field name, include index isntead
        if not isinstance(record, dict):
            raise field_error(
                path,
                None,
                f"correlations[{index}]",
                "a JSON object",
            )
            
        events.append(
            _correlation_event_from_record(
                cast(dict[str, object], record),
                path,
            )
        )
    return tuple(events)

def _correlation_summary_from_report(
    report: dict[str, object],
    path: Path,
) -> CorrelationSummary:
    
    # Apply the same integer type rule to report counts and JSONL ATT handles
    event_count = required_integer(report, "event_count", path)
    matched_count = required_integer(report, "matched_count", path)
    unmatched_count = required_integer(report, "unmatched_count", path)
    
    counts = (event_count, matched_count, unmatched_count)
    
    # Reject negative count totals
    if any(count < 0 for count in counts):
        raise ValueError(f"{path}: correlation counts cannot be negative")
    
    # Reject inconsistent totals
    if matched_count + unmatched_count != event_count:
        raise ValueError(
            f"{path}: matched_count + unmatched_count must equal event_count"
        )
        
    return CorrelationSummary(
        event_count=event_count,
        matched_count=matched_count,
        unmatched_count=unmatched_count,
    )
    
def load_correlation_report(path: Path) -> CorrelationReport:
    report = read_correlation_report(path)
    summary = _correlation_summary_from_report(report, path)
    events = _correlation_events_from_report(report, path)
    
    # Summary totals and event pages come from same saved report
    # Reject disagreements between the two 
    if len(events) != summary.event_count:
        raise field_error(
            path,
            None,
            "event_count",
            "equal to the number of correlations",
        )
        
    actual_matched_count = sum(event.matched for event in events)
    
    if actual_matched_count != summary.matched_count:
        raise field_error(
            path,
            None,
            "matched_count",
            "equal to the number of matched correlations",
        )
        
    return CorrelationReport(
        summary=summary,
        events=events,
    )