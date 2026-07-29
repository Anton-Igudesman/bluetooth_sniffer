import argparse
import tkinter as tk
from pathlib import Path

from .model import CorrelationReport, load_correlation_report

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
    return parser.parse_args()

class CorrelationDashboard:
    def __init__(
        self,
        root: tk.Tk,
        report: CorrelationReport,
    ) -> None:
        self.root = root
        self.report = report
        self.summary = report.summary
        
        self.root.title("Bluetooth Sniffer")
        self.root.configure(background=BACKGROUND_COLOR)
        
        # Size application directly from Waveshare X screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        self.root.overrideredirect(True)
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        
        self._build_summary()
    
    def _clear_screen(self) -> None:
        # Screen navigation replaces widgets but keeps the validated report in memory
        for widget in self.root.winfo_children():
            widget.destroy()
            
    @staticmethod
    def _shorten(value: str, limit: int) -> str:
        # Preserve full payload preventing display leaks
        return value if len(value) <= limit else f"{value[:limit - 3]}..."
        
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
            command=self.root.destroy,
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
    CorrelationDashboard(root, report)
    root.mainloop()
    
if __name__ == "__main__":
    run()

