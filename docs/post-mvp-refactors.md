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
