import argparse
import asyncio
from datetime import timedelta
from pathlib import Path

from .correlation import analyze_session
from .reporting import write_correlation_report

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
        "--output",
        type=Path,
        help="Optional path for a structured JSON correlation report",
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

    # Use same session-analysis boundary that live application
    # calls after capture has finished
    correlations = await analyze_session(
        arguments.event_log,
        arguments.pcap,
        max_time_delta=timedelta(seconds=arguments.window),
    )
    
    if arguments.output is not None:
        # Save same correlation evidence in a form for
        # future screen to consume without terminal parsing
        write_correlation_report(
            correlations,
            arguments.event_log,
            arguments.pcap,
            arguments.output,
            arguments.window,
        )
        
        print(f"Saved correlation report to {arguments.output}")

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