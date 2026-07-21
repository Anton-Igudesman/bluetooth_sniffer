# `bluetoothctl` Reference

This document lists the `bluetoothctl` commands used by this project. `bluetoothctl` is a command-line interface to BlueZ, the Linux Bluetooth stack. On the Raspberry Pi Zero 2 W, it controls the built-in Bluetooth controller, normally named `hci0`.

`bluetoothctl` does not control the PCA10059 when that dongle is running Nordic sniffer firmware. The dongle and the Pi's built-in Bluetooth controller have separate roles.

## Command notation

Commands shown with a shell prompt are entered in the normal terminal:

```console
$ bluetoothctl
```

Commands shown with a `bluetoothctl` prompt are entered after starting the interactive program:

```text
[bluetoothctl]> show
```

Do not type the `$` or `[bluetoothctl]>` prompt text.

Text inside angle brackets is a placeholder. Replace it with a real value and do not type the angle brackets. For example:

```text
info <device-address>
```

could become:

```text
info 41:1F:2C:9D:23:A1
```

Many BLE devices use private addresses that can change. Scan again instead of assuming an old address is still valid.

## Start and exit

Start an interactive session:

```console
$ bluetoothctl
```

Display commands available in the current menu:

```text
help
```

Return from a submenu to the main menu:

```text
back
```

Exit `bluetoothctl`:

```text
quit
```

## Controller commands

List Bluetooth controllers known to BlueZ:

```text
list
```

Show the default controller's status and capabilities:

```text
show
```

Show a specific controller:

```text
show <controller-address>
```

Select the controller that later commands will use:

```text
select <controller-address>
```

Power the selected controller on or off:

```text
power on
power off
```

Set whether other devices may initiate pairing with this controller:

```text
pairable on
pairable off
```

`pairable off` does not stop this project from scanning or initiating a connection. It prevents unsolicited incoming pairing requests.

Set whether other devices can discover this controller:

```text
discoverable on
discoverable off
```

The Pi does not need to be discoverable when it is acting as a BLE central and looking for peripherals.

## Scanning and device information

Start a BLE-only scan:

```text
scan le
```

Stop the active scan:

```text
scan off
```

Run a 15-second BLE scan without entering an interactive session:

```console
$ bluetoothctl --timeout 15 scan le
```

List devices currently known to BlueZ:

```text
devices
```

Filter the device list by a stored property:

```text
devices Paired
devices Bonded
devices Trusted
devices Connected
```

Show information about one device:

```text
info <device-address>
```

Useful `info` fields include:

- `AddressType`: whether the address is public or random.
- `Name` and `Alias`: the advertised name and the local BlueZ name.
- `Paired` and `Bonded`: whether security information has been exchanged and stored.
- `Trusted`: whether BlueZ may reconnect automatically without asking.
- `Connected`: whether a connection currently exists.
- `UUID`: services BlueZ has discovered or seen advertised.
- `RSSI`: received signal strength in dBm; a value closer to zero is stronger.

Unpaired devices found during a scan may be removed from BlueZ after some time. Keep an interactive scan running when a temporary device must remain available for an immediate connection.

## Connect and disconnect

Connect to a device that is currently advertising:

```text
connect <device-address>
```

For BLE, BlueZ normally needs a recent active scan report before it can connect. If a connection fails because the device is unavailable, confirm that it is still advertising and scan again.

Disconnect from a device:

```text
disconnect <device-address>
```

Show currently connected devices:

```text
devices Connected
```

Connecting does not automatically mean that a device has been paired or bonded.

## Pairing and trust

Enable an authentication agent before pairing:

```text
agent KeyboardDisplay
default-agent
```

Other agent capabilities include `DisplayOnly`, `DisplayYesNo`, `KeyboardOnly`, and `NoInputNoOutput`. The correct capability depends on how the two devices confirm identity.

Initiate pairing with an owned or authorized device:

```text
pair <device-address>
```

BlueZ's `pair` command pairs, trusts, and connects the device. Do not use it merely to test an ordinary connection.

Trust or untrust a device explicitly:

```text
trust <device-address>
untrust <device-address>
```

Remove a device and its stored pairing information from BlueZ:

```text
remove <device-address>
```

`remove` changes stored state and requires pairing again if the device is needed later.

## GATT commands

Connect to the device before working with its GATT services and characteristics.

Enter the GATT submenu:

```text
menu gatt
```

List the connected device's services, characteristics, and descriptors:

```text
list-attributes
```

Select a characteristic or descriptor by UUID or BlueZ object path:

```text
select-attribute <attribute-or-uuid>
```

Show the selected attribute's UUID, handle, supported flags, and other properties:

```text
attribute-info
```

Read the selected attribute:

```text
read
```

Write hexadecimal bytes to the selected attribute:

```text
write <hex-byte> [hex-byte ...]
```

For example, the UTF-8 text `Hi` is represented by the hexadecimal bytes `48 69`:

```text
write 48 69
```

Check `attribute-info` before writing. A characteristic must advertise a suitable flag such as `write` or `write-without-response`. A write may cause a physical or persistent action on the target, so only write a known value to an owned or explicitly authorized test device.

Enable or disable notifications from the selected characteristic:

```text
notify on
notify off
```

Return to the main menu:

```text
back
```

## Nordic UART Service UUIDs

The controlled iPhone test peripheral uses Nordic UART Service (NUS):

| Attribute | UUID | Typical central operation |
| --- | --- | --- |
| NUS service | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | Discover the service |
| RX characteristic | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Write data to the peripheral |
| TX characteristic | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Subscribe to notifications |

The RX and TX names describe the peripheral's perspective. The Pi writes to the peripheral's RX characteristic and receives notifications from the peripheral's TX characteristic.

## Project test sequence

The following sequence discovers and connects to the controlled `Test BLE` iPhone advertiser. Replace `<device-address>` with the address reported by the current scan.

```text
scan le
info <device-address>
scan off
connect <device-address>
menu gatt
list-attributes
```

Inspect an attribute before selecting, reading, writing, or subscribing to it. Disconnect when the test is finished:

```text
back
disconnect <device-address>
quit
```

## Related commands outside `bluetoothctl`

Show whether Linux has blocked the Bluetooth radio:

```console
$ rfkill list bluetooth
```

Remove a software radio block:

```console
$ sudo rfkill unblock bluetooth
```

Capture communication between BlueZ and the Pi's Bluetooth controller:

```console
$ sudo btmon
```

`btmon` captures the Pi's local HCI activity. It is not a replacement for the PCA10059's independent over-the-air packet capture.

## References

- [Debian Trixie `bluetoothctl` manual](https://manpages.debian.org/trixie/bluez/bluetoothctl.1.en.html)
- [Debian Trixie `bluetoothctl` GATT manual](https://manpages.debian.org/trixie/bluez/bluetoothctl-gatt.1.en.html)
- [BlueZ Adapter API](https://bluez.readthedocs.io/en/latest/adapter-api/)
- [BlueZ GATT API](https://bluez.readthedocs.io/en/latest/gatt-api/)
