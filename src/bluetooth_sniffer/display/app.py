import argparse
import tkinter as tk
from pathlib import Path

from .model import CorrelationSummary, load_correlation_summary

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
        summary: CorrelationSummary,
    ) -> None:
        self.root = root
        self.summary = summary
        
        self.root.title("Bluetooth Sniffer")
        self.root.configure(background=BACKGROUND_COLOR)
        
        # Size application directly from Waveshare X screen dimensions
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        self.root.overrideredirect(True)
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        
        self._build_summary()
        
    def _build_summary(self) -> None:
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
        
        # Touch exit
        tk.Button(
            container,
            text="CLOSE",
            command=self.root.destroy,
            font=("DejaVu Sans", 11, "bold"),
            padx=20,
            pady=5,
        ).pack(pady=(12,0))
        
def run() -> None:
    arguments = parse_arguments()
    
    # Validate complete summary before rendering
    summary = load_correlation_summary(arguments.report)
    
    root = tk.Tk()
    CorrelationDashboard(root, summary)
    root.mainloop()
    
if __name__ == "__main__":
    run()

