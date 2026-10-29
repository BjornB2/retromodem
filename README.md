# RetroModem

> **Test version — not yet released.** The installer and SD image are being
> prepared for clean-install testing on a Raspberry Pi 3B. A stable release
> will follow after the acceptance tests pass. This repository is currently
> private; there is no downloadable SD image yet.
>
> MY018 is the preferred infrared build. MA-620 is the USB infrared fallback;
> Prolific USB-to-RS-232 is the main connection for computers without infrared.
> Other Raspberry Pi models have not been tested.
> See [PUBLICATION-STATUS.md](PUBLICATION-STATUS.md) for remaining preparation.

**Network bridge and virtual modem for retro computers and handhelds**

On your connected retro browser, open **http://start.retromodem/** for Search,
ChatGPT and Settings. **http://setup.retromodem/** lists local configuration
pages, including **http://wifi.retromodem/** for Wi-Fi setup from the retro
device itself. See the [quickstart](docs/QUICKSTART.md).

**http://proxy.retromodem/** provides page-size and image settings from the
retro device, also linked from Setup. See [retro proxy settings](docs/RETRO-PROXY-SETTINGS.md).

RetroModem turns a Raspberry Pi into a standalone internet bridge and Hayes
modem for vintage handhelds and computers. The preferred infrared build uses a
Ming Yuan MY018 module connected to the Pi's GPIO/UART. Computers without
infrared connect through a Prolific USB-to-RS-232 adapter and the appropriate
serial cable. A Mobile Action MA-620 USB adapter provides an infrared fallback.
PPP traffic is routed
through the Pi's Wi-Fi network; Hayes dialing can open internet PPP or a BBS.

The project is hardware-independent. Adapter-specific details live in hardware
profiles; the web interface, PPP service and network management remain shared.

## Connection options

All three connection options belong to the same installation and release.

| Connection | Intended use |
| --- | --- |
| **MY018 GPIO/UART infrared** | Preferred infrared build, with the documented selector wiring and transistor circuit |
| **Prolific USB-to-RS-232** | Main wired connection for computers without infrared; cable/null-modem requirements depend on the computer |
| **MA-620 USB infrared** | Fallback when the MY018 build is not used |

An RS-232 adapter is electrically different from a USB-TTL cable. Use the
correct adapter and pinout for the target computer.

## MY018 prototype wiring

This assembly overview shows the Raspberry Pi 3B, MY018, two status LEDs, mode
button and the battery/charging/step-up power chain. It is intended as a
practical wiring aid rather than a formal electronic schematic. Follow the
pin table and notes below as well: resistor values and the internal MY018
modification are not all legible in the drawing itself.

![RetroModem prototype wiring overview](docs/retromodem-prototype-wiring.png)

The MY018 in this drawing is a stand-in because the exact module is not
available in the drawing tool. Its four side connections are, from top to
bottom, **GND, RXD, TXD and VCC**; the three selector pads are **A, B and C**.

| Part or connection | Physical Pi pin | Function / BCM |
| --- | ---: | --- |
| MY018 VCC | 1 | 3.3 V |
| MY018 TXD | 8 | BCM14 / Pi TX; the tested board uses host-perspective labels, so do not cross TXD and RXD |
| MY018 RXD | 10 | BCM15 / Pi RX |
| MY018 A centre pad | 11 | BCM17, through 1 kΩ |
| MY018 B centre pad | 13 | BCM27, through 1 kΩ |
| MY018 C centre pad | 15 | BCM22, through 1 kΩ |
| 2N3904 base | 22 | BCM25, through 1 kΩ |
| 2N3904 emitter | 6 | Pi GND |
| 2N3904 collector | — | MY018 board GND |
| Dial-up/status LED | 16 | BCM23, through 330 Ω; cathode to GND pin 14 |
| PPP/status LED | 18 | BCM24, through 330 Ω; cathode to GND pin 20 |
| Mode/shutdown button | 36 | BCM16; other side to GND pin 34 |
| Raspberry Pi power | 2 and 9 | 5 V and GND from the adjusted MT3608 output |

The assembly drawing is not a substitute for the modification instructions.
In particular:

- remove the original A/B/C solder bridges;
- connect each A/B/C centre pad to its GPIO through its own 1 kΩ resistor;
- add a separate 10 kΩ pull-down from each centre pad to **board GND**;
- switch board GND through the documented 2N3904 circuit; do not add another
  direct board-GND-to-Pi-GND connection;
- adjust the MT3608 output to **5.0 V and verify it with a multimeter before
  connecting the Raspberry Pi**.

The exact physical pin numbers, transistor orientation and tested limitations
are in the [MY018 wiring and setup guide](docs/MY018-SETUP.md). Disconnect USB
and the battery before changing the wiring. This battery-powered arrangement
is the current prototype, not a certified power-supply design.

### Power boards used in the prototype

![TP4056 charger/protection board and MT3608 step-up converter used in the prototype](docs/power-boards-tp4056-mt3608.jpeg)

The upper board is the adjustable **MT3608 step-up converter**. Its input comes
from the TP4056 output; adjust its output to a measured **5.0 V before** it is
connected to physical Pi pins 2 and 9. The lower board is the USB-C **TP4056
charger/protection board** used with the single 18650 cell. The cell connects
to B+ and B− and the protected OUT+ and OUT− feed the MT3608. Board variants
exist, so always follow the markings printed on the actual board rather than
its position in this photograph.

### MY018 infrared board

![Front and back of the Ming Yuan MY018 infrared board](docs/my018-module-product-photo.jpg)

This product photograph shows the front and back of the MY018 module family.
The rear silkscreen identifies VCC, TXD, RXD and GND and the front shows the
A/B/C solder bridges. Compare the markings with your own module before making
changes. For this build the three original bridges are removed; each centre pad
gets its own GPIO connection and 10 kΩ pull-down as described above. Image
source: [MY018 product listing](https://www.ebay.com/itm/306204181304).

## Prototype enclosure files

The repository includes printable
[bottom and lid STL files](hardware/enclosure/README.md). Treat them as a rough
prototype or starting point: they were made around the current hand-built
assembly and the fit is tight. Space is provided for the MY018 board, but its
dimensions are not quite right; hot glue is the pragmatic mounting solution.
Check clearances and modify the models for your own parts before printing; the
enclosure is not part of the tested installation path.

## Tested setup

- Raspberry Pi 3 Model B Rev 1.2
- MY018 with the modified A/B/C selector wiring and 2N3904 power-control circuit
- Psion 5mx direct PPP over infrared at 57600 bit/s
- Psion 5mx Hayes dial-up/BBS sessions
- Palm IIIc direct PPP over infrared at 57600 bit/s
- MY018 Palm Beam (IrOBEX) sending to Palm at 57600 bit/s
- Windows XP dial-up internet (`5559000`) and BBS over infrared
- Windows 98 dial-up BBS session
- Prolific USB-to-RS-232 for wired PPP and Hayes/BBS connections
- MA-620 infrared fallback (`0df7:0620`) at 9600 bit/s

See the [MY018 wiring and setup guide](docs/MY018-SETUP.md) before connecting
the module. These results apply to the existing working setup. The remaining
major publication check is reproducing the installation from a clean SD card
and then repeating the physical connection tests.

## Status

The verified internet route is working end to end:

`Psion 5mx / Palm IIIc -> IrDA -> MY018 -> Raspberry Pi -> Wi-Fi -> internet`

For computers without an infrared port:

`Retro computer -> RS-232 cable -> Prolific USB adapter -> Raspberry Pi -> internet / BBS`

The web interface, access-point fallback and selectable PPP/Hayes backends are
operational. Generic serial file transfer uses X/Y/ZMODEM. Native device
beaming is deliberately separated by protocol: Psion EikonIr is experimental,
Palm IrOBEX sending is verified, Windows IrOBEX remains untested, and HP raw HPSIR requires a
different backend. See `docs/PROTOCOL-AUDIT.md` for the evidence and support
matrix.

Retro-device Wi-Fi setup is available at **http://wifi.retromodem/** over PPP:
current connection, explicit scan, network selection and password entry in small
cookie-free HTML forms. See [retro Wi-Fi setup](docs/RETRO-WIFI.md).

The optional ChatGPT BBS on `5559999` uses Sign in with ChatGPT, starts a fresh
conversation for every call, and can use OpenAI web search. OAuth credentials
are stored locally with owner-only permissions; the BBS has no local system
tools or device-control permissions.

## Initial installation (in development)

Follow the [clean-SD installation guide](docs/INSTALL.md) for the installation
command, GitHub download route and adapter selection. The bootstrap script
fetches one exact pinned commit. It preserves the SSH account created through
Raspberry Pi Imager and does not create another account with a fixed password.

The installer is intended for a clean **Raspberry Pi OS Legacy Bookworm
(32-bit) Lite** installation. Do not select the regular 32-bit image in
Raspberry Pi Imager: that image now uses a newer Debian release. The installer
deliberately stops unless the system is Debian 12/Bookworm. It builds the IrDA
stack removed from the Linux kernel as DKMS modules, installs the PPP server
and enables IPv4 routing through nftables.

```sh
sudo sh install.sh
```

Prefer the MY018 build documented in the
[wiring and configuration guide](docs/MY018-SETUP.md). Select MY018 in the
installer and confirm the documented wiring. The installer selects 57.6 kbit/s,
configures the PL011 UART and disables Bluetooth and the serial login console.
Reboot the Pi before testing the modem connection. Use the Prolific RS-232 path
for computers without infrared; MA-620 is the alternative USB infrared path.

Verify the installation with:

```sh
sudo retromodem-diagnose
sudo retromodem-verify
```

`retromodem-verify` checks dependencies, installed files, checksums, services,
the web interface, routing and the default phone book. An installation is not
considered reproducible until the physical tests in
[docs/CLEAN-INSTALL-ACCEPTANCE.md](docs/CLEAN-INSTALL-ACCEPTANCE.md) have also
passed on a clean second SD card.

The upstream IrDA source is pinned to commit
`6c7ef8c17360dfe049e6315e9291583a6dcaf52a` from
[`cschramm/irda`](https://github.com/cschramm/irda). This allows compatibility
testing before a working driver is replaced by an update.

After installation the web interface is available at
`http://retromodem.local`. Both the username and default password are
`retromodem`. If no saved Wi-Fi network is available, the Pi creates access
point `retromodem` with password `12345678` after about ten seconds. A failed
Wi-Fi connection automatically falls back to that access point. These
credentials apply to the web interface; SSH uses your own Imager account.

In addition to the selected modem mode, the front LEDs indicate network and
power state. The selected P or D LED flashes for at least three seconds during
a mode change, and longer if necessary while starting, then remains on when the
modem is ready. Both LEDs flash slowly while searching for Wi-Fi; P and D flash
alternately in hotspot mode. Two short simultaneous flashes followed by a
pause warn of current undervoltage; the Raspberry Pi red PWR LED may also go
out or flash.

The current web interface includes status information, Wi-Fi configuration,
modem and adapter settings, a phone book, guides and file transfer. Only paths
marked as verified in the compatibility matrix should be treated as stable.

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for all default addresses, Wi-Fi
details and logins on one page.

## License

GPL-3.0-or-later.
