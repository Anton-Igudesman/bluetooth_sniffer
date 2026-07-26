import asyncio
from collections.abc import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from .profile_config.model import ProtocolProfile

type NotificationHandler = Callable[
    [BleakGATTCharacteristic, bytearray],
    None,
]

# Keep a connection w/ BleakClient alive across inspection/read/write
class GattClient:
    def __init__(self, device: BLEDevice) -> None:
        self.device = device
        self._client = BleakClient(device)
        
    async def connect(self) -> None:
        await self._client.connect()
        
    async def disconnect(self) -> None:
        if self._client.is_connected:
            await self._client.disconnect()
            
    def _require_connected(self, operation: str) -> None:
        if not self._client.is_connected:
            raise RuntimeError(f"Cannot {operation} while disconnected")
            
    def _get_profile_characteristic(
        self,
        profile: ProtocolProfile,
        characteristic_uuid: str,
        role: str
    ) -> BleakGATTCharacteristic:
        # Profile operations resolve RX or TX inside selected service
        service = self._client.services.get_service(profile.service_uuid)
        
        if service is None:
            raise ValueError(
                f"{profile.name}: service {profile.service_uuid} was not found"
            )
            
        characteristic = service.get_characteristic(characteristic_uuid)
        
        if characteristic is None:
            raise ValueError(
                f"{profile.name}: {role} characteristic"
                f" {characteristic_uuid} was not found"
            )
            
        return characteristic
            
    def validate_profile(self, profile: ProtocolProfile) -> None:
        self._require_connected("validate a profile")
        
        # Check profile against connected GATT db, not advertisement
        rx_characteristic = self._get_profile_characteristic(
            profile,
            profile.rx_uuid,
            "RX",
        )
        
        if not any(
            property_name in rx_characteristic.properties
            for property_name in ("write", "write-without-response")
        ):
            raise ValueError(
                f"{profile.name}: RX characteristic does not support writes"
            )
            
        tx_characteristic = self._get_profile_characteristic(
            profile,
            profile.tx_uuid,
            "TX",
        )
                
        if "notify" not in tx_characteristic.properties:
            raise ValueError(
                f"{profile.name}: TX characteristic does not support notifications"
            )
            
    async def write_rx(
        self,
        profile: ProtocolProfile,
        data: bytes,
        *, # with response must be named
        with_response: bool,
    ) -> None:
        self._require_connected("write")
            
        characteristic = self._get_profile_characteristic(
            profile,
            profile.rx_uuid,
            "RX",
        )
            
        # Bleak calls with-response property "write"
        required_property = (
            "write" if with_response else "write-without-response"
        )
        
        if required_property not in characteristic.properties:
            raise ValueError(
                f"{profile.name}: RX characteristic does not support"
                f" {required_property}"
            )
        
        # Use characteristic discovered in connection including handle
        await self._client.write_gatt_char(
            characteristic,
            data,
            response=with_response,
        )
        
    async def listen_tx(
        self,
        profile: ProtocolProfile,
        duration_seconds: float,
        handler: NotificationHandler,
    ) -> None:
        self._require_connected("listen")
        
        characteristic = self._get_profile_characteristic(
            profile,
            profile.tx_uuid,
            "TX",
        )
        
        if "notify" not in characteristic.properties:
            raise ValueError(
                f"{profile.name}: TX characteristic does not support notifications"
            )
        
        await self._client.start_notify(characteristic, handler)
        
        try:
            # Keep the event loop available while Bleak delivers TX notifications
            await asyncio.sleep(duration_seconds)
        finally:
            # Remove TX subscription before the outer connection cleanup runs
            await self._client.stop_notify(characteristic)
            
    def print_services(self) -> None:
        self._require_connected("inspect GATT services")
        
        # Service collection only available during connection
        for service in self._client.services:
            print(f"\nService: {service.description}")
            print(f"    UUID: {service.uuid}")
            print(f"    Handle: {service.handle}")
            
            for characteristic in service.characteristics:
                properties = ", ".join(characteristic.properties)
                
                print(f"    Characteristic: {characteristic.description}")
                print(f"        UUID: {characteristic.uuid}")
                print(f"        Handle: {characteristic.handle}")
                print(f"        Properties: {properties}")
                
                for descriptor in characteristic.descriptors:
                    print(f"        Descriptor: {descriptor.description}")
                    print(f"            UUID: {descriptor.uuid}")
                    print(f"            Handle: {descriptor.handle}")