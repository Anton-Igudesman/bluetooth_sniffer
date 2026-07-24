from bleak import BleakScanner

# Return types for discovery results
from bleak.backends.device import BLEDevice # passed to connection
from bleak.backends.scanner import AdvertisementData # RSSI/man. data

type ScanResults = dict[str, tuple[BLEDevice, AdvertisementData]]

class BluetoothScanner:
    # Manage BLE Discovery configuration and scan results

    def __init__(
        self,
        duration_seconds: float,
        service_uuid: str | None = None,
    ) -> None:
        if duration_seconds <= 0:
            raise ValueError("Scan duration must be greater than zero.")
        self.service_uuid = service_uuid
        self.duration_seconds = duration_seconds
        self.results: ScanResults = {}

    async def scan(self) -> ScanResults:
        # Bleak requires list of UUID filters or None if not filtering
        service_uuids = (
            [self.service_uuid]
            if self.service_uuid is not None
            else None
        )

        self.results = await BleakScanner.discover(
            timeout=self.duration_seconds,
            return_adv=True, # Include advertisement data
            service_uuids=service_uuids,
        )

        return self.results

    def print_scan_results(self) -> None:
        if not self.results:
            print("No matching BLE devices found.")
            return

        for device, advertisement in self.results.values():
            # Prefer current advertised name of BlueZ potentially cached info
            name = advertisement.local_name or device.name or "Unknown"

            # Convert raw manufacturer bytes to readable hex
            manufacturer_data = {
                f"0x{company_id:04X}": payload.hex(" ")
                for company_id, payload in advertisement.manufacturer_data.items()
            }

            print(f"\n{name} ({device.address})")
            print(f"    RSSI: {advertisement.rssi} dBm")
            print(f"    Service UUIDs: {', '.join(advertisement.service_uuids)}")
            print(f"    Manufacturer data: {manufacturer_data or 'None'}")
