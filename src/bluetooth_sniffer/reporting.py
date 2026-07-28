import json
from pathlib import Path

from .scanner import ScanResults
from .correlation import GattCorrelation

def build_scan_report(results: ScanResults) -> list[dict[str, object]]:
    # Preserve captures adv. values without BlueZ-specific objects
    return [
        {
            "address": device.address,
            "name": advertisement.local_name or device.name,
            "rssi": advertisement.rssi,
            "tx_power": advertisement.tx_power,
            "service_uuids": advertisement.service_uuids,
            "manufacturer_data": {
                f"0x{company_id:04X}": payload.hex(" ")
                for company_id, payload in advertisement.manufacturer_data.items()
            },
            "service_data": {
                service_uuid: payload.hex(" ")
                for service_uuid, payload in advertisement.service_data.items()
            },
        }
        for device, advertisement in results.values()
    ]

def build_correlation_report(
    correlations: list[GattCorrelation],
    event_log_path: Path,
    pcap_path: Path,
    window_seconds: float,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    
    for correlation in correlations:
        packet = correlation.packet
        
        # An unmatched event remains in report so capture loss can be identified
        packet_record: dict[str, object] | None = None
        
        if packet is not None:
            packet_record = {
                "frame_number": packet.frame_number,
                "timestamp": packet.timestamp.isoformat(),
                "access_address": packet.access_address,
                "central_address": packet.central_address,
                "peripheral_address": packet.peripheral_address,
                "rssi": packet.rssi,
                "encrypted": packet.encrypted,
                "opcode": packet.opcode,
                "handle": packet.handle,
                "value_hex": (
                    packet.value.hex(" ")
                    if packet.value is not None
                    else None
                ),
                "service_uuid": packet.service_uuid,
            }
            
        records.append(
            {
                "matched": correlation.matched,
                "time_offset_seconds": (
                    correlation.time_offset.total_seconds()
                    if correlation.time_offset is not None
                    else None
                ),
                "event": {
                    "timestamp": correlation.event.timestamp.isoformat(),
                    "event_type": correlation.event.event_type,
                    "characteristic_uuid": (
                        correlation.event.characteristic_uuid
                    ),
                    "payload_hex": correlation.event.payload.hex(" "),
                },
                # Preserve both handles because the screen may display
                # different structure from packet matching
                "mapping": {
                    "service_uuid": correlation.mapping.service_uuid,
                    "service_handle": correlation.mapping.service_handle,
                    "characteristic_uuid": (
                        correlation.mapping.characteristic_uuid
                    ),
                    "declaration_handle": (
                        correlation.mapping.declaration_handle
                    ),
                    "value_handle": correlation.mapping.value_handle,
                    "properties": list(correlation.mapping.properties),
                },
                "packet": packet_record,
                
            }
        )
    
    matched_count = sum(
        correlation.matched for correlation in correlations
    )
    
    return {
        # The screen can reject incompatible report layouts instead
        # of interpreting incorrectly
        "schema_version": 1,
        "event_log": str(event_log_path),
        "pcap": str(pcap_path),
        "correlation_window_seconds": window_seconds,
        "event_count": len(correlations),
        "matched_count": matched_count,
        "unmatched_count": len(correlations) - matched_count,
        "correlations": records,
    }

def write_json_report(report: object, output_path: Path) -> None:
    # Scan and correlation reports use same formatting so 
    # saved artifacts behave consistently
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    
def write_correlation_report(
    correlations: list[GattCorrelation],
    event_log_path: Path,
    pcap_path: Path,
    output_path: Path,
    window_seconds: float,
) -> None:
    # Keep analyzer and live runtime on one report-writing path
    # Saved evidence uess same schema/source-file
    report = build_correlation_report(
        correlations,
        event_log_path,
        pcap_path,
        window_seconds,
    )
    write_json_report(report, output_path)

def write_scan_report(results: ScanResults, output_path: Path) -> None:
    report = build_scan_report(results)
    write_json_report(report, output_path)