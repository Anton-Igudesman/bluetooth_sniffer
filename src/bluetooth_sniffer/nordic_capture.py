import asyncio
import signal
from pathlib import Path
import os

class NordicCapture:
    def __init__(self, port: str, output_path: Path) -> None:
        self.port = port
        self.output_path = output_path
        self._process: asyncio.subprocess.Process | None = None
        
    async def start(self, device_address: str) -> None:
        if self._process is not None:
            raise RuntimeError("Nordic capture is already running")
        
        # A PCAP represents a single session
        if self.output_path.exists():
            raise FileExistsError(
                f"Capture output already exists: {self.output_path}"
            )
            
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Pass arguments directly
        self._process = await asyncio.create_subprocess_exec(
            "nrfutil",
            "ble-sniffer",
            "sniff",
            "--port",
            self.port,
            "--output-pcap-file",
            str(self.output_path),
            "--follow",
            device_address,
            start_new_session=True,
        )
        
        try:
            await self._wait_until_started()
        except Exception:
            await self.stop()
            raise
            
    async def _wait_until_started(self) -> None:
        if self._process is None:
            raise RuntimeError("Nordic capture process was not created")
        
        try:
            async with asyncio.timeout(5):
                while not self.output_path.exists():
                    if self._process.returncode is not None:
                        raise RuntimeError(
                            "Nordic capture exited before creating PCAP"
                        )
                        
                    await asyncio.sleep(0.05)
                    
        except TimeoutError as error:
            raise RuntimeError(
                "Nordic capture did not create PCAP within 5 seconds"
            ) from error
    
    async def stop(self) -> None:
        process = self._process
        
        if process is None:
            return
        
        try:
            if process.returncode is None:
                # Match terminal Ctrl+C by signaling nrfutil and helper
                try:
                    os.killpg(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
            
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            # Terminate the entire capture group if graceful shutdown stalls
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            
            await process.wait()
        finally:
            self._process = None
            