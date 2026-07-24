import json
from pathlib import Path

from .scanner import ScanResults

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

def write_scan_report(results: ScanResults, output_path: Path) -> None:
    report = build_scan_report(results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )