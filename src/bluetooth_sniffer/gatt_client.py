import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from .profile_config.model import ProtocolProfile

type NotificationHandler = Callable[
    [BleakGATTCharacteristic, bytearray],
    None,
]

type DisconnectedHandler = Callable[[], None]

"""
    Links each characteristic UUID to the temp ATT handle used during
    the same connection, allows Nordic packets to identify the correct characteristic
"""
@dataclass(frozen=True)
class GattCharacteristicMapping:
    service_uuid: str
    service_handle: int
    characteristic_uuid: str
    
    # Keep the declaration handle as GATT context, but match Nordic
    # ATT packets against value_handle - offset of 1
    declaration_handle: int
    value_handle: int
    
    properties: tuple[str, ...]

@dataclass(frozen=True)
class GattDescriptorSnapshot:
    uuid: str
    description: str
    handle: int

@dataclass(frozen=True)
class GattCharacteristicSnapshot:
    uuid: str
    description: str
    declaration_handle: int
    value_handle: int
    properties: tuple[str, ...]
    descriptors: tuple[GattDescriptorSnapshot, ...]

@dataclass(frozen=True)
class GattServiceSnapshot:
    uuid: str
    description: str
    handle: int
    characteristics: tuple[GattCharacteristicSnapshot, ...]

# Keep a connection w/ BleakClient alive across inspection/read/write
class GattClient:
    def __init__(
        self,
        device: BLEDevice,
        disconnected_handler: DisconnectedHandler | None = None
    ) -> None:
        self.device = device
        
        def handle_disconnect(_client: BleakClient) -> None:
            # End runtime session when peripheral drops BLE link
            if disconnected_handler is not None:
                disconnected_handler()
        self._client = BleakClient(
            device,
            disconnected_callback=handle_disconnect,
        )
        
    async def connect(self) -> None:
        await self._client.connect()
        
    async def disconnect(self) -> None:
        if self._client.is_connected:
            await self._client.disconnect()
            
    def _require_connected(self, operation: str) -> None:
        if not self._client.is_connected:
            raise RuntimeError(f"Cannot {operation} while disconnected")
    
    def _get_characteristic(
        self,
        service_uuid: str,
        characteristic_uuid: str,
        *,
        context: str,
    ) -> BleakGATTCharacteristic:
        # Scope lookup to the selected service because separate services may
        # legally contain characteristics with the same UUID.
        service = self._client.services.get_service(service_uuid)

        if service is None:
            raise ValueError(
                f"{context}: service {service_uuid} was not found"
            )

        characteristic = service.get_characteristic(characteristic_uuid)

        if characteristic is None:
            raise ValueError(
                f"{context}: characteristic {characteristic_uuid} was not found"
            )

        return characteristic
           
    def _get_profile_characteristic(
        self,
        profile: ProtocolProfile,
        characteristic_uuid: str,
        role: str
    ) -> BleakGATTCharacteristic:
        # Profile operations still use the shared lookup, while this context
        # identifies whether the missing characteristic was configured as RX or TX.
        return self._get_characteristic(
            profile.service_uuid,
            characteristic_uuid,
            context=f"{profile.name}: {role}",
        )
    
    async def read_characteristic(
        self,
        service_uuid: str,
        characteristic_uuid: str,
    ) -> bytes:
        self._require_connected("read a characteristic")

        characteristic = self._get_characteristic(
            service_uuid,
            characteristic_uuid,
            context="GATT read",
        )

        # Reject unsupported reads here so the touchscreen receives a useful
        # explanation instead of exposing a lower-level BlueZ protocol error.
        if "read" not in characteristic.properties:
            raise ValueError(
                f"Characteristic {characteristic_uuid} does not support reads"
            )

        value = await self._client.read_gatt_char(characteristic)
        return bytes(value)
            
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
    
    def gatt_snapshot(self) -> tuple[GattServiceSnapshot, ...]:
        self._require_connected("inspect the GATT database")

        # Convert connection-owned Bleak objects into plain values that the
        # background runtime can safely deliver to the touchscreen thread.
        return tuple(
            GattServiceSnapshot(
                uuid=service.uuid,
                description=service.description,
                handle=service.handle,
                characteristics=tuple(
                    GattCharacteristicSnapshot(
                        uuid=characteristic.uuid,
                        description=characteristic.description,
                        declaration_handle=characteristic.handle,

                        # Passive ATT operations use the value attribute after
                        # this declaration, so the browser must expose both.
                        value_handle=characteristic.handle + 1,
                        properties=tuple(characteristic.properties),
                        descriptors=tuple(
                            GattDescriptorSnapshot(
                                uuid=descriptor.uuid,
                                description=descriptor.description,
                                handle=descriptor.handle,
                            )
                            for descriptor in characteristic.descriptors
                        ),
                    )
                    for characteristic in service.characteristics
                ),
            )
            for service in self._client.services
        )
    
    def characteristic_mappings(
        self,
    ) -> list[GattCharacteristicMapping]:
        # Correlation needs a reduced view of the same GATT snapshot shown by
        # the browser, keeping handle interpretation consistent in both paths.
        return [
            GattCharacteristicMapping(
                service_uuid=service.uuid,
                service_handle=service.handle,
                characteristic_uuid=characteristic.uuid,
                declaration_handle=characteristic.declaration_handle,
                value_handle=characteristic.value_handle,
                properties=characteristic.properties,
            )
            for service in self.gatt_snapshot()
            for characteristic in service.characteristics
        ]
           
    def print_services(self) -> None:
        # Terminal inspection and the touchscreen now describe the same
        # immutable snapshot rather than interpreting Bleak objects separately.
        for service in self.gatt_snapshot():
            print(f"\nService: {service.description}")
            print(f"    UUID: {service.uuid}")
            print(f"    Handle: {service.handle}")

            for characteristic in service.characteristics:
                properties = ", ".join(characteristic.properties)

                print(
                    f"    Characteristic: {characteristic.description}"
                )
                print(f"        UUID: {characteristic.uuid}")
                print(
                    "        Declaration Handle:"
                    f" {characteristic.declaration_handle}"
                )
                print(
                    f"        Value Handle: {characteristic.value_handle}"
                )
                print(f"        Properties: {properties}")

                for descriptor in characteristic.descriptors:
                    print(f"        Descriptor: {descriptor.description}")
                    print(f"            UUID: {descriptor.uuid}")
                    print(f"            Handle: {descriptor.handle}")    