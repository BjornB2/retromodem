# MY018: automatic link speed with transistor switching

This option is intended only for the modified and tested Raspberry Pi 3/MY018
setup. An unmodified module remains at 9600 bit/s with solder bridges A0/B0/C0.
There is no general 57.6 kbit/s IrDA limit; the findings below apply to this
specific combination of module, control circuit, power supply and retro
devices.

## Verified results

| Maximum | Result |
| --- | --- |
| 9600 | Working baseline for PPP and Palm Beam |
| 19200 | Beam started; a complete transfer has not been verified |
| 38400 | Not tested yet |
| 57600 | PPP with Palm IIIc/OS 4.1 and Psion 5mx; complete Beam transfer to Palm |
| 115200 | Experimental; Palm Beam could not connect and Psion PPP has not been confirmed |

MochaTelnet (79,026 bytes) was transferred completely at 57.6 kbit/s in
23.910 seconds: 3.305 kB/s or 26.44 kbit/s of useful file data, including
connection setup. This is not a measurement of the optical baud rate or an
extensive stability certification. Receiving from a Palm at 57.6 kbit/s and
EPOC/X/YMODEM on the new module have not been reverified. The limitations in
the general documentation therefore still apply.

## Connections: physical pin number versus BCM

Disconnect all power, including the battery, before modifying the hardware.
Pin 4 of the IC is not used. The MY018 IC identity and internal schematic have
not been confirmed.

| Function | Physical Pi pin | BCM / details |
| --- | --- | --- |
| Board VCC | 1 | fixed 3.3 V; never power it directly from a GPIO |
| Board TXD | 8 | BCM14 / Pi TX; this board uses host-perspective labels, so do not cross TXD and RXD |
| Board RXD | 10 | BCM15 / Pi RX |
| A centre pad | 11 | BCM17, through 1 kΩ |
| B centre pad | 13 | BCM27, through 1 kΩ |
| C centre pad | 15 | BCM22, through 1 kΩ |
| 2N3904 base | 22 | BCM25, through 1 kΩ; remove the old R6/reset wire |
| 2N3904 emitter | 6 | actual Pi GND |
| 2N3904 collector | — | board GND, with no other direct board-GND-to-Pi-GND connection |

With the flat labelled side of this 2N3904 facing you and the leads pointing
down, the pins are emitter, base and collector from left to right. Give each
A/B/C centre pad its own 10 kΩ pull-down to **board GND**. Remove the A/B/C
solder bridges first and keep the three centre pads electrically separate.
The LEDs use ground on physical pins 14 and 20; the button uses physical pin 36
/ BCM16. Do not use an HDMI shield as the measurement reference. The transistor
does not have a proven current margin under every transmit condition; an
inadequate supply may affect reliability.

## Software

Use the included driver source and helper. Set the following values in
`/etc/retromodem/retromodem.env` only for this exact wiring:

```text
RETROMODEM_MY018_POWER_CYCLE=1
RETROMODEM_MY018_BITRATE=57600
RETROMODEM_IRDA_BITRATE=57600
```

On a new installation, the virtual Hayes/Comms port defaults to
`RETROMODEM_IRDA_DIALUP_BITRATE=115200` and
`RETROMODEM_MY018_DIALUP_BITRATE=115200`. This virtual speed is independent of
the 57.6 kbit/s physical infrared limit. Updates preserve existing speed
selections.

The public test installer applies these settings for `--adapter my018` after
the wiring has been confirmed. It also sets `enable_uart=1` and
`dtoverlay=disable-bt`, disables `hciuart` and the UART login console, and saves
the original boot files with a `.pre-retromodem` suffix. Bluetooth is therefore
unavailable in this configuration. A reboot is required before the PL011 UART
can be used as `/dev/serial0`. See [INSTALL.md](INSTALL.md) for the complete
clean-SD procedure.

The installer builds the modified `irtty-sir` source through DKMS and installs
the helper. With this explicit opt-in it also installs the module option and
adds `include retromodem-my018.txt` to the boot configuration. That file drives
BCM25 high early in the boot process, connecting board GND through the
transistor, while leaving A/B/C as inputs without internal pulls. The clean-SD
boot and power-cycle test is still part of release acceptance.

For every new IrDA attachment, the preparation step resets the module to 9600
bit/s. During a speed change, the driver releases UART and A/B/C, switches the
transistor off, waits 100 ms, drives only the required high bits, switches the
module on, waits 50 ms and restores the UART. Board-referenced pull-downs define
the low bits: driving GPIO outputs low while board ground is disconnected could
create an alternative current path. This runs in the sleepable IrDA thread
before the UART termios change. It is an experimental low-side switching design,
not a generic solution for other boards or GPIO assignments.

## Use

Select MY018 and the desired maximum on the Modem page. The setting is stored
per adapter; saving it disconnects the current session. New discovery starts
at 9600 bit/s and the connection then negotiates up to the configured maximum.
The connection or modem-port speed displayed by the retro device does not by
itself prove the physical link speed. Beam does not necessarily use the PPP
profile. Start at 57.6 kbit/s, or return to 9600 if problems occur. Keep Remote
Link disabled on the Psion.

The existing MY018 setup works. The public installer still needs clean-SD
acceptance including the reboot test. Keep access to the SD card: after a kernel
update, the driver must be rebuilt and checked for compatibility.

Design references (not confirmation of the MY018 IC):

- [Microchip AN756: BAUD pins are sampled at reset](https://www.microchip.com/content/dam/mchp/documents/APID/ApplicationNotes/ApplicationNotes/00756a.pdf)
- [Raspberry Pi boot GPIO configuration](https://www.raspberrypi.com/documentation/computers/config_txt.html#gpio-control)
- [2N3904 data sheet](https://www.onsemi.com/pdf/datasheet/2n3904-d.pdf)
