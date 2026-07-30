import asyncio
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread
from typing import Literal

from datetime import UTC, datetime

from concurrent.futures import Future

from ..scanner import BluetoothScanner, ScanResults
from ..gatt_client import GattClient, GattServiceSnapshot

@dataclass(frozen=True)
class LiveDevice:
    address: str
    name: str
    rssi: int
    service_uuids: tuple[str, ...]

@dataclass(frozen=True)
class ScanStarted:
    duration_seconds: float

@dataclass(frozen=True)
class ScanCompleted:
    devices: tuple[LiveDevice, ...]
    
@dataclass(frozen=True)
class ConnectionStarted:
    device_address: str

@dataclass(frozen=True)
class GattDiscovered:
    device_address: str
    services: tuple[GattServiceSnapshot, ...]
    
@dataclass(frozen=True)
class CharacteristicRead:
    service_uuid: str
    characteristic_uuid: str
    value: bytes

@dataclass(frozen=True)
class CharacteristicWritten:
    service_uuid: str
    characteristic_uuid: str
    value: bytes
    with_response: bool

@dataclass(frozen=True)
class NotificationSubscriptionStarted:
    service_uuid: str
    characteristic_uuid: str

@dataclass(frozen=True)
class CharacteristicValueReceived:
    service_uuid: str
    characteristic_uuid: str
    timestamp: datetime
    value: bytes

@dataclass(frozen=True)
class NotificationSubscriptionStopped:
    service_uuid: str
    characteristic_uuid: str

@dataclass(frozen=True)
class ConnectionClosed:
    device_address: str
    connection_opened: bool

@dataclass(frozen=True)
class RuntimeFailed:
    operation: Literal[
        "scan",
        "connect",
        "disconnect",
        "read",
        "write",
        "subscribe",
        "unsubscribe",
    ]
    error_type: str
    message: str

type LiveUpdate = (
    ScanStarted
    | ScanCompleted
    | ConnectionStarted
    | GattDiscovered
    | CharacteristicRead
    | CharacteristicWritten
    | NotificationSubscriptionStarted
    | CharacteristicValueReceived
    | NotificationSubscriptionStopped
    | ConnectionClosed
    | RuntimeFailed
)

class LiveRuntime:
    def __init__(self) -> None:
        self._updates: Queue[LiveUpdate] = Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = Event()
        self._thread: Thread | None = None
        self._scan_future: Future[None] | None = None
        self._scan_results: ScanResults = {}
        
        # Retain the GATT client on its owning event loop so later read, write, and
        # notification operations use the same live connection and discovered handles.
        self._connection_future: Future[None] | None = None
        self._gatt_client: GattClient | None = None
        self._disconnect_event: asyncio.Event | None = None
        
        self._gatt_operation_future: Future[None] | None = None
        
        # Track the actual subscribed UUIDs so STOP always targets the active
        # callback even if the user navigates to another characteristic screen.
        self._notification_target: tuple[str, str] | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Live runtime has already been started")

        self._loop_ready.clear()
        
        # Bleak operations will remain on this worker thread while Tk continues
        # handling screen redraws and touch input on the main thread.
        self._thread = Thread(
            target=self._run_loop,
            name="bluetooth-live-runtime",
            daemon=True,
        )
        self._thread.start()

        if not self._loop_ready.wait(timeout=5):
            raise RuntimeError(
                "Live runtime did not start within 5 seconds"
            )

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._loop_ready.set()

        try:
            loop.run_forever()
        finally:
            # Closing the touchscreen during a BLE operation must cancel its
            # async task before closing the loop that owns BlueZ resources.
            pending_tasks = asyncio.all_tasks(loop)

            for task in pending_tasks:
                task.cancel()

            if pending_tasks:
                loop.run_until_complete(
                    asyncio.gather(
                        *pending_tasks,
                        return_exceptions=True,
                    )
                )

            loop.close()
            
    def start_scan(self, duration_seconds: float) -> None:
        if duration_seconds <= 0:
            raise ValueError("Scan duration must be greater than zero")
        
        loop = self._loop
        
        if loop is None or not loop.is_running():
            raise RuntimeError("Live runtime is not running")
        
        if self._scan_future is not None and not self._scan_future.done():
            raise RuntimeError("A Bluetooth scan is already running")

        if (
            self._connection_future is not None
            and not self._connection_future.done()
        ):
            raise RuntimeError(
                "Cannot scan while a device connection is open"
            )
        # This thead-safe submission returns to Tk
        # Future retained to block a second scan until this has completed
        self._scan_future = asyncio.run_coroutine_threadsafe(
            self._scan(duration_seconds),
            loop,
        )
    
    async def _scan(self, duration_seconds: float) -> None:
        self._updates.put(
            ScanStarted(duration_seconds = duration_seconds)
        )
        
        try:
            scanner = BluetoothScanner(
                duration_seconds=duration_seconds,
            )
            results = await scanner.scan()
            
        except Exception as error:
            # UI receives printable failure instead of allowing
            # async exception to disappear in worker thread
            self._updates.put(
                RuntimeFailed(
                    operation="scan",
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
            return
        
        # Keep original BLEDevice objects for connection step
        self._scan_results = results
        
        devices = tuple(
            sorted(
                (
                    LiveDevice(
                        address=device.address,
                        name=(
                            advertisement.local_name
                            or device.name
                            or "Unknown"
                        ),
                        rssi=advertisement.rssi,
                        service_uuids=tuple(
                            advertisement.service_uuids
                        ),
                    )
                    for device, advertisement in results.values()
                ),
                key=lambda item: item.rssi,
                reverse=True,
            )
        )
        
        self._updates.put(ScanCompleted(devices=devices))

    def start_connection(self, device_address: str) -> None:
        device_address = device_address.strip()

        if not device_address:
            raise ValueError("Device address must not be empty")

        loop = self._loop

        if loop is None or not loop.is_running():
            raise RuntimeError("Live runtime is not running")

        if self._scan_future is not None and not self._scan_future.done():
            raise RuntimeError(
                "Cannot connect while a Bluetooth scan is running"
            )

        if (
            self._connection_future is not None
            and not self._connection_future.done()
        ):
            raise RuntimeError("A device connection is already open")

        self._connection_future = asyncio.run_coroutine_threadsafe(
            self._connection_session(device_address),
            loop,
        )

    def _prepare_gatt_operation(
        self,
    ) -> tuple[asyncio.AbstractEventLoop, GattClient]:
        loop = self._loop
        client = self._gatt_client

        if loop is None or not loop.is_running():
            raise RuntimeError("Live runtime is not running")

        if client is None:
            raise RuntimeError(
                "No connected device is available for a GATT operation"
            )

        # BlueZ should finish the current attribute request before another read
        # or write is submitted through this connection.
        if (
            self._gatt_operation_future is not None
            and not self._gatt_operation_future.done()
        ):
            raise RuntimeError("A GATT operation is already running")

        return loop, client
    
    def start_characteristic_read(
        self,
        service_uuid: str,
        characteristic_uuid: str,
    ) -> None:
        loop, client = self._prepare_gatt_operation()

        # Pass the active client into this task so the read stays tied to the
        # connection whose GATT hierarchy is currently shown on the touchscreen.
        self._gatt_operation_future = asyncio.run_coroutine_threadsafe(
            self._read_characteristic(
                client,
                service_uuid,
                characteristic_uuid,
            ),
            loop,
        )
        
    async def _read_characteristic(
        self,
        client: GattClient,
        service_uuid: str,
        characteristic_uuid: str,
    ) -> None:
        try:
            value = await client.read_characteristic(
                service_uuid,
                characteristic_uuid,
            )
        except Exception as error:
            # Convert worker-thread failures into a display update instead of
            # leaving the user with an unchanged characteristic screen.
            self._updates.put(
                RuntimeFailed(
                    operation="read",
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
            return

        self._updates.put(
            CharacteristicRead(
                service_uuid=service_uuid,
                characteristic_uuid=characteristic_uuid,
                value=value,
            )
        )
    
    def start_characteristic_write(
        self,
        service_uuid: str,
        characteristic_uuid: str,
        value: bytes,
        *,
        with_response: bool,
    ) -> None:
        loop, client = self._prepare_gatt_operation()

        self._gatt_operation_future = asyncio.run_coroutine_threadsafe(
            self._write_characteristic(
                client,
                service_uuid,
                characteristic_uuid,
                value,
                with_response=with_response,
            ),
            loop,
        )

    async def _write_characteristic(
        self,
        client: GattClient,
        service_uuid: str,
        characteristic_uuid: str,
        value: bytes,
        *,
        with_response: bool,
    ) -> None:
        try:
            await client.write_characteristic(
                service_uuid,
                characteristic_uuid,
                value,
                with_response=with_response,
            )
        except Exception as error:
            # Report the rejected payload or mode without treating it as a
            # connection failure; the user may choose another supported mode.
            self._updates.put(
                RuntimeFailed(
                    operation="write",
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
            return

        self._updates.put(
            CharacteristicWritten(
                service_uuid=service_uuid,
                characteristic_uuid=characteristic_uuid,
                value=value,
                with_response=with_response,
            )
        )
    
    def start_characteristic_subscription(
        self,
        service_uuid: str,
        characteristic_uuid: str,
    ) -> None:
        if self._notification_target is not None:
            raise RuntimeError(
                "Another characteristic subscription is already active"
            )

        loop, client = self._prepare_gatt_operation()
        self._gatt_operation_future = asyncio.run_coroutine_threadsafe(
            self._subscribe_characteristic(
                client,
                service_uuid,
                characteristic_uuid,
            ),
            loop,
        )

    async def _subscribe_characteristic(
        self,
        client: GattClient,
        service_uuid: str,
        characteristic_uuid: str,
    ) -> None:
        def handle_value(
            _characteristic: object,
            value: bytearray,
        ) -> None:
            # Copy Bleak's mutable bytearray before it crosses into Tk's queue;
            # every displayed event must preserve the bytes received at that moment.
            self._updates.put(
                CharacteristicValueReceived(
                    service_uuid=service_uuid,
                    characteristic_uuid=characteristic_uuid,
                    timestamp=datetime.now(UTC),
                    value=bytes(value),
                )
            )

        try:
            await client.subscribe_characteristic(
                service_uuid,
                characteristic_uuid,
                handle_value,
            )
        except Exception as error:
            self._updates.put(
                RuntimeFailed(
                    operation="subscribe",
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
            return

        self._notification_target = (
            service_uuid,
            characteristic_uuid,
        )
        self._updates.put(
            NotificationSubscriptionStarted(
                service_uuid=service_uuid,
                characteristic_uuid=characteristic_uuid,
            )
        )

    def stop_characteristic_subscription(self) -> None:
        target = self._notification_target

        if target is None:
            raise RuntimeError("No characteristic subscription is active")

        loop, client = self._prepare_gatt_operation()
        service_uuid, characteristic_uuid = target
        self._gatt_operation_future = asyncio.run_coroutine_threadsafe(
            self._unsubscribe_characteristic(
                client,
                service_uuid,
                characteristic_uuid,
            ),
            loop,
        )

    async def _unsubscribe_characteristic(
        self,
        client: GattClient,
        service_uuid: str,
        characteristic_uuid: str,
    ) -> None:
        try:
            await client.unsubscribe_characteristic(
                service_uuid,
                characteristic_uuid,
            )
        except Exception as error:
            self._updates.put(
                RuntimeFailed(
                    operation="unsubscribe",
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
            return

        self._notification_target = None
        self._updates.put(
            NotificationSubscriptionStopped(
                service_uuid=service_uuid,
                characteristic_uuid=characteristic_uuid,
            )
        )
    
    async def _connection_session(self, device_address: str) -> None:
        self._updates.put(
            ConnectionStarted(device_address=device_address)
        )

        client: GattClient | None = None
        connected = False

        try:
            # The UI passes an address from the same completed scan, allowing
            # us to recover the original BLEDevice instead of reconnecting from
            # a hardcoded or previously cached address.
            scan_result = self._scan_results.get(device_address)

            if scan_result is None:
                raise ValueError(
                    f"{device_address} is not available in the current scan"
                )

            device, _advertisement = scan_result
            disconnect_event = asyncio.Event()
            
            # Manual and peripheral-initiated disconnects release the same
            client = GattClient(
                device,
                disconnected_handler=disconnect_event.set,
            )
            await client.connect()
            connected = True

            self._gatt_client = client
            self._disconnect_event = disconnect_event

            # Discovery happens on the Bleak worker loop; Tk receives only the
            # immutable snapshot and never accesses live BlueZ objects.
            services = client.gatt_snapshot()
            self._updates.put(
                GattDiscovered(
                    device_address=device_address,
                    services=services,
                )
            )

            # Keep this coroutine and its GattClient alive for later attribute
            # reads, writes, and notification subscriptions from the browser.
            await self._disconnect_event.wait()

        except Exception as error:
            self._updates.put(
                RuntimeFailed(
                    operation="connect",
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )

        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception as error:
                    self._updates.put(
                        RuntimeFailed(
                            operation="disconnect",
                            error_type=type(error).__name__,
                            message=str(error),
                        )
                    )

            self._gatt_client = None
            self._disconnect_event = None
            
            # BlueZ removes subscriptions when the connection closes; clear our
            # matching state so the next device can create a new subscription.
            self._notification_target = None
            
            # Tk needs a final update after success, failure, cancel
            # Whether to allow another scan/connection
            self._updates.put(
                ConnectionClosed(
                    device_address=device_address,
                    connection_opened=connected,
                )
            )

    def request_disconnect(self) -> None:
        connection_future = self._connection_future

        if connection_future is None or connection_future.done():
            return

        disconnect_event = self._disconnect_event
        loop = self._loop

        if disconnect_event is not None and loop is not None:
            loop.call_soon_threadsafe(disconnect_event.set)
        else:
            # Cancellation covers BACK or CLOSE while connection setup is still
            # waiting for BlueZ and has not created its disconnect event yet.
            connection_future.cancel()
    
    def drain_updates(self) -> tuple[LiveUpdate, ...]:
        updates: list[LiveUpdate] = []

        while True:
            try:
                updates.append(self._updates.get_nowait())
            except Empty:
                return tuple(updates)

    def close(self) -> None:
        loop = self._loop
        thread = self._thread

        if loop is None or thread is None:
            return

        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)

        if thread.is_alive():
            raise RuntimeError(
                "Live runtime did not stop within 5 seconds"
            )

        self._loop = None
        self._thread = None