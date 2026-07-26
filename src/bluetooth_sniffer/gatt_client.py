from bleak import BleakClient
from bleak.backends.device import BLEDevice

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