# Hardware

This document records the physical components and interface constraints of the portable BLE sniffer.

## Host computer

- Raspberry Pi Zero 2 W-family board
- 40-pin GPIO header installed
- microSD card for operating-system and capture storage
- One micro-USB On-The-Go data port
- One separate micro-USB power port

## Display

- Manufacturer: Waveshare
- Product: 3.5inch RPi LCD (B)
- Hardware revision: Rev2.0
- Resolution: 480 × 320 pixels
- Panel: IPS
- Display interface: SPI
- Touch interface: SPI
- Touch type: Resistive
- Connector: 26-pin GPIO connector
- Normal operating current: Approximately 150 mA

The display connector fits over physical GPIO-header pins 1–26. Physical pins 27–40 remain uncovered.

### Display pin usage

| Physical pin | Function |
|-------------:|----------|
| 1 | 3.3 V power |
| 2 | 5 V power |
| 4 | 5 V power |
| 6 | Ground |
| 9 | Ground |
| 11 | Touch interrupt |
| 14 | Ground |
| 17 | 3.3 V power |
| 18 | LCD command/data selection |
| 19 | LCD and touch SPI data input |
| 20 | Ground |
| 21 | Touch SPI data output |
| 22 | LCD reset |
| 23 | LCD and touch SPI clock |
| 24 | LCD chip select |
| 25 | Ground |
| 26 | Touch chip select |

Waveshare marks physical pins 3, 5, 7, 8, 10, 12, 13, 15, and 16 as not connected by the display.

| Physical pin | BCM GPIO | Purpose |
|-------------:|----------|---------|
| 19 | GPIO10 | MOSI: Pi sends data to the display or touch controller |
| 21 | GPIO9 | MISO: Touch controller sends data to the Pi |
| 23 | GPIO11 | SPI clock |
| 24 | GPIO8 | Selects the display |
| 26 | GPIO7 | Selects the touchscreen |

## BLE radio

- Manufacturer: Nordic Semiconductor
- Radio: nRF52840
- Form: USB dongle
- Host connection: Raspberry Pi USB data port through a micro-USB OTG adapter
- Purpose: Dedicated BLE packet capture and connection following

The nRF52840 connects to the Pi’s USB data port, not the separate power-only micro-USB port.

## Power

Waveshare recommends a stable 5 V, 2.5 A supply for the combined Raspberry Pi and display setup.

## Physical constraints

- Pins 27–40 remain physically accessible after display is connected.
- SPI0 is shared by the display and touchscreen.
- GPIO7 and GPIO8 provide separate chip-select signals for touch and display.
- The USB OTG adapter provides data and power.
