# Waveshare 3.5-inch Display

## Verified hardware

The project uses a Waveshare 3.5-inch RPi LCD (B), Rev2.0 on a Raspberry Pi
Zero 2 W Rev1.0. The display occupies GPIO header pins 1–26, starting at the
microSD-card end of the Pi.

The installed `waveshare35b-v2` overlay provides:

- `/dev/fb1`: ILI9486 framebuffer at 480x320;
- `ADS7846 Touchscreen`: input device exposed through the Linux input system.

`/dev/fb0` remains the Pi's primary framebuffer. Display services for this
project must explicitly select `/dev/fb1`.

## Boot configuration

The display requires these effective settings in
`/boot/firmware/config.txt`:

```ini
dtparam=spi=on
#dtoverlay=vc4-kms-v3d

[all]
dtoverlay=waveshare35b-v2
```

The overlay file is installed as:

```text
/boot/firmware/overlays/waveshare35b-v2.dtbo
```

## Xorg configuration

The Pi runs Raspberry Pi OS Lite, so the project uses a minimal Xorg server
without a desktop environment or window manager. The system-specific file
`/etc/X11/xorg.conf.d/99-waveshare.conf` selects:

- the `fbdev` driver with `/dev/fb1`;
- the `evdev` driver for `ADS7846 Touchscreen`;
- calibration values `3932 300 294 3801`;
- swapped axes for the display's rotated landscape layout.

The runtime packages are:

```text
xserver-xorg
xinit
xserver-xorg-video-fbdev
xserver-xorg-input-evdev
python3-tk
```

## Verified result

A fullscreen Tkinter test rendered on the Waveshare display. Tapping its
button changed the displayed message from `Waveshare display works` to
`Touch input works`. This proves the complete display path:

```text
Tkinter application
        ↓
Xorg fbdev and evdev drivers
        ↓
/dev/fb1 and ADS7846 Touchscreen
        ↓
Waveshare pixels and touch input
```

## Application boundary

The display code will consume the backend's structured scan, event, and
correlation results. It must not duplicate BLE scanning, GATT operations,
Nordic capture, or correlation logic. This keeps the terminal CLI and the
touchscreen as two interfaces over the same backend behavior.
