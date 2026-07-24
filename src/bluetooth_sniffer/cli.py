import argparse
import asyncio
from pathlib import Path

from .profile_config.loader import load_profile
from .scanner import BluetoothScanner

DEFAULT_SCAN_DURATION_SECONDS = 10.0

def parse_arguments() -> argparse.Namespace:
    # Keep launch-time input handling separate from Bluetooth scanning
    parser = argparse.ArgumentParser(
        description="Scan for nearby Bluetooth Low Energy devices"
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_SCAN_DURATION_SECONDS,
        help="Number of seconds to scan (default: %(default)s)",
    )

    # No profile means unfiltered scan
    parser.add_argument(
        "--profile",
        type=Path,
        help="Optional path to a protocol profile TOML file",
    )

    return parser.parse_args()

async def main() -> None:
    arguments = parse_arguments()

    # Start w/ generic scan settings
    service_uuid: str | None = None
    target = "all BLE advertisers"

    if arguments.profile is not None:
        profile = load_profile(arguments.profile)
        service_uuid = profile.service_uuid
        target = profile.name

    # Pass scan settings only
    scanner = BluetoothScanner(
        service_uuid=service_uuid,
        duration_seconds=arguments.duration,
    )

    print(f"Scanning for {target} for {arguments.duration:g} seconds")

    await scanner.scan()
    scanner.print_scan_results()

if __name__ == "__main__":
    asyncio.run(main())