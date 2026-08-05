# Development Workflow and Handoff

## Current stopping point

The latest completed milestone is touchscreen-controlled Nordic capture.
From the Waveshare interface, the operator can:

- scan for nearby BLE devices;
- select and connect to a device returned by the current scan;
- browse its GATT services, characteristics, and descriptors;
- read and write supported characteristics;
- subscribe to notifications;
- start the Nordic sniffer before opening the BLE connection; and
- stop and finalize the PCAP after disconnecting.

The touchscreen currently saves the passive PCAP, but it does not yet create
the application event log or automatically correlate the completed session.
The terminal workflow already contains the event logging and correlation
building blocks needed for that work.

## Overall demo narrative

The intended end-to-end demo is:

```text
discover device
    -> select device
    -> start passive capture
    -> connect and inspect GATT
    -> perform a read, write, or notification operation
    -> disconnect and finalize evidence
    -> correlate the operation with an over-the-air packet
    -> present a structured report
```

This evidence chain is important because a PCAP alone does not explain which
operation the tester intentionally performed, which UUID was selected, or
whether a captured ATT packet corresponds to that action. The application log
provides intent and stable UUIDs; the Nordic capture provides independent
over-the-air evidence. Correlation joins them using operation type, payload,
timestamp, and the connection's temporary UUID-to-ATT-handle mappings.

This is also the foundation for a later authorized security-assessment demo.
Controlled assessment actions can be added without redesigning the capture
path because each action will already be logged, passively verified, and
included in a report.

## Next milestone: touchscreen evidence pipeline

The next milestone is to make each touchscreen capture a self-contained
session bundle:

```text
captures/
└── touchscreen-<UTC timestamp>-<device address>/
    ├── session.jsonl
    ├── capture.pcap
    └── correlation.json
```

The exact directory-name encoding may change during implementation, but every
artifact for one connection must remain grouped together and must never
overwrite an earlier session.

### Implementation status

The first development slice now reserves the session directory atomically and
records the touchscreen lifecycle in `session.jsonl`. Successful reads,
writes, subscription changes, notifications, connection state, capture state,
and UUID-to-handle mappings use the existing terminal event schema. Session
failures and cancellation are also retained. Automatic correlation and report
loading remain the next slice.

### Step 1: create and populate the event log

When `CAPTURE + CONNECT` begins, create `session.jsonl` and record UTC-dated
events for:

- session start and completion;
- capture start and completion;
- connection open and close;
- discovered characteristic UUID-to-handle mappings;
- characteristic reads and writes;
- notification subscription changes; and
- received notification payloads.

UUID-to-handle mappings are essential. UUIDs identify protocol attributes,
while ATT handles are temporary values from the connected device's current
GATT database. Correlation must not assume that a handle remains stable across
connections.

Reuse the existing `EventLogger` record format so touchscreen logs remain
compatible with `analyze_session()` and `bluetooth-sniffer-analyze`. Avoid
creating a second touchscreen-specific event schema.

### Step 2: correlate after clean shutdown

After the connection closes and the Nordic process has finalized the PCAP:

1. close or flush the application event log;
2. analyze `session.jsonl` and `capture.pcap` with the existing correlation
   engine;
3. write the result to `correlation.json`; and
4. retain clear failure states when the PCAP is missing, contains no decoded
   ATT traffic, or cannot be parsed.

Correlation must never run against a PCAP that is still being written.

### Step 3: show the new report

After successful correlation, load the newly generated report into the
touchscreen dashboard. The operator should be able to move directly from the
completed live session to its summary and matched or unmatched event details
without restarting the application or entering paths in a terminal.

## Acceptance criteria

The milestone is complete when a single touchscreen-driven test can:

1. scan and select a current BLE device;
2. start Nordic capture and connect;
3. perform at least one logged GATT write or receive one logged notification;
4. disconnect and stop every capture subprocess;
5. produce a non-overwriting session bundle containing JSONL, PCAP, and JSON;
6. correlate the application event with passive ATT evidence when present;
7. preserve unmatched events as explicit results; and
8. open the generated correlation report on the touchscreen.

Normal completion and failure paths must both disconnect BLE, stop the full
Nordic process group, and leave finalized artifacts in an understandable
state.

## Deferred work

Authorized red-team capabilities are deliberately on the back burner until
the evidence pipeline is complete. A future assessment layer may add scoped
permission checks, controlled replay, and bounded protocol robustness tests.
Those features should require an explicitly selected current device, preserve
rate limits and audit logs, and reuse the same session evidence pipeline.
