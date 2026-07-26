# Portable BLE Sniffer

A Raspberry Pi-based field tool for passive BLE discovery, capture control, and basic conversation viewing.

## Hardware

- Raspberry Pi Zero 2 W or Zero 2 WH
- Waveshare 3.5-inch RPi LCD (B)
- Nordic nRF52840 USB dongle
- microSD card
- USB OTG adapter
- Battery pack

## Project status

The project currently supports generic BLE discovery, selectable protocol
profiles, JSON advertisement reports, current-scan device selection, BLE
connection, and GATT enumeration. The next milestone adds profile-driven
writes, notification subscriptions, and operation logging. Passive Nordic
capture and the Waveshare interface remain later milestones.

## Documentation

- [Architecture](docs/architecture.md)

## Safety and authorization

This tool is intended for passive discovery and authorized testing of owned or permitted BLE devices.

## License

MIT License

Copyright (c) 2026 Anton Igudesman
