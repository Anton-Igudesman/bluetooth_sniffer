import argparse
import asyncio
from datetime import timedelta
from pathlib import Path

from .correlation import (
    correlate_gatt_events,
    read_gatt_events,
    read_gatt_mappings,
)
from .pcap_analysis import read_att_packets

DEFAULT_CORRELATION_WINDOW_SECONDS = 2.0

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Correlate application GATT events with a Nordic PCAP"
    )

    parser.add_argument(
        "--event-log",
        type=Path,
        required=True,
        help="JSONL application event log from the captured session",
    )
    parser.add_argument(
        "--pcap",
        type=Path,
        required=True,
        help="Nordic PCAP recorded during the same session",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=DEFAULT_CORRELATION_WINDOW_SECONDS,
        help="Maximum event-to-packet time difference in seconds",
    )

    arguments = parser.parse_args()

    if arguments.window < 0:
        parser.error("--window cannot be negative")

    return arguments

async def main() -> None:
    arguments = parse_arguments()

    # Both files describe the same BLE session from different observation
    # layers; correlation links application intent to passive radio evidence.
    events = read_gatt_events(arguments.event_log)
    mappings = read_gatt_mappings(arguments.event_log)
    packets = await read_att_packets(arguments.pcap)

    correlations = correlate_gatt_events(
        events,
        mappings,
        packets,
        max_time_delta=timedelta(seconds=arguments.window),
    )

    matched_count = sum(
        correlation.matched for correlation in correlations
    )
    print(f"Matched GATT events: {matched_count}/{len(correlations)}")

    for correlation in correlations:
        event = correlation.event
        status = "MATCHED" if correlation.matched else "UNMATCHED"

        print(
            f"{status}: {event.event_type}"
            f" {event.characteristic_uuid}"
            f" [{event.payload.hex(' ')}]"
        )

        if correlation.packet is not None:
            print(
                f"    PCAP frame: {correlation.packet.frame_number}"
                f", RSSI: {correlation.packet.rssi} dBm"
            )

def run() -> None:
    asyncio.run(main())

if __name__ == "__main__":
    run()