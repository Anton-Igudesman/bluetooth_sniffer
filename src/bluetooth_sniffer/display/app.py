import argparse
import tkinter as tk
from pathlib import Path

from .model import CorrelationReport, load_correlation_report
from ..scanner import DEFAULT_SCAN_DURATION_SECONDS
from ..gatt_client import GattServiceSnapshot
from .live_runtime import (
    ConnectionClosed,
    ConnectionStarted,
    GattDiscovered,
    LiveDevice,
    LiveRuntime,
    RuntimeFailed,
    ScanCompleted,
    ScanStarted,
)

# Screen color palette
BACKGROUND_COLOR = "#0B1117"
PRIMARY_TEXT_COLOR = "#E6EDF3"
MUTED_TEXT_COLOR = "#8B949E"
SUCCESS_COLOR = "#3FB950"
WARNING_COLOR = "#D29922"

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display a Bluetooth correlation report"
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Structured correlation JSON report to display",
    )
    parser.add_argument(
        "--scan-duration",
        type=float,
        default=DEFAULT_SCAN_DURATION_SECONDS,
        help="Live BLE scan duration in seconds (default: %(default)s)",
    )
    
    return parser.parse_args()

class CorrelationDashboard:
    def __init__(
        self,
        root: tk.Tk,
        report: CorrelationReport,
        scan_duration_seconds: float,
    ) -> None:
        self.root = root
        self.report = report
        self.summary = report.summary
        
        if scan_duration_seconds <= 0:
            raise ValueError("Scan duration must be greater than zero"
            )
            
        self.scan_duration_seconds = scan_duration_seconds
        self.live_runtime = LiveRuntime()
        self.live_runtime_started = False
        self.poll_job: str | None = None
        
        # Values survive screen navigation
        self.live_devices: tuple[LiveDevice, ...] = ()
        self.live_status_text = "READY TO SCAN"
        self.live_status_color = MUTED_TEXT_COLOR
        self.live_status_label: tk.Label | None = None
        self.live_devices_list: tk.Listbox | None = None
        
        # Preserve the chosen device and its connected GATT hierarchy while the user
        # moves between connection, service, characteristic, and descriptor screens.
        self.selected_live_device: LiveDevice | None = None
        self.gatt_services: tuple[GattServiceSnapshot, ...] = ()
        self.gatt_services_list: tk.Listbox | None = None
        self.connection_status_text = "DISCONNECTED"
        self.connection_status_color = MUTED_TEXT_COLOR
        self.connection_status_label: tk.Label | None = None
        self.return_to_scan_after_disconnect = False
        
        self.connection_session_finished = True
        self.connection_failed = False
        
        self.root.title("Bluetooth Sniffer")
        self.root.configure(background=BACKGROUND_COLOR)
        
        # Size application directly from Waveshare X screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        self.root.overrideredirect(True)
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        
        # WIndow-manager close and on-screen CLOSE share same worker cleanup
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._build_summary()
    
    def _close(self) -> None:
        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None
            
        try:
            self.live_runtime.close()
        finally:
            # Destroy Tk even if worker shutdown reports LC fail
            self.root.destroy()
    
    def _clear_screen(self) -> None:
        # Stop runtime updates from targeting widgets destroyed during navigation
        self.live_status_label = None
        self.live_devices_list = None
        self.connection_status_label = None
        self.gatt_services_list = None
        
        # Screen navigation replaces widgets but keeps the validated report in memory
        for widget in self.root.winfo_children():
            widget.destroy()
            
    @staticmethod
    def _shorten(value: str, limit: int) -> str:
        # Preserve full payload preventing display leaks
        return value if len(value) <= limit else f"{value[:limit - 3]}..."
    
    def _build_live_scan(self) -> None:
        self._clear_screen()

        container = tk.Frame(
            self.root,
            background=BACKGROUND_COLOR,
            padx=12,
            pady=8,
        )
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text="LIVE BLE SCAN",
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 12, "bold"),
        ).pack(pady=(0, 4))

        self.live_status_label = tk.Label(
            container,
            text=self.live_status_text,
            background=BACKGROUND_COLOR,
            foreground=self.live_status_color,
            font=("DejaVu Sans", 9, "bold"),
            wraplength=440,
        )
        self.live_status_label.pack(fill="x", pady=(0, 6))

        self.live_devices_list = tk.Listbox(
            container,
            background="#161B22",
            foreground=PRIMARY_TEXT_COLOR,
            selectbackground="#1F6FEB",
            selectforeground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            height=10,
            activestyle="none",
            exportselection=False,
        )
        self.live_devices_list.pack(fill="both", expand=True)

        actions = tk.Frame(container, background=BACKGROUND_COLOR)
        actions.pack(fill="x", pady=(7, 0))

        tk.Button(
            actions,
            text="SCAN",
            command=self._start_live_scan,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")

        tk.Button(
            actions,
            text="DETAILS",
            command=self._open_selected_live_device,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=(8, 0))
        
        tk.Button(
            actions,
            text="BACK",
            command=self._build_summary,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=8)

        tk.Button(
            actions,
            text="CLOSE",
            command=self._close,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="right")

        self._render_live_scan()

    def _open_selected_live_device(self) -> None:
        devices_list = self.live_devices_list
        
        if devices_list is None:
            return
        
        selected_indices = devices_list.curselection()
        
        if not selected_indices:
            self.live_status_text = "SELECT A DEVICE FIRST"
            self.live_status_color = WARNING_COLOR
            self._render_live_scan()
            return
        
        selected_index = selected_indices[0]
        
        # The Listbox rows and live_devices use RSSI-sorted order
        if selected_index >= len(self.live_devices):
            self.live_status_text = "THE SELECTED SCAN RESULT IS NO LONGER AVAILABLE"
            self.live_status_color = WARNING_COLOR
            self._render_live_scan()
            return
        
        self._build_live_device(self.live_devices[selected_index])
        
    def _build_live_device(self, device: LiveDevice) -> None:
        self._clear_screen()
        
        container = tk.Frame(
            self.root,
            background=BACKGROUND_COLOR,
            padx=12,
            pady=8,
        )
        container.pack(fill="both", expand=True)
        
        tk.Label(
            container,
            text=self._shorten(device.name, 36),
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 13, "bold"),
        ).pack(pady=(0, 3))

        tk.Label(
            container,
            text=device.address,
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans Mono", 10),
        ).pack()

        tk.Label(
            container,
            text=f"SIGNAL {device.rssi} dBm",
            background=BACKGROUND_COLOR,
            foreground=SUCCESS_COLOR,
            font=("DejaVu Sans", 10, "bold"),
        ).pack(pady=(5, 7))

        tk.Label(
            container,
            text="ADVERTISED SERVICE UUIDS",
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans", 9, "bold"),
            anchor="w",
        ).pack(fill="x")

        services_list = tk.Listbox(
            container,
            background="#161B22",
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            height=6,
            activestyle="none",
        )
        services_list.pack(fill="both", expand=True, pady=(3, 7))

        if device.service_uuids:
            for service_uuid in device.service_uuids:
                services_list.insert(tk.END, service_uuid)
        else:
            # Advertisements may omit UUIDs even when the device has GATT
            # services; the later connection step must discover the real table.
            services_list.insert(tk.END, "None included in advertisement")

        actions = tk.Frame(container, background=BACKGROUND_COLOR)
        actions.pack(fill="x")

        tk.Button(
            actions,
            text="CONNECT",
            command=lambda: self._start_live_connection(device),
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")
        
        tk.Button(
            actions,
            text="BACK",
            command=self._build_live_scan,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=8)

        tk.Button(
            actions,
            text="CLOSE",
            command=self._close,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="right")
    
    def _start_live_connection(self, device: LiveDevice) -> None:
        self.selected_live_device = device
        self.gatt_services = ()
        self.connection_status_text = "CONNECTING AND DISCOVERING GATT"
        self.connection_status_color = MUTED_TEXT_COLOR
        self.connection_session_finished = False
        self.connection_failed = False
        self.return_to_scan_after_disconnect = False
        self._build_connection_status()

        try:
            self.live_runtime.start_connection(device.address)
        except (RuntimeError, ValueError) as error:
            self.connection_status_text = f"CONNECTION FAILED: {error}"
            self.connection_status_color = WARNING_COLOR
            self.connection_session_finished = True
            self.connection_failed = True
            self._render_connection_status()
            return

        self._schedule_live_poll()

    def _build_connection_status(self) -> None:
        device = self.selected_live_device

        if device is None:
            raise RuntimeError(
                "Cannot display connection status without a selected device"
            )

        self._clear_screen()

        container = tk.Frame(
            self.root,
            background=BACKGROUND_COLOR,
            padx=14,
            pady=10,
        )
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text="LIVE GATT CONNECTION",
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans", 10, "bold"),
        ).pack(pady=(0, 8))

        tk.Label(
            container,
            text=self._shorten(device.name, 36),
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 14, "bold"),
        ).pack()

        tk.Label(
            container,
            text=device.address,
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans Mono", 9),
        ).pack(pady=(3, 10))

        self.connection_status_label = tk.Label(
            container,
            text=self.connection_status_text,
            background=BACKGROUND_COLOR,
            foreground=self.connection_status_color,
            font=("DejaVu Sans", 11, "bold"),
            wraplength=440,
            justify="center",
        )
        self.connection_status_label.pack(expand=True)

        actions = tk.Frame(container, background=BACKGROUND_COLOR)
        actions.pack(fill="x", pady=(10, 0))

        tk.Button(
            actions,
            text="BACK",
            command=self._leave_live_connection,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")

        tk.Button(
            actions,
            text="CLOSE",
            command=self._close,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="right")

    def _render_connection_status(self) -> None:
        status_label = self.connection_status_label

        if status_label is None:
            return

        status_label.configure(
            text=self.connection_status_text,
            foreground=self.connection_status_color,
        )

    def _build_gatt_services(self) -> None:
        device = self.selected_live_device

        if device is None:
            raise RuntimeError(
                "Cannot browse GATT services without a selected device"
            )

        self._clear_screen()

        container = tk.Frame(
            self.root,
            background=BACKGROUND_COLOR,
            padx=12,
            pady=8,
        )
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text=f"GATT SERVICES — {self._shorten(device.name, 24)}",
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 11, "bold"),
        ).pack(pady=(0, 3))

        self.connection_status_label = tk.Label(
            container,
            text=f"CONNECTED • {len(self.gatt_services)} SERVICES",
            background=BACKGROUND_COLOR,
            foreground=SUCCESS_COLOR,
            font=("DejaVu Sans", 9, "bold"),
        )
        self.connection_status_label.pack(fill="x", pady=(0, 5))

        self.gatt_services_list = tk.Listbox(
            container,
            background="#161B22",
            foreground=PRIMARY_TEXT_COLOR,
            selectbackground="#1F6FEB",
            selectforeground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            height=10,
            activestyle="none",
            exportselection=False,
        )
        self.gatt_services_list.pack(fill="both", expand=True)

        for service in self.gatt_services:
            # Handles identify this connection's attribute entries; UUIDs remain
            # the stable identities used by profiles and later operations.
            self.gatt_services_list.insert(
                tk.END,
                f"{service.handle:>4}  "
                f"{self._shorten(service.description, 34)}",
            )

        actions = tk.Frame(container, background=BACKGROUND_COLOR)
        actions.pack(fill="x", pady=(7, 0))

        tk.Button(
            actions,
            text="DETAILS",
            command=self._open_selected_gatt_service,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")

        tk.Button(
            actions,
            text="DISCONNECT",
            command=self._leave_live_connection,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=8)

        tk.Button(
            actions,
            text="CLOSE",
            command=self._close,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="right")

    def _open_selected_gatt_service(self) -> None:
        services_list = self.gatt_services_list

        if services_list is None:
            return

        selected_indices = services_list.curselection()

        if not selected_indices:
            self.connection_status_text = "SELECT A SERVICE FIRST"
            self.connection_status_color = WARNING_COLOR
            self._render_connection_status()
            return

        selected_index = selected_indices[0]

        if selected_index >= len(self.gatt_services):
            self.connection_status_text = (
                "THE SELECTED SERVICE IS NO LONGER AVAILABLE"
            )
            self.connection_status_color = WARNING_COLOR
            self._render_connection_status()
            return

        self._build_gatt_service(self.gatt_services[selected_index])

    def _build_gatt_service(self, service: GattServiceSnapshot) -> None:
        self._clear_screen()

        container = tk.Frame(
            self.root,
            background=BACKGROUND_COLOR,
            padx=12,
            pady=8,
        )
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text=self._shorten(service.description, 38),
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 11, "bold"),
        ).pack(pady=(0, 2))

        tk.Label(
            container,
            text=service.uuid,
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
        ).pack()

        tk.Label(
            container,
            text=(
                f"SERVICE HANDLE {service.handle} • "
                f"{len(service.characteristics)} CHARACTERISTICS"
            ),
            background=BACKGROUND_COLOR,
            foreground=SUCCESS_COLOR,
            font=("DejaVu Sans", 9, "bold"),
        ).pack(pady=(4, 5))

        characteristics_list = tk.Listbox(
            container,
            background="#161B22",
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            height=9,
            activestyle="none",
        )
        characteristics_list.pack(fill="both", expand=True)

        for characteristic in service.characteristics:
            properties = ",".join(characteristic.properties) or "none"

            # ATT reads, writes, and notifications target value_handle, so that
            # operational handle is shown beside each characteristic.
            characteristics_list.insert(
                tk.END,
                f"{characteristic.value_handle:>4}  "
                f"{self._shorten(characteristic.description, 20):<20} "
                f"{properties}",
            )

        actions = tk.Frame(container, background=BACKGROUND_COLOR)
        actions.pack(fill="x", pady=(7, 0))

        tk.Button(
            actions,
            text="BACK",
            command=self._build_gatt_services,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")

        tk.Button(
            actions,
            text="DISCONNECT",
            command=self._leave_live_connection,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=8)

        tk.Button(
            actions,
            text="CLOSE",
            command=self._close,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="right")
    
    def _leave_live_connection(self) -> None:
        if self.connection_session_finished:
            self.return_to_scan_after_disconnect = False
            self._build_live_scan()
            return

        self.return_to_scan_after_disconnect = True
        self.connection_status_text = "DISCONNECTING"
        self.connection_status_color = MUTED_TEXT_COLOR
        self._render_connection_status()
        self.live_runtime.request_disconnect()
    
    def _start_live_scan(self) -> None:
        if not self.live_runtime_started:
            try:
                self.live_runtime.start()
            except Exception as error:
                self.live_status_text = (
                    f"RUNTIME FAILED: {type(error).__name__}: {error}"
                )
                self.live_status_color = WARNING_COLOR
                self._render_live_scan()
                return

            # LiveRuntime owns one worker thread for every scan made by this UI.
            self.live_runtime_started = True

        self.live_devices = ()
        self.live_status_text = (
            f"STARTING {self.scan_duration_seconds:g}-SECOND SCAN"
        )
        self.live_status_color = MUTED_TEXT_COLOR
        self._render_live_scan()

        try:
            self.live_runtime.start_scan(self.scan_duration_seconds)
        except (RuntimeError, ValueError) as error:
            self.live_status_text = f"SCAN FAILED: {error}"
            self.live_status_color = WARNING_COLOR
            self._render_live_scan()
            return

        self._schedule_live_poll()

    def _schedule_live_poll(self) -> None:
        if self.poll_job is None:
            # Tk polls the thread-safe queue because only Tk's main thread may
            # update labels and device rows on the touchscreen.
            self.poll_job = self.root.after(
                100,
                self._poll_live_updates,
            )

    def _poll_live_updates(self) -> None:
        # This scheduled callback is now executing, so another callback may be
        # registered without creating two simultaneous polling loops.
        self.poll_job = None
        updates = self.live_runtime.drain_updates()
        scan_state_changed = False

        for update in updates:
            if isinstance(update, ScanStarted):
                self.live_status_text = (
                    f"SCANNING FOR {update.duration_seconds:g} SECONDS"
                )
                self.live_status_color = MUTED_TEXT_COLOR
                scan_state_changed = True

            elif isinstance(update, ScanCompleted):
                self.live_devices = update.devices
                self.live_status_text = (
                    f"FOUND {len(update.devices)} BLE DEVICE(S)"
                )
                self.live_status_color = SUCCESS_COLOR
                scan_state_changed = True

            elif isinstance(update, ConnectionStarted):
                self.connection_status_text = "CONNECTING AND DISCOVERING GATT"
                self.connection_status_color = MUTED_TEXT_COLOR
                self._render_connection_status()

            elif isinstance(update, GattDiscovered):
                self.gatt_services = update.services
                self.connection_status_text = (
                    f"CONNECTED: DISCOVERED {len(update.services)} SERVICE(S)"
                )
                self.connection_status_color = SUCCESS_COLOR
                self.connection_failed = False
                self._build_gatt_services()

            elif isinstance(update, RuntimeFailed):
                if update.operation == "scan":
                    self.live_status_text = (
                        f"{update.error_type}: {update.message}"
                    )
                    self.live_status_color = WARNING_COLOR
                    scan_state_changed = True
                else:
                    self.connection_status_text = (
                        f"{update.operation.upper()} FAILED: "
                        f"{update.error_type}: {update.message}"
                    )
                    self.connection_status_color = WARNING_COLOR
                    self.connection_failed = True
                    self._render_connection_status()

            elif isinstance(update, ConnectionClosed):
                self.connection_session_finished = True

                if (
                    self.return_to_scan_after_disconnect
                    and not self.connection_failed
                ):
                    self.return_to_scan_after_disconnect = False
                    self._build_live_scan()
                else:
                    if not self.connection_failed:
                        self.connection_status_text = "DISCONNECTED"
                        self.connection_status_color = MUTED_TEXT_COLOR

                    self._render_connection_status()

        # Redrawing scan rows removes their selected state, so only scan
        # updates are allowed to rebuild that Listbox.
        if scan_state_changed:
            self._render_live_scan()

        self._schedule_live_poll()

    def _render_live_scan(self) -> None:
        status_label = self.live_status_label
        devices_list = self.live_devices_list

        # A scan may finish while another screen is open; its results remain in
        # live_devices and will render when the user returns to LIVE SCAN.
        if status_label is None or devices_list is None:
            return

        status_label.configure(
            text=self.live_status_text,
            foreground=self.live_status_color,
        )

        devices_list.delete(0, tk.END)

        if not self.live_devices:
            devices_list.insert(tk.END, "No scan results to display")
            return

        for device in self.live_devices:
            devices_list.insert(
                tk.END,
                f"{device.rssi:>4} dBm  "
                f"{device.name[:20]:<20}  "
                f"{device.address}",
        )
        
    def _build_summary(self) -> None:
        self._clear_screen()
        passive_capture_complete = self.summary.unmatched_count == 0
        
        status_text = (
            "PASSIVE EVIDENCE COMPLETE"
            if passive_capture_complete
            else (
                f"{self.summary.unmatched_count} EVENT(S) WITHOUT"
                " PASSIVE MATCH"
            )
        )
        status_color = (
            SUCCESS_COLOR
            if passive_capture_complete
            else WARNING_COLOR
        )
        
        container = tk.Frame(
            self.root,
            background=BACKGROUND_COLOR,
            padx=16,
            pady=10,
        )
        container.pack(fill="both", expand=True)
        
        tk.Label(
            container,
            text="CAPTURE CORRELATION",
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans", 11, "bold"),
        ).pack(pady=(0, 8))
        
        tk.Label(
            container,
            text=(
                f"{self.summary.matched_count} / {self.summary.event_count}"
            ),
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 28, "bold"),
        ).pack()
        
        tk.Label(
            container,
            text="APPLICATION EVENTS MATCHED",
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans", 10),
        ).pack(pady=(0, 12))
        
        # This status describes passive packet evidence only
        tk.Label(
            container,
            text=status_text,
            background=BACKGROUND_COLOR,
            foreground=status_color,
            font=("DejaVu Sans", 11, "bold"),
            wraplength=420,
            justify="center",
        ).pack(expand=True)
        
        actions = tk.Frame(
            container,
            background=BACKGROUND_COLOR,
        )
        actions.pack(pady=(12,0))
        
        tk.Button(
            actions,
            text="LIVE SCAN",
            command=self._build_live_scan,
            font=("DejaVu Sans", 10, "bold"),
            padx=14,
            pady=4,
        ).pack(side="left", padx=6)
        
        if self.report.events:
            tk.Button(
                actions,
                text="EVENTS",
                command=lambda: self._build_event(0),
                font=("DejaVu Sans", 11, "bold"),
                padx=14,
                pady=4,
            ).pack(side="left", padx=6)
            
        tk.Button(
            actions,
            text="CLOSE",
            command=self._close,
            font=("DejaVu Sans", 10, "bold"),
            padx=14,
            pady=4,
        ).pack(side="left", padx=6)
            
    def _build_event(self, index: int) -> None:
        self._clear_screen()
        event = self.report.events[index]
        
        status_text = "MATCHED" if event.matched else "UNMATCHED"
        status_color = SUCCESS_COLOR if event.matched else WARNING_COLOR
        
        payload_text = (
            repr(event.payload_text)
            if event.payload_text is not None
            else "Not valid UTF-8"
        )
        evidence_text = (
            f"Frame {event.frame_number} | {event.rssi} dBm"
            if event.matched
            else "No passive packet match"
        )
        
        container = tk.Frame(
            self.root,
            background=BACKGROUND_COLOR,
            padx=12,
            pady=8,
        )
        container.pack(fill="both", expand=True)
        
        header = tk.Frame(container, background=BACKGROUND_COLOR)
        header.pack(fill="x")
        
        tk.Label(
            header,
            text=f"EVENT {index + 1} / {len(self.report.events)}",
            background= BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans", 9, "bold"),
        ).pack(side="left")
        
        tk.Label(
            header,
            text=status_text,
            background=BACKGROUND_COLOR,
            foreground=status_color,
            font=("DejaVu Sans", 9, "bold"),
        ).pack(side="right")
        
        tk.Label(
            container,
            text=event.event_type,
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 12, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(8, 3))
        
        tk.Label(
            container,
            text=event.characteristic_uuid,
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            anchor="w",
        ).pack(fill="x")
        
        tk.Label(
            container,
            text=f"HEX {self._shorten(event.payload_hex, 96)}",
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            wraplength=450,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(9, 3))
        
        tk.Label(
            container,
            text=f"UTF-8 {self._shorten(payload_text, 72)}",
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 9),
            anchor="w",
        ).pack(fill="x")
        
        tk.Label(
            container,
            text=evidence_text,
            background=BACKGROUND_COLOR,
            foreground=status_color,
            font=("DejaVu Sans", 9, "bold"),
        ).pack(pady=(10, 5))
        
        navigation = tk.Frame(container, background=BACKGROUND_COLOR)
        navigation.pack(side="bottom", fill="x")
        
        tk.Button(
            navigation,
            text="BACK",
            command=self._build_summary,
            font=("DejaVu Sans", 9, "bold"),
            padx=10,
            pady=3,
        ).pack(side="left")
        
        tk.Button(
            navigation,
            text="PREV",
            command=lambda: self._build_event(index - 1),
            state="normal" if index > 0 else "disabled",
            font=("DejaVu Sans", 9, "bold"),
            padx=10,
            pady=3,
        ).pack(side="left", padx=8)
        
        tk.Button(
            navigation,
            text="NEXT",
            command=lambda: self._build_event(index + 1),
            state=(
                "normal"
                if index < len(self.report.events) - 1
                else "disabled"
            ),
            font=("DejaVu Sans", 9, "bold"),
            padx=10,
            pady=3,
        ).pack(side="right")
        
def run() -> None:
    arguments = parse_arguments()
    
    # Validate complete summary before rendering
    report = load_correlation_report(arguments.report)
    
    root = tk.Tk()
    CorrelationDashboard(root, report, arguments.scan_duration)
    root.mainloop()
    
if __name__ == "__main__":
    run()

