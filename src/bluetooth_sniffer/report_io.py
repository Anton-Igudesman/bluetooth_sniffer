import json
from pathlib import Path
from typing import cast


# Writers and readers share this value so a saved layout cannot be interpreted
# as the current format after its fields or meanings change.
CORRELATION_REPORT_SCHEMA_VERSION = 1

def _source_label(path: Path, line_number: int | None) -> str:
    # JSONL records include a line number, while correlation reports 
    # only identify file containing invalid field
    return (
        f"{path}:{line_number}"
        if line_number is not None
        else str(path)
    )

def field_error(
    path: Path,
    line_number: int | None,
    key: str,
    requirement: str,
) -> ValueError:
    # Both JSONL events and complete reports use one field-error format
    # JSONL callers supply record's line number
    source = _source_label(path, line_number)
    return ValueError(f"{source}: {key} must be {requirement}")

def _required_type[T](
    record: dict[str, object],
    key: str,
    expected_type: type[T],
    requirement: str,
    path: Path,
    line_number: int | None = None,
    *,
    reject_boolean: bool = False,
) -> T:
    value = record.get(key)
    
    # Reject bool when reading counts and handles so JSON true doesn't become numeric 1
    invalid_boolean = reject_boolean and isinstance(value, bool)
    
    if not isinstance(value, expected_type) or invalid_boolean:
        raise field_error(path, line_number, key, requirement)
    
    return value

def required_integer(
    record: dict[str, object],
    key: str,
    path: Path,
    line_number: int | None = None,
) -> int:
    return _required_type(
        record,
        key,
        int,
        "an integer",
        path,
        line_number,
        reject_boolean=True,
    )

def required_string(
    record: dict[str, object],
    key: str,
    path: Path,
    line_number: int | None = None,
) -> str:
    return _required_type(
        record,
        key,
        str,
        "a string",
        path,
        line_number,
    )
    
def required_hex_bytes(
    record: dict[str, object],
    key: str,
    path: Path,
    line_number: int | None = None,
) -> bytes:
    value = required_string(record, key, path, line_number)
    
    try:
        # Application logs and correlation reports store BLE payloads as hex
        # Return bytes so matching and display models use same representation
        return bytes.fromhex(value)
    except ValueError as error:
        raise field_error(
            path,
            line_number,
            key,
            "valid hex bytes",
        ) from error

def required_boolean(
    record: dict[str, object],
    key: str,
    path: Path,
    line_number: int | None = None,
) -> bool:
    return _required_type(
        record,
        key,
        bool,
        "a boolean",
        path,
        line_number,
    )

def required_object(
    record: dict[str, object],
    key: str,
    path: Path,
    line_number: int | None = None,
) -> dict[str, object]:
    value = _required_type(
        record,
        key,
        dict,
        "a JSON object",
        path,
        line_number,
    )
    return cast(dict[str, object], value)

def required_list(
    record: dict[str, object],
    key: str,
    path: Path,
    line_number: int | None = None,
) -> list[object]:
    value = _required_type(
        record,
        key,
        list,
        "a JSON array",
        path,
        line_number,
    )
    return cast(list[object], value)

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