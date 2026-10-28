# RetroModem

> **Test version — not yet released.** The installer and SD image are being
> prepared for clean-install testing on a Raspberry Pi 3B. A stable release
> will follow after the acceptance tests pass. This repository is temporarily
> public for installation testing; there is no downloadable SD image yet.
>
> MY018 is the preferred infrared build. MA-620 is the USB infrared fallback;
> Prolific USB-to-RS-232 is the main connection for computers without infrared.
> Other Raspberry Pi models have not been tested.
> See [PUBLICATION-STATUS.md](PUBLICATION-STATUS.md) for remaining preparation.

**Network bridge and virtual modem for retro computers and handhelds**

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

## Tested setup

- Raspberry Pi 3 Model B Rev 1.2
- MY018 with the modified A/B/C selector wiring and 2N3904 power-control circuit
- MY018 direct PPP at 57600 bit/s with Psion 5mx and Palm IIIc
- MY018 Palm Beam (IrOBEX) sending to Palm at 57600 bit/s
- Prolific USB-to-RS-232 for wired PPP and Hayes/BBS connections
- MA-620 infrared fallback (`0df7:0620`) at 9600 bit/s

See the [MY018 wiring and setup guide](docs/MY018-SETUP.md) before connecting
the module. These results apply to the existing working setup; reproducing it
from a clean SD card is the next acceptance step.

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

The optional ChatGPT BBS on `5559999` uses Sign in with ChatGPT, starts a fresh
conversation for every call, and can use OpenAI web search. OAuth credentials
are stored locally with owner-only permissions; the BBS has no local system
tools or device-control permissions.

## Eerste installatie (in ontwikkeling)

Volg de [schone-SD-installatiehandleiding](docs/INSTALL.md) voor het installatiecommando
zonder GitHub-login en de adapterkeuze. Het bootstrap-script haalt één exact
vastgelegde commit op. Je bestaande SSH-account uit Raspberry Pi Imager blijft
behouden; er wordt geen extra account met een vast SSH-wachtwoord aangemaakt.

De installer is bedoeld voor een schone **Raspberry Pi OS Legacy Bookworm
(32-bit) Lite**-installatie. Kies in Raspberry Pi Imager niet de gewone
32-bit image: die gebruikt inmiddels een nieuwere Debian-versie. De installer
stopt bewust wanneer het systeem niet Debian 12/Bookworm is. Hij bouwt de uit
de Linux-kernel verwijderde IrDA-stack als DKMS-
modules, installeert de PPP-server en zet IPv4-routing met nftables aan.

```sh
sudo sh install.sh
```

Gebruik bij voorkeur de MY018-opbouw uit de
[aansluit- en configuratiehandleiding](docs/MY018-SETUP.md). Kies in de
installer de MY018 en bevestig de gedocumenteerde bedrading. De installer stelt
57k6 in, configureert de PL011-UART en schakelt daarvoor Bluetooth en de seriële
console uit. Herstart daarna de Pi voordat je de modemverbinding test.
Gebruik voor computers zonder infrarood de Prolific RS-232-route. MA-620 is
alleen de alternatieve USB-infraroodroute.

Controleer daarna de installatie met:

```sh
sudo retromodem-diagnose
sudo retromodem-verify
```

`retromodem-verify` controleert afhankelijkheden, geïnstalleerde bestanden,
checksums, services, webinterface, routing en het standaardtelefoonboek. Een
installatie geldt pas als reproduceerbaar nadat ook de fysieke tests uit
[docs/CLEAN-INSTALL-ACCEPTANCE.md](docs/CLEAN-INSTALL-ACCEPTANCE.md) op een
schone tweede SD-kaart zijn uitgevoerd.

De upstream IrDA-bron staat vast op commit
`6c7ef8c17360dfe049e6315e9291583a6dcaf52a` van
[`cschramm/irda`](https://github.com/cschramm/irda). Zo kan een update eerst
apart op compatibiliteit worden getest voordat de werkende driver vervangen
wordt.

Na installatie is de webinterface bereikbaar op `http://retromodem.local`. De
gebruikersnaam en het standaardwachtwoord zijn beide `retromodem`. Als geen
opgeslagen wifi-netwerk beschikbaar is, maakt de Pi na ongeveer tien
seconden accesspoint `retromodem` met wachtwoord `12345678`. Een mislukte
wifi-koppeling schakelt automatisch terug naar dat accesspoint.
Deze logins gelden voor de webinterface; SSH gebruikt je eigen Imager-account.

De front-leds geven naast de gekozen modemstand ook de netwerk- en
voedingsstatus aan: de gekozen P- of D-led knippert bij een moduswissel ten
minste drie seconden en zo nodig langer tijdens het starten, en
brandt continu zodra de modem gereed is,
beide leds knipperen langzaam tijdens het zoeken naar wifi, en P/D knipperen
om en om in hotspotmodus. Twee korte gelijktijdige flitsen met een pauze
waarschuwen voor actuele onderspanning; de rode PWR-led van de Raspberry Pi
kan daarbij eveneens uitgaan of knipperen.

De huidige webinterface bevat statusinformatie, wifi-configuratie, modem- en
adapterinstellingen, een telefoonboek, handleidingen en bestandsoverdracht.
Alleen routes die in de compatibiliteitsmatrix als geverifieerd staan mogen als
stabiel worden beschouwd.

Zie [docs/QUICKSTART.md](docs/QUICKSTART.md) voor alle standaardadressen,
wifi-gegevens en logins op één pagina.

## License

GPL-3.0-or-later.
