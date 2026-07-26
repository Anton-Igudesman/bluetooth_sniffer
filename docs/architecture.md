# Architecture

## Purpose

The application is a generic BLE analysis tool. Its scanner, connection
handling, capture support, and replay support must not depend on one device,
address, or protocol such as Nordic UART Service (NUS).

## Configuration boundaries

| Kind of value | Examples | Source |
| --- | --- | --- |
| Runtime setting | Scan duration, adapter, output path | CLI arguments or application settings |
| Protocol definition | Service and characteristic UUIDs | Selectable profile file |
| Discovered state | Device address, name, RSSI, advertisement data | Current BLE scan |
| Sensitive material | Pairing keys, IRKs, LTKs | Local protected storage; never tracked by Git |

These categories must remain separate. In particular, a device address found
during one scan is not configuration: BLE privacy can change that address.

## Protocol profiles

Bluetooth advertisements contain UUID values, not reliable human-readable
protocol names. The application can identify NUS only by comparing an
advertised UUID with a known NUS definition.

Known UUIDs therefore need to exist somewhere, but they must not be buried in
scanner logic. A tracked profile makes the definition visible, selectable,
and replaceable without changing the scanner.

A NUS profile will contain values equivalent to:

```toml
name = "Nordic UART Service"
service_uuid = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
rx_uuid = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
tx_uuid = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
```

The UUIDs are fixed protocol identifiers. Selecting NUS for every scan would
be hardcoded application behavior; loading the same identifiers from a
selected profile is configuration.

## Discovery and connection

The active BLE path is:

```text
runtime settings + optional profile
                ↓
          generic scanner
                ↓
 BLEDevice + AdvertisementData
                ↓
       selected BLEDevice
                ↓
       connection and GATT
```

The program must connect with the `BLEDevice` returned by the current scan.
It must not copy a previously observed address into source code or assume that
an address remains stable.

Scanning lists available devices and their advertisement data without
automatically filtering by the selected profile. A valid peripheral may omit
its GATT service UUIDs from its advertisement, as the LightBlue NUS test
device did. After connection, the selected profile validates the discovered
GATT table and supplies the UUIDs used for protocol operations.

## UUIDs and GATT handles

A UUID identifies the purpose of a service, characteristic, or descriptor.
A handle identifies one entry in the connected device's current GATT
attribute table. Handles are used in ATT traffic and packet captures, but
they can change when the peripheral rebuilds or reorders its GATT database.

Protocol profiles therefore store stable UUIDs rather than observed handles.
After connecting, the application finds the current characteristic by UUID
and passes the resulting Bleak characteristic object to read, write, or
notification operations.

During one controlled iPhone test, NUS RX had handle `26`, NUS TX had handle
`29`, and the TX notification configuration descriptor had handle `31`.
During a later test, those handles were `66`, `69`, and `71`. The changing
values describe separate discovered GATT databases and must not become
profile configuration.

### ATT operations

The Attribute Protocol (ATT) carries the individual messages used to access
the GATT attribute table. An ATT operation identifies a current attribute
handle and performs an action such as reading its value, writing bytes, or
delivering a notification.

The application normally calls higher-level Bleak GATT methods. Bleak and
BlueZ translate those calls into ATT messages. For example:

- writing NUS RX becomes an ATT write targeting its current handle;
- subscribing to NUS TX configures its notification descriptor;
- incoming NUS TX data arrives as an ATT notification containing the TX
  handle and value.

ATT handles and operation names will appear in HCI and over-the-air packet
captures even though application configuration continues to use UUIDs.

Human-readable characteristic descriptions produced by tools are not
authoritative. In one verified `btmon` capture, BlueZ described NUS UUID
`...0002` as "Nordic UART TX" and `...0003` as "Nordic UART RX", the reverse
of the roles defined by the NUS profile. Correlation must use the complete
UUID, ATT operation direction, handle, and payload rather than the description
alone.

## Radio roles

The Raspberry Pi's built-in Bluetooth controller handles active operations:

- discovery;
- connection and pairing;
- GATT service enumeration;
- characteristic reads and writes;
- notification subscriptions.

The Nordic PCA10059 handles passive over-the-air capture using the bundled
nRF Sniffer for Bluetooth LE firmware. Flashing that firmware replaces the
dongle's connectivity application until connectivity firmware is restored.
`btmon` separately records HCI traffic generated by the Pi's own controller.

These are independent data sources. Passive packets, local HCI events, and
application-level operations must not be presented as if they were the same
capture layer.

The Nordic CLI requires a current address to follow this LightBlue peripheral
reliably. A controlled `--follow-by-name` capture recorded two valid
`CONNECT_IND` packets but did not follow either connection onto its data
channels. Repeating the test with `--follow` and the address returned by the
immediately preceding scan captured 99 decoded ATT packets. The address is
therefore a runtime capture selector, not profile or source-code configuration.

## Current implementation

The active BLE path now supports:

- generic discovery through `BluetoothScanner`;
- selectable protocol definitions loaded from TOML;
- optional JSON reports containing portable advertisement data;
- exact device matching against current addresses and reported names;
- numbered selection when a name matches multiple current scan results;
- connection using the selected `BLEDevice`;
- validation of the selected profile against the connected GATT database;
- explicit profile-driven RX writes with a selectable with-response or
  without-response mode;
- profile-driven TX notification subscriptions with hexadecimal and optional
  UTF-8 output;
- optional JSONL event logs containing UTC timestamps and portable details for
  completed scans, connections, profile validation, RX writes, and TX
  notifications;
- GATT service, characteristic, property, and descriptor enumeration;
- guaranteed disconnect after GATT inspection, writes, notification
  subscriptions, or failures;
- passive Nordic PCAP capture of advertisements, connection establishment, and
  unencrypted ATT traffic for a selected current device address;
- automatic Nordic process startup and cleanup through `NordicCapture`, using
  explicit `--nordic-port` and `--nordic-pcap` runtime options;
- JSONL `capture.started` and `capture.completed` records that link an
  application session to its current device address, Nordic port, and PCAP;
- typed parsing of Nordic ATT packets from finalized PCAP files through
  TShark's JSON output.

The controlled LightBlue iPhone test verified that the NUS profile can connect
to a virtual peripheral even when its advertisement omits the NUS service
UUID. GATT enumeration found:

- NUS RX `6e400002-b5a3-f393-e0a9-e50e24dcca9e`, supporting `write` and
  `write-without-response`;
- NUS TX `6e400003-b5a3-f393-e0a9-e50e24dcca9e`, supporting `notify`;
- the TX Client Characteristic Configuration descriptor used to enable
  notifications.

The Pi successfully wrote the 13 UTF-8 bytes for `hello from pi` to NUS RX
using a write with response. LightBlue then sent `68 69` through NUS TX, and
the application received and decoded the notification as `hi`. These tests
verify both active NUS data directions without treating the iPhone's changing
BLE address or GATT handles as configuration.

A later paired application/HCI capture verified the same operations at the
ATT layer:

- an ATT Write Request sent 17 bytes for `hci write from pi` to NUS UUID
  `...0002` at handle `0x001e`, followed by an ATT Write Response;
- an ATT Handle Value Notification delivered `68 69` from NUS UUID `...0003`
  at handle `0x001b`;
- an ATT Write Request sent `0000` to handle `0x001c` when
  `stop_notify()` disabled the TX Client Characteristic Configuration
  descriptor at the end of the listening interval.

A controlled application/Nordic capture then verified the notification over
the air. The application logged NUS TX UUID `...0003` with payload `68 69`.
The independent Nordic capture recorded the same bytes in frame `7386` as an
ATT Handle Value Notification (`0x1b`) on handle `0x0042`, with an RSSI of
`-46 dBm`. The handle and Wireshark's human-readable TX/RX description remain
session-specific observations; the UUID, operation direction, and payload
establish the protocol identity.

The automated capture path was then verified without a second terminal.
`NordicCapture` received the selected `BLEDevice.address`, started exact-address
following before the GATT connection, and kept the capture active through
disconnect. Because nRF Util launches both a wrapper and a
`nrfutil-ble-sniffer` helper, the capture starts in a separate process group.
Cleanup signals the entire group so both processes exit and the PCAP closes
normally.

The resulting automated PCAP contained 1,399 packets and 85 decoded ATT
packets. Frame `485` contained notification bytes `68 69` on handle `0x0042`
with RSSI `-35 dBm`. No nRF Util process remained after normal application
completion.

The capture lifecycle log was verified in a separate connection-only session.
It recorded `capture.started`, `connection.opened`, `connection.closed`,
`capture.completed`, and `session.completed` in order. The capture and
connection records shared current address `53:26:7C:35:07:A2`, and the
completed capture record named the finalized PCAP. No nRF Util process
remained after the session.

The first full-PCAP parser test processed the automated capture and returned
the same 85 ATT packets previously counted by TShark. Parsed frame `485`
retained its UTC timestamp, connection access address, central and peripheral
addresses, RSSI `-35 dBm`, notification opcode, handle `0x0042`, service UUID,
and payload bytes `68 69` (`hi`).

## Next implementation steps

1. Correlate application JSONL, HCI, and passive PCAP records without relying
   on session-specific handles or human-readable characteristic labels.
