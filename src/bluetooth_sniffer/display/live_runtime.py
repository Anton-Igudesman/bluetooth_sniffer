import asyncio
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread
from typing import Literal

from concurrent.futures import Future

from ..scanner import BluetoothScanner, ScanResults

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
class RuntimeFailed:
    operation: Literal["scan"]
    error_type: str
    message: str

type LiveUpdate = ScanStarted | ScanCompleted | RuntimeFailed

class LiveRuntime:
    def __init__(self) -> None:
        self._updates: Queue[LiveUpdate] = Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = Event()
        self._thread: Thread | None = None
        self._scan_future: Future[None] | None = None
        self._scan_results: ScanResults = {}

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