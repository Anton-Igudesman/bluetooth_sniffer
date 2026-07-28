# Post-MVP Refactors

This document records structural improvements that are useful but not required
to complete the first working version.

## Project exception hierarchy

### Current decision

Continue using standard exceptions such as `RuntimeError`, `ValueError`, and
`FileExistsError` during the MVP. Existing validation messages should continue
to identify the failed operation and relevant project value.

### Reason to revisit

Expected failures now come from several boundaries:

- BLE scanning and device selection;
- profile loading and validation;
- GATT connection state and operations;
- the external Nordic capture process;
- output-file creation.

If every expected failure is logged and re-raised as a general exception, the
CLI can produce repetitive logs and full tracebacks for problems that a user
can correct. A helper function that only constructs `RuntimeError` would reduce
typing without giving callers a reliable way to distinguish these failures.

### Proposed refactor

- Add a project-level base exception such as `BluetoothSnifferError`.
- Add focused subclasses only where callers need different handling, beginning
  with a passive-capture exception.
- Raise project exceptions for expected operational failures.
- Catch the project base exception once at the CLI boundary, record one failure
  event, print one concise message, and return a nonzero exit status.
- Continue allowing unexpected programming errors to produce their original
  tracebacks.
- Preserve exception chaining when translating a lower-level failure so its
  original cause remains available for diagnosis.

### Completion criteria

- An expected Nordic startup failure produces one application event and one
  concise terminal error.
- An unexpected code defect still retains its traceback.
- Tests demonstrate that distinct error messages keep the relevant device,
  profile, path, or operation context.
- No helper is introduced solely to shorten `raise RuntimeError(...)`.

## Automated correlation tests

### Current decision

Defer the automated test suite until after the DEFCON MVP display workflow is
operational. The current correlation implementation is backed by retained
JSONL, Nordic PCAP, and structured-report artifacts from a verified automatic
session that produced `2/2` matches.

### Reason to revisit

The correlation engine now makes several decisions that should remain stable
as the application evolves:

- matching writes and notifications by ATT operation, value handle, payload,
  and timestamp;
- preserving an ordinary unmatched event when other ATT packets exist;
- rejecting a passive capture containing no decoded ATT packets;
- parsing payload bytes when Wireshark replaces `btatt.value` with a
  profile-specific field;
- keeping repeated identical payloads associated with separate packet frames.

Manual hardware sessions verify the complete system but are too variable and
slow to run as regression checks after every code change.

### Proposed work

- Add pytest as an optional development dependency rather than a deployed
  runtime dependency.
- Add deterministic in-memory tests for matched, unmatched, duplicate-payload,
  and unusable-capture correlation.
- Add parser fixtures representing generic `btatt.value` and
  profile-specific raw ATT payloads.
- Keep hardware capture checks as separate integration tests that are not
  required for every local test run.

### Completion criteria

- Tests run without Bluetooth hardware, LightBlue, Nordic capture, or live
  TShark input.
- Matched, unmatched, and unusable-capture decisions are covered.
- A regression in UUID-to-value-handle matching or raw ATT payload extraction
  fails deterministically.
