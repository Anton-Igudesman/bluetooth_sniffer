import argparse
import tkinter as tk
from pathlib import Path

from .model import (
    CorrelationReport,
    decode_utf8,
    load_correlation_report,
)
    
from ..scanner import DEFAULT_SCAN_DURATION_SECONDS
from ..gatt_client import (
    GattCharacteristicSnapshot,
    GattServiceSnapshot,
)

from .live_runtime import (
    CharacteristicRead,
    CharacteristicWritten,
    CharacteristicValueReceived,
    NotificationSubscriptionStarted,
    NotificationSubscriptionStopped,
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
        self.selected_gatt_service: GattServiceSnapshot | None = None
        self.gatt_characteristics_list: tk.Listbox | None = None
        self.selected_gatt_characteristic: (
            GattCharacteristicSnapshot | None
        ) = None
        
        # Preserve the latest read result through async BLE ops
        self.gatt_read_status_text = "NO VALUE READ"
        self.gatt_read_status_color = MUTED_TEXT_COLOR
        self.gatt_read_status_label: tk.Label | None = None
        
        # Store entered nibbles separately from their spaced display so SEND
        # always converts an exact sequence of hexadecimal bytes.
        self.gatt_write_hex = ""
        self.gatt_write_with_response = True
        self.gatt_write_status_text = "ENTER HEX BYTES"
        self.gatt_write_status_color = MUTED_TEXT_COLOR
        self.gatt_write_value_label: tk.Label | None = None
        self.gatt_write_mode_label: tk.Label | None = None
        self.gatt_write_status_label: tk.Label | None = None
        
        # Keep one active subscription and a bounded value history while the
        # user moves between the monitor and the surrounding GATT browser.
        self.gatt_monitor_target: tuple[str, str] | None = None
        self.gatt_monitor_events: list[CharacteristicValueReceived] = []
        self.gatt_monitor_status_text = "NOT SUBSCRIBED"
        self.gatt_monitor_status_color = MUTED_TEXT_COLOR
        self.gatt_monitor_status_label: tk.Label | None = None
        self.gatt_monitor_values_text: tk.Text | None = None
        
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
        self.gatt_characteristics_list = None
        self.gatt_read_status_label = None
        self.gatt_write_value_label = None
        self.gatt_write_mode_label = None
        self.gatt_write_status_label = None
        self.gatt_monitor_status_label = None
        self.gatt_monitor_values_text = None
        
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
        
        self.selected_gatt_characteristic = None
        self.selected_gatt_service = service

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

        self.gatt_characteristics_list = tk.Listbox(
            container,
            background="#161B22",
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            height=9,
            activestyle="none",
            selectbackground="#1F6FEB",
            selectforeground=PRIMARY_TEXT_COLOR,
            exportselection=False,
        )
        self.gatt_characteristics_list.pack(fill="both", expand=True)

        for characteristic in service.characteristics:
            properties = ",".join(characteristic.properties) or "none"

            # ATT reads, writes, and notifications target value_handle, so that
            # operational handle is shown beside each characteristic.
            self.gatt_characteristics_list.insert(
                tk.END,
                f"{characteristic.value_handle:>4}  "
                f"{self._shorten(characteristic.description, 20):<20} "
                f"{properties}",
            )

        actions = tk.Frame(container, background=BACKGROUND_COLOR)
        actions.pack(fill="x", pady=(7, 0))
        
        tk.Button(
            actions,
            text="DETAILS",
            command=self._open_selected_gatt_characteristic,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")
        
        tk.Button(
            actions,
            text="BACK",
            command=self._build_gatt_services,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=8)

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
    
    def _open_selected_gatt_characteristic(self) -> None:
        characteristics_list = self.gatt_characteristics_list
        service = self.selected_gatt_service

        if characteristics_list is None or service is None:
            return

        selected_indices = characteristics_list.curselection()

        if not selected_indices:
            return

        selected_index = selected_indices[0]

        if selected_index >= len(service.characteristics):
            return

        self._build_gatt_characteristic(
            service,
            service.characteristics[selected_index],
        )

    def _build_gatt_characteristic(
        self,
        service: GattServiceSnapshot,
        characteristic: GattCharacteristicSnapshot,
    ) -> None:
        self._clear_screen()
        
        self.selected_gatt_service = service
        self.selected_gatt_characteristic = characteristic

        if "read" in characteristic.properties:
            self.gatt_read_status_text = "READY TO READ"
            self.gatt_read_status_color = MUTED_TEXT_COLOR
        else:
            self.gatt_read_status_text = "READ NOT SUPPORTED"
            self.gatt_read_status_color = MUTED_TEXT_COLOR

        container = tk.Frame(
            self.root,
            background=BACKGROUND_COLOR,
            padx=12,
            pady=8,
        )
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text=self._shorten(characteristic.description, 38),
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 11, "bold"),
        ).pack(pady=(0, 2))

        tk.Label(
            container,
            text=characteristic.uuid,
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            wraplength=450,
        ).pack()

        tk.Label(
            container,
            text=f"SERVICE: {self._shorten(service.description, 34)}",
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans", 8),
        ).pack(pady=(3, 2))

        # The declaration describes the characteristic, while ATT data
        # operations use its value handle; showing both prevents capture
        # frames from being compared with the wrong attribute.
        tk.Label(
            container,
            text=(
                f"DECLARATION {characteristic.declaration_handle}  •  "
                f"VALUE {characteristic.value_handle}"
            ),
            background=BACKGROUND_COLOR,
            foreground=SUCCESS_COLOR,
            font=("DejaVu Sans", 9, "bold"),
        ).pack(pady=(2, 3))

        properties = ", ".join(characteristic.properties) or "none"

        tk.Label(
            container,
            text=f"PROPERTIES: {properties}",
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 8),
            wraplength=450,
            justify="left",
        ).pack(fill="x", pady=(0, 4))

        self.gatt_read_status_label = tk.Label(
            container,
            text=self.gatt_read_status_text,
            background=BACKGROUND_COLOR,
            foreground=self.gatt_read_status_color,
            font=("DejaVu Sans Mono", 8),
            wraplength=450,
            justify="left",
            anchor="w",
        )
        self.gatt_read_status_label.pack(fill="x", pady=(0, 4))
        
        tk.Label(
            container,
            text=f"DESCRIPTORS ({len(characteristic.descriptors)})",
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans", 8, "bold"),
            anchor="w",
        ).pack(fill="x")

        descriptors_text = tk.Text(
            container,
            background="#161B22",
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            height=6,
            wrap="char",
            relief="flat",
        )
        descriptors_text.pack(fill="both", expand=True, pady=(3, 6))

        if characteristic.descriptors:
            for descriptor in characteristic.descriptors:
                descriptors_text.insert(
                    tk.END,
                    f"{descriptor.description}\n"
                    f"UUID {descriptor.uuid}\n"
                    f"HANDLE {descriptor.handle}\n\n",
                )
        else:
            descriptors_text.insert(
                tk.END,
                "No descriptors discovered for this characteristic",
            )

        # Attribute metadata is inspectable here; editable values and live
        # operations are added separately according to characteristic properties.
        descriptors_text.configure(state="disabled")

        # Keep attribute operations separate from navigation so the monitor
        # control remains touchable within the Waveshare screen's 480-pixel width.
        operations = tk.Frame(container, background=BACKGROUND_COLOR)
        operations.pack(fill="x", pady=(0, 3))

        tk.Button(
            operations,
            text="READ",
            command=self._start_gatt_read,
            state=(
                "normal"
                if "read" in characteristic.properties
                else "disabled"
            ),
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")

        tk.Button(
            operations,
            text="WRITE",
            command=self._build_gatt_write,
            state=(
                "normal"
                if any(
                    property_name in characteristic.properties
                    for property_name in (
                        "write",
                        "write-without-response",
                    )
                )
                else "disabled"
            ),
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            operations,
            text="MONITOR",
            command=self._build_gatt_monitor,
            state=(
                "normal"
                if any(
                    property_name in characteristic.properties
                    for property_name in ("notify", "indicate")
                )
                else "disabled"
            ),
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=(8, 0))

        navigation = tk.Frame(container, background=BACKGROUND_COLOR)
        navigation.pack(fill="x")

        tk.Button(
            navigation,
            text="BACK",
            command=lambda: self._build_gatt_service(service),
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")

        tk.Button(
            navigation,
            text="DISCONNECT",
            command=self._leave_live_connection,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=8)

        tk.Button(
            navigation,
            text="CLOSE",
            command=self._close,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="right")
    
    def _start_gatt_read(self) -> None:
        service = self.selected_gatt_service
        characteristic = self.selected_gatt_characteristic

        if service is None or characteristic is None:
            return

        self.gatt_read_status_text = "READING..."
        self.gatt_read_status_color = MUTED_TEXT_COLOR
        self._render_gatt_read_status()

        try:
            self.live_runtime.start_characteristic_read(
                service.uuid,
                characteristic.uuid,
            )
        except (RuntimeError, ValueError) as error:
            self.gatt_read_status_text = f"READ FAILED: {error}"
            self.gatt_read_status_color = WARNING_COLOR
            self._render_gatt_read_status()

    def _render_gatt_read_status(self) -> None:
        status_label = self.gatt_read_status_label

        # A read may finish after the user navigates away; retain its result
        # without trying to update a characteristic widget that no longer exists.
        if status_label is None:
            return

        status_label.configure(
            text=self.gatt_read_status_text,
            foreground=self.gatt_read_status_color,
        )
    
    def _build_gatt_write(self) -> None:
        service = self.selected_gatt_service
        characteristic = self.selected_gatt_characteristic

        if service is None or characteristic is None:
            return

        supports_with_response = "write" in characteristic.properties
        supports_without_response = (
            "write-without-response" in characteristic.properties
        )

        if not supports_with_response and not supports_without_response:
            return

        # Start each visit with a deliberate empty payload so an earlier
        # characteristic's command cannot be sent to this selected handle.
        self.gatt_write_hex = ""
        self.gatt_write_with_response = supports_with_response
        self.gatt_write_status_text = "ENTER HEX BYTES"
        self.gatt_write_status_color = MUTED_TEXT_COLOR
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
            text=f"WRITE — {self._shorten(characteristic.description, 28)}",
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 11, "bold"),
        ).pack(pady=(0, 2))

        tk.Label(
            container,
            text=characteristic.uuid,
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            wraplength=450,
        ).pack()

        self.gatt_write_value_label = tk.Label(
            container,
            text="PAYLOAD <empty>",
            background="#161B22",
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 10, "bold"),
            wraplength=440,
            anchor="w",
            justify="left",
            padx=6,
            pady=5,
        )
        self.gatt_write_value_label.pack(fill="x", pady=(5, 3))

        self.gatt_write_mode_label = tk.Label(
            container,
            background=BACKGROUND_COLOR,
            foreground=SUCCESS_COLOR,
            font=("DejaVu Sans", 8, "bold"),
        )
        self.gatt_write_mode_label.pack(fill="x")

        self.gatt_write_status_label = tk.Label(
            container,
            text=self.gatt_write_status_text,
            background=BACKGROUND_COLOR,
            foreground=self.gatt_write_status_color,
            font=("DejaVu Sans", 8, "bold"),
        )
        self.gatt_write_status_label.pack(fill="x", pady=(1, 3))

        keypad = tk.Frame(container, background=BACKGROUND_COLOR)
        keypad.pack(fill="x")

        for index, digit in enumerate("0123456789ABCDEF"):
            # Capture this loop's digit now so each touch button appends its
            # own value rather than every button appending the final "F".
            tk.Button(
                keypad,
                text=digit,
                command=lambda digit=digit: self._append_gatt_write_hex(
                    digit
                ),
                font=("DejaVu Sans Mono", 9, "bold"),
                width=3,
                pady=2,
            ).grid(
                row=index // 8,
                column=index % 8,
                padx=2,
                pady=2,
            )

        edit_actions = tk.Frame(container, background=BACKGROUND_COLOR)
        edit_actions.pack(fill="x", pady=(3, 0))

        tk.Button(
            edit_actions,
            text="BACKSPACE",
            command=self._backspace_gatt_write_hex,
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=2,
        ).pack(side="left")

        tk.Button(
            edit_actions,
            text="CLEAR",
            command=self._clear_gatt_write_hex,
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=2,
        ).pack(side="left", padx=8)

        tk.Button(
            edit_actions,
            text="MODE",
            command=self._toggle_gatt_write_mode,
            state=(
                "normal"
                if supports_with_response and supports_without_response
                else "disabled"
            ),
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=2,
        ).pack(side="left")
        
        navigation = tk.Frame(container, background=BACKGROUND_COLOR)
        navigation.pack(side="bottom", fill="x")

        tk.Button(
            navigation,
            text="SEND",
            command=self._start_gatt_write,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left")
        
        tk.Button(
            navigation,
            text="BACK",
            command=lambda: self._build_gatt_characteristic(
                service,
                characteristic,
            ),
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            navigation,
            text="DISCONNECT",
            command=self._leave_live_connection,
            font=("DejaVu Sans", 9, "bold"),
            padx=12,
            pady=3,
        ).pack(side="left", padx=8)

        self._render_gatt_write()

    def _append_gatt_write_hex(self, digit: str) -> None:
        # GATT writes with response are limited to 512 bytes, so the editor
        # prevents input beyond 1,024 hexadecimal digits.
        if len(self.gatt_write_hex) >= 1024:
            self.gatt_write_status_text = "PAYLOAD LIMIT: 512 BYTES"
            self.gatt_write_status_color = WARNING_COLOR
            self._render_gatt_write()
            return

        self.gatt_write_hex += digit
        self.gatt_write_status_text = "ENTER HEX BYTES"
        self.gatt_write_status_color = MUTED_TEXT_COLOR
        self._render_gatt_write()

    def _backspace_gatt_write_hex(self) -> None:
        self.gatt_write_hex = self.gatt_write_hex[:-1]
        self._render_gatt_write()

    def _clear_gatt_write_hex(self) -> None:
        self.gatt_write_hex = ""
        self.gatt_write_status_text = "ENTER HEX BYTES"
        self.gatt_write_status_color = MUTED_TEXT_COLOR
        self._render_gatt_write()
        
    def _toggle_gatt_write_mode(self) -> None:
        characteristic = self.selected_gatt_characteristic

        if characteristic is None:
            return

        supports_with_response = "write" in characteristic.properties
        supports_without_response = (
            "write-without-response" in characteristic.properties
        )

        # Mode changes are allowed only when the peripheral advertised both
        # forms; selecting an unsupported mode would make BlueZ reject SEND.
        if supports_with_response and supports_without_response:
            self.gatt_write_with_response = (
                not self.gatt_write_with_response
            )

        self._render_gatt_write()

    def _start_gatt_write(self) -> None:
        service = self.selected_gatt_service
        characteristic = self.selected_gatt_characteristic

        if service is None or characteristic is None:
            return

        if not self.gatt_write_hex:
            self.gatt_write_status_text = "ENTER A PAYLOAD BEFORE SENDING"
            self.gatt_write_status_color = WARNING_COLOR
            self._render_gatt_write()
            return

        # Every byte requires two hexadecimal digits. An unfinished final
        # digit cannot be converted into the exact byte payload sent over GATT.
        if len(self.gatt_write_hex) % 2 != 0:
            self.gatt_write_status_text = "INCOMPLETE BYTE: ADD ONE HEX DIGIT"
            self.gatt_write_status_color = WARNING_COLOR
            self._render_gatt_write()
            return

        payload = bytes.fromhex(self.gatt_write_hex)
        self.gatt_write_status_text = "WRITING..."
        self.gatt_write_status_color = MUTED_TEXT_COLOR
        self._render_gatt_write()

        try:
            self.live_runtime.start_characteristic_write(
                service.uuid,
                characteristic.uuid,
                payload,
                with_response=self.gatt_write_with_response,
            )
        except (RuntimeError, ValueError) as error:
            self.gatt_write_status_text = f"WRITE FAILED: {error}"
            self.gatt_write_status_color = WARNING_COLOR
            self._render_gatt_write()

    def _render_gatt_write(self) -> None:
        value_label = self.gatt_write_value_label
        mode_label = self.gatt_write_mode_label
        status_label = self.gatt_write_status_label

        if (
            value_label is None
            or mode_label is None
            or status_label is None
        ):
            return

        grouped_hex = " ".join(
            self.gatt_write_hex[index:index + 2]
            for index in range(0, len(self.gatt_write_hex), 2)
        )

        value_label.configure(
            text=f"PAYLOAD {self._shorten(grouped_hex, 96)}"
            if grouped_hex
            else "PAYLOAD <empty>"
        )
        mode_label.configure(
            text=(
                "MODE: WITH RESPONSE"
                if self.gatt_write_with_response
                else "MODE: WITHOUT RESPONSE"
            )
        )
        status_label.configure(
            text=self.gatt_write_status_text,
            foreground=self.gatt_write_status_color,
        )
    
    def _build_gatt_monitor(self) -> None:
        service = self.selected_gatt_service
        characteristic = self.selected_gatt_characteristic

        if service is None or characteristic is None:
            return

        if not any(
            property_name in characteristic.properties
            for property_name in ("notify", "indicate")
        ):
            return

        selected_target = (service.uuid, characteristic.uuid)
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
            text=(
                f"LIVE VALUES — "
                f"{self._shorten(characteristic.description, 26)}"
            ),
            background=BACKGROUND_COLOR,
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans", 11, "bold"),
        ).pack(pady=(0, 2))

        tk.Label(
            container,
            text=characteristic.uuid,
            background=BACKGROUND_COLOR,
            foreground=MUTED_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            wraplength=450,
        ).pack()

        self.gatt_monitor_status_label = tk.Label(
            container,
            text=self.gatt_monitor_status_text,
            background=BACKGROUND_COLOR,
            foreground=self.gatt_monitor_status_color,
            font=("DejaVu Sans", 8, "bold"),
        )
        self.gatt_monitor_status_label.pack(fill="x", pady=(4, 3))

        self.gatt_monitor_values_text = tk.Text(
            container,
            background="#161B22",
            foreground=PRIMARY_TEXT_COLOR,
            font=("DejaVu Sans Mono", 8),
            wrap="char",
            relief="flat",
            padx=6,
            pady=4,
        )
        self.gatt_monitor_values_text.pack(
            fill="both",
            expand=True,
            pady=(0, 5),
        )

        actions = tk.Frame(container, background=BACKGROUND_COLOR)
        actions.pack(fill="x")

        tk.Button(
            actions,
            text="START",
            command=self._start_gatt_monitor,
            state=(
                "normal"
                if self.gatt_monitor_target is None
                else "disabled"
            ),
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side="left")

        tk.Button(
            actions,
            text="STOP",
            command=self._stop_gatt_monitor,
            state=(
                "normal"
                if self.gatt_monitor_target == selected_target
                else "disabled"
            ),
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side="left", padx=(6, 0))

        tk.Button(
            actions,
            text="CLEAR",
            command=self._clear_gatt_monitor,
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side="left", padx=6)

        tk.Button(
            actions,
            text="BACK",
            command=lambda: self._build_gatt_characteristic(
                service,
                characteristic,
            ),
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side="left")

        tk.Button(
            actions,
            text="DISCONNECT",
            command=self._leave_live_connection,
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side="right")

        self._render_gatt_monitor()

    def _start_gatt_monitor(self) -> None:
        service = self.selected_gatt_service
        characteristic = self.selected_gatt_characteristic

        if service is None or characteristic is None:
            return

        # A new subscription begins a distinct value stream; old values should
        # not appear to have come from the newly selected characteristic.
        self.gatt_monitor_events = []
        self.gatt_monitor_status_text = "SUBSCRIBING..."
        self.gatt_monitor_status_color = MUTED_TEXT_COLOR
        self._render_gatt_monitor()

        try:
            self.live_runtime.start_characteristic_subscription(
                service.uuid,
                characteristic.uuid,
            )
        except (RuntimeError, ValueError) as error:
            self.gatt_monitor_status_text = f"START FAILED: {error}"
            self.gatt_monitor_status_color = WARNING_COLOR
            self._render_gatt_monitor()

    def _stop_gatt_monitor(self) -> None:
        self.gatt_monitor_status_text = "STOPPING..."
        self.gatt_monitor_status_color = MUTED_TEXT_COLOR
        self._render_gatt_monitor()

        try:
            self.live_runtime.stop_characteristic_subscription()
        except (RuntimeError, ValueError) as error:
            self.gatt_monitor_status_text = f"STOP FAILED: {error}"
            self.gatt_monitor_status_color = WARNING_COLOR
            self._render_gatt_monitor()

    def _clear_gatt_monitor(self) -> None:
        # CLEAR affects only the touchscreen history; it does not interrupt the
        # active BlueZ subscription or stop new values from arriving.
        self.gatt_monitor_events = []
        self._render_gatt_monitor()

    def _render_gatt_monitor(self) -> None:
        status_label = self.gatt_monitor_status_label
        values_text = self.gatt_monitor_values_text

        if status_label is None or values_text is None:
            return

        status_label.configure(
            text=self.gatt_monitor_status_text,
            foreground=self.gatt_monitor_status_color,
        )

        values_text.configure(state="normal")
        values_text.delete("1.0", tk.END)

        if self.gatt_monitor_events:
            for event in self.gatt_monitor_events:
                timestamp = (
                    event.timestamp.astimezone()
                    .strftime("%H:%M:%S.%f")[:-3]
                )
                payload_hex = event.value.hex(" ") or "<empty>"
                decoded_text = decode_utf8(event.value)
                payload_text = (
                    repr(decoded_text)
                    if decoded_text is not None
                    else "not valid UTF-8"
                )

                values_text.insert(
                    tk.END,
                    f"{timestamp}  {len(event.value)} BYTE(S)\n"
                    f"HEX {self._shorten(payload_hex, 84)}\n"
                    f"UTF-8 {self._shorten(payload_text, 64)}\n\n",
                )
        else:
            values_text.insert(
                tk.END,
                "No values received yet.\n"
                "START subscribes; the peripheral must then send a value.",
            )

        values_text.configure(state="disabled")
        values_text.see(tk.END)
    
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
        monitor_values_changed = False
        monitor_controls_changed = False

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

            elif isinstance(update, CharacteristicRead):
                service = self.selected_gatt_service
                characteristic = self.selected_gatt_characteristic

                if (
                    service is not None
                    and characteristic is not None
                    and service.uuid == update.service_uuid
                    and characteristic.uuid == update.characteristic_uuid
                ):
                    payload_hex = update.value.hex(" ") or "<empty>"
                    decoded_text = decode_utf8(update.value)
                    payload_text = (
                        repr(decoded_text)
                        if decoded_text is not None
                        else "not valid UTF-8"
                    )

                    # Limit both representations so an unusually large value
                    # cannot push the touchscreen controls off the 320-pixel display.
                    self.gatt_read_status_text = (
                        f"HEX {self._shorten(payload_hex, 80)}\n"
                        f"UTF-8 {self._shorten(payload_text, 48)}"
                    )
                    self.gatt_read_status_color = SUCCESS_COLOR
                    self._render_gatt_read_status()
            
            elif isinstance(update, CharacteristicWritten):
                service = self.selected_gatt_service
                characteristic = self.selected_gatt_characteristic

                # A write may finish after navigation. Only show its result when
                # the open screen still represents the characteristic that received it.
                if (
                    service is not None
                    and characteristic is not None
                    and service.uuid == update.service_uuid
                    and characteristic.uuid == update.characteristic_uuid
                ):
                    write_mode = (
                        "WITH RESPONSE"
                        if update.with_response
                        else "WITHOUT RESPONSE"
                    )
                    self.gatt_write_status_text = (
                        f"SENT {len(update.value)} BYTE(S) — {write_mode}"
                    )
                    self.gatt_write_status_color = SUCCESS_COLOR
                    self._render_gatt_write()
            
            elif isinstance(
                update,
                NotificationSubscriptionStarted,
            ):
                self.gatt_monitor_target = (
                    update.service_uuid,
                    update.characteristic_uuid,
                )
                self.gatt_monitor_status_text = (
                    f"MONITORING — "
                    f"{len(self.gatt_monitor_events)} VALUE(S)"
                )
                self.gatt_monitor_status_color = SUCCESS_COLOR
                monitor_controls_changed = True

            elif isinstance(update, CharacteristicValueReceived):
                self.gatt_monitor_events.append(update)

                # Retain only the newest 50 values so a high-rate peripheral
                # cannot grow memory and touchscreen redraw work indefinitely.
                del self.gatt_monitor_events[:-50]

                self.gatt_monitor_status_text = (
                    f"MONITORING — "
                    f"{len(self.gatt_monitor_events)} VALUE(S) RETAINED"
                )
                self.gatt_monitor_status_color = SUCCESS_COLOR
                monitor_values_changed = True

            elif isinstance(
                update,
                NotificationSubscriptionStopped,
            ):
                self.gatt_monitor_target = None
                self.gatt_monitor_status_text = (
                    f"STOPPED — "
                    f"{len(self.gatt_monitor_events)} VALUE(S) RETAINED"
                )
                self.gatt_monitor_status_color = MUTED_TEXT_COLOR
                monitor_controls_changed = True
            
            elif isinstance(update, RuntimeFailed):
                if update.operation == "scan":
                    self.live_status_text = (
                        f"{update.error_type}: {update.message}"
                    )
                    self.live_status_color = WARNING_COLOR
                    scan_state_changed = True
                elif update.operation == "read":
                    # A rejected attribute read does not necessarily mean the
                    # BLE connection failed, so keep the GATT browser available.
                    self.gatt_read_status_text = (
                        f"READ FAILED: {update.error_type}: {update.message}"
                    )
                    self.gatt_read_status_color = WARNING_COLOR
                    self._render_gatt_read_status()
                elif update.operation == "write":
                    # A rejected write leaves the connection usable, allowing
                    # the user to correct the payload or select another mode.
                    self.gatt_write_status_text = (
                        f"WRITE FAILED: {update.error_type}: {update.message}"
                    )
                    self.gatt_write_status_color = WARNING_COLOR
                    self._render_gatt_write()
                elif update.operation in ("subscribe", "unsubscribe"):
                    # Subscription failures leave the BLE connection and GATT
                    # browser usable, so report them only on the monitor page.
                    self.gatt_monitor_status_text = (
                        f"{update.operation.upper()} FAILED: "
                        f"{update.error_type}: {update.message}"
                    )
                    self.gatt_monitor_status_color = WARNING_COLOR
                    monitor_values_changed = True
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
                
                self.gatt_monitor_target = None
                self.gatt_monitor_status_text = (
                    "NOT SUBSCRIBED — CONNECTION CLOSED"
                )
                self.gatt_monitor_status_color = MUTED_TEXT_COLOR

                if not self.connection_failed:
                    disconnected_unexpectedly = (
                        not self.return_to_scan_after_disconnect
                    )
                    self.return_to_scan_after_disconnect = False
                    self.connection_status_text = "DISCONNECTED"
                    self.connection_status_color = MUTED_TEXT_COLOR

                    if disconnected_unexpectedly:
                        self.live_status_text = "DEVICE DISCONNECTED"
                        self.live_status_color = WARNING_COLOR

                    # Connection-owned handles cannot be used after disconnect,
                    # so remove their cached screens before another operation is attempted.
                    self._build_live_scan()
                else:
                    self._render_connection_status()

        # Redrawing scan rows removes their selected state, so only scan
        # updates are allowed to rebuild that Listbox.
        if scan_state_changed:
            self._render_live_scan()
            
        # Rebuild only when START/STOP button states changed; ordinary incoming
        # values update the existing text widget without resetting the screen.
        if (
            monitor_controls_changed
            and self.gatt_monitor_status_label is not None
        ):
            self._build_gatt_monitor()
        elif monitor_values_changed:
            self._render_gatt_monitor()

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

