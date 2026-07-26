from bleak import BleakClient
from bleak.backends.device import BLEDevice
from .profile_config.model import ProtocolProfile

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
            
    def validate_profile(self, profile: ProtocolProfile) -> None:
        if not self._client.is_connected:
            raise RuntimeError("Cannot validate a profile while disconnected")
        
        # Check profile against connected GATT db, not advertisement
        service = self._client.services.get_service(profile.service_uuid)
        
        if service is None:
            raise ValueError(
                f"{profile.name}: service {profile.service_uuid} was not found"
            )
        
        rx_characteristic = service.get_characteristic(profile.rx_uuid)
        
        if rx_characteristic is None:
            raise ValueError(
                f"{profile.name}: RX characteristic {profile.rx_uuid} was not found"
            )
            
        if not any(
            property_name in rx_characteristic.properties
            for property_name in ("write", "write-without-response")
        ):
            raise ValueError(
                f"{profile.name}: RX characteristic does not support writes"
            )
            
        tx_characteristic = service.get_characteristic(profile.tx_uuid)
            
        if tx_characteristic is None:
            raise ValueError(
                f"{profile.name}: TX characteristic {profile.tx_uuid} was not found"
            )
                
        if "notify" not in tx_characteristic.properties:
            raise ValueError(
                f"{profile.name}: TX characteristic does not support notifications"
            )
            
    async def write_rx(
        self,
        profile: ProtocolProfile,
        data: bytes,
    ) -> None:
        if not self._client.is_connected:
            raise RuntimeError("Cannot write while disconnected")
        
        # Locate RX within the profile's service
        service = self._client.services.get_service(profile.service_uuid)
        
        if service is None:
            raise ValueError(
                f"{profile.name}: service {profile.service_uuid} was not found"
            )
            
        characteristic = service.get_characteristic(profile.rx_uuid)
        
        if characteristic is None:
            raise ValueError(
                f"{profile.name}: RX characteristic {profile.rx_uuid} was not found"
            )
            
        # Prefer a confirmed write when device supports both BLE write modes
        if "write" in characteristic.properties:
            response = True
        elif "write-without-response" in characteristic.properties:
            response = False
        else:
            raise ValueError(
                f"{profile.name}: RX characteristic does not support writes"
            )
        
        # Use characteristic discovered in connection including handle
        await self._client.write_gatt_char(
            characteristic,
            data,
            response=response,
        )
            
    def print_services(self) -> None:
        if not self._client.is_connected:
            raise RuntimeError("Cannot inspect GATT services while disconnected")
        
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