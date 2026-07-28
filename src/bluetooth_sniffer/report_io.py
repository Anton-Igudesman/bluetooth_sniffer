import json
from pathlib import Path
from typing import cast


# Writers and readers share this value so a saved layout cannot be interpreted
# as the current format after its fields or meanings change.
CORRELATION_REPORT_SCHEMA_VERSION = 1

def required_integer(
    record: dict[str, object],
    key: str,
    path: Path,
    line_number: int | None = None,
) -> int:
    value = record.get(key)
    
    # True/False are not valid ATT handles and must fail JSON validation
    if isinstance(value, bool) or not isinstance(value, int):
        source = (
            f"{path}:{line_number}"
            if line_number is not None
            else str(path)
        )
        raise ValueError(f"{source}: {key} must be an integer")
    
    return value

def read_correlation_report(path: Path) -> dict[str, object]:
    try:
        report: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        # Consolidate report-loading failures into an error the touchscreen can
        # display without knowing whether the file or its JSON was defective.
        raise ValueError(
            f"Could not read correlation report {path}: {error}"
        ) from error

    if not isinstance(report, dict):
        raise ValueError(
            f"{path}: correlation report must contain a JSON object"
        )

    schema_version = report.get("schema_version")

    # Reject incompatible layouts before the screen interprets renamed or
    # repurposed fields as valid capture evidence.
    if schema_version != CORRELATION_REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: unsupported correlation report schema version "
            f"{schema_version!r}"
        )

    # JSON object keys are strings, so downstream display code can use the
    # report without carrying json.loads()'s unrestricted return type.
    return cast(dict[str, object], report)


def write_json_report(report: object, output_path: Path) -> None:
    # Report paths commonly use ignored logs/ directories that do not exist in
    # a fresh checkout, so create the selected parent before saving evidence.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )