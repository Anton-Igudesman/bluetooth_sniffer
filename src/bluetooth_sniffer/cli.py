import argparse
import asyncio
from pathlib import Path

from .profile_config.loader import load_profile
from .profile_config.model import ProtocolProfile
from .scanner import BluetoothScanner
from .reporting import write_scan_report
from .gatt_client import GattClient
from .event_log import EventLogger

from bleak.backends.device import BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from .selection import find_devices

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
    
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for a JSON scan report",
    )
    
    parser.add_argument(
        "--device", # str type by default
        help="Connect by exact name or current address from this scan"
    )
    
    parser.add_argument(
        "--write",
        metavar="TEXT",
        help="UTF-8 text to write to selected profile's RX characteristic"
    )
    
    parser.add_argument(
        "--write-mode",
        choices=("with-response", "without-response"),
        default="with-response",
        help="BLE write mode (default: %(default)s)",
    )
    
    parser.add_argument(
        "--listen",
        type=float,
        metavar="SECONDS",
        help="Listen for TX notifications for the specified number of seconds",
    )
    
    parser.add_argument(
        "--event-log",
        type=Path,
        help="Optional path for timestamped JSONL application events",
    )

    arguments = parser.parse_args()
    
    # A write needs both profile's RX UUID and device to receive data
    gatt_action_requested = (
        arguments.write is not None or arguments.listen is not None
    )
    
    # GATT writes and notifications need profile UUIDs and selected device
    if gatt_action_requested:
        if arguments.profile is None:
            parser.error("--write and --listen require a specified profile")
            
        if arguments.device is None:
            parser.error("--write and --listen require a specified device")
            
    if arguments.listen is not None and arguments.listen <= 0:
        parser.error("--listen must be greater than zero")
            
    return arguments

def choose_device(devices: list[BLEDevice]) -> BLEDevice:
    # A single match can connect without asking user to choose
    if len(devices) == 1:
        return devices[0]
    
    # Number only device that match value supplied with --device
    print("\nMultiple devices matched:")
    
    for number, device in enumerate(devices, start=1):
        display_name = device.name or "Unknown"
        print(f"    {number}. {display_name} ({device.address})")
        
    while True:
        choice = input("Select device number: ").strip()
        
        if choice.isdecimal():
            number = int(choice)
            
            # Clamp values
            if 1 <= number <= len(devices):
                # Convert displayed number to zero indexed list
                return devices[number - 1]
        
        print(f"Enter a number from 1 to {len(devices)}")
        
def print_notification(
    characteristic: BleakGATTCharacteristic,
    data: bytearray,
) -> None:
    # Convert Bleak's callback into payload for display
    payload = bytes(data)
    
    print(f"\nNotification from {characteristic.uuid}")
    print(f"    Hex: {payload.hex(' ')}")
    
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        # Hex preserves arbitrary binary data when no text representation exists
        return
    
    print(f"    UTF-8: {text}")
    
async def main() -> None:
    arguments = parse_arguments()
    event_logger = EventLogger(arguments.event_log)
    
    event_logger.record(
        "session.started",
        scan_duration_seconds=arguments.duration,
    )
    
    def handle_notification(
        characteristic: BleakGATTCharacteristic,
        data: bytearray,
    ) -> None:
        payload = bytes(data)
        
        # Notification feeds both session log and terminal display
        event_logger.record(
            "gatt.notification",
            characteristic_uuid=characteristic.uuid,
            payload_hex=payload.hex(" "),
            payload_size_bytes=len(payload),
        )
        
        print_notification(characteristic, data)

    # Start w/ generic scan settings
    profile: ProtocolProfile | None = None
    service_uuid: str | None = None
    target = "all BLE advertisers"

    if arguments.profile is not None:
        profile = load_profile(arguments.profile)

    # Pass scan settings only
    scanner = BluetoothScanner(
        service_uuid=service_uuid,
        duration_seconds=arguments.duration,
    )

    print(f"Scanning for {target} for {arguments.duration:g} seconds")

    results = await scanner.scan()
    event_logger.record(
        "scan.completed",
        device_count=len(results),
    )
    
    scanner.print_scan_results()
    
    if arguments.output is not None:
        # Save BLE scan report to location supplied with --output
        write_scan_report(results, arguments.output)
        print(f"Saved scan report to {arguments.output}")
        
    if arguments.device is not None:
        matching_devices = find_devices(results, arguments.device)
        device = choose_device(matching_devices)
        client = GattClient(device)
        display_name = device.name or "Unknown"
        
        print(f"\nConnecting to {display_name} ({device.address})")

        # Remember connect completed so logs only real connection closure
        connection_opened = False
        
        try:
            await client.connect()
            connection_opened = True
            
            event_logger.record(
                "connection.opened",
                device_name=display_name,
                device_address=device.address,
            )
            print("Connected")
            
            if profile is not None:
                client.validate_profile(profile)
                event_logger.record(
                    "profile.validated",
                    profile_name=profile.name,
                    service_uuid=profile.service_uuid,
                )
                print(f"Validated profile: {profile.name}")
                
                if arguments.write is not None:
                    # BLE characteristics xfer bytes, encode CLI text before sending
                    payload = arguments.write.encode("utf-8")
                    with_response = arguments.write_mode == "with-response"
                    
                    await client.write_rx(
                        profile, 
                        payload,
                        with_response=with_response,
                        )
                    print(
                        f"Sent {len(payload)} bytes to {profile.name} RX"
                        f" using {arguments.write_mode}"
                        )
                    event_logger.record(
                        "gatt.write",
                        profile_name=profile.name,
                        characteristic_uuid=profile.rx_uuid,
                        payload_hex=payload.hex(" "),
                        payload_size_bytes=len(payload),
                        write_mode=arguments.write_mode,
                    )
                    
                if arguments.listen is not None:
                    print(
                        f"Listening for {profile.name} TX notifications"
                        f" for {arguments.listen:g} seconds"
                    )
                
                    await client.listen_tx(
                        profile,
                        arguments.listen,
                        handle_notification,
                    )
                   
            client.print_services()
            
        except Exception as error:
            # Preserve the original traceback after recording failed session
            event_logger.record(
                "session.failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
            raise
        finally:
            # End GATT connection even if service inspection fails
            await client.disconnect()
            
            if connection_opened:
                event_logger.record(
                    "connection.closed",
                    device_name=display_name,
                    device_address=device.address,
                )
    
    event_logger.record("session.completed")

def run() -> None:
    asyncio.run(main())

if __name__ == "__main__":
    run()