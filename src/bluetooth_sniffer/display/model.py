from dataclasses import dataclass
from pathlib import Path

from ..report_io import read_correlation_report, required_integer

@dataclass(frozen=True)
class CorrelationSummary:
    event_count: int
    matched_count: int
    unmatched_count: int

def load_correlation_summary(path: Path) -> CorrelationSummary:
    report = read_correlation_report(path)
    
    # Apply the same integer type rule to report counts and JSONL ATT handles
    event_count = required_integer(report, "event_count", path)
    matched_count = required_integer(report, "matched_count", path)
    unmatched_count = required_integer(report, "unmatched_count", path)
    
    counts = (event_count, matched_count, unmatched_count)
    
    # Reject negative count totals
    if any(count < 0 for count in counts):
        raise ValueError(f"{path}: correlation counts cannot be negative")
    
    # Reject inconsistent totals
    if matched_count + unmatched_count != event_count:
        raise ValueError(
            f"{path}: matched_count + unmatched_count must equal event_count"
        )
        
    return CorrelationSummary(
        event_count=event_count,
        matched_count=matched_count,
        unmatched_count=unmatched_count,
    )