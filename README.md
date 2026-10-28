# RetroModem

> **Test version — not yet released.** The installer and SD image are being
> prepared for clean-install testing on a Raspberry Pi 3B. A stable release
> will follow after the acceptance tests pass. There is no public bootstrap
> installation command or downloadable SD image yet.
>
> Release scope: MY018 is the preferred infrared build; MA-620 USB infrared and
> Prolific USB-to-RS-232 are included alternatives. Other Raspberry Pi models
> have not been tested. Some documentation below still describes older defaults
> and is being updated. See [PUBLICATION-STATUS.md](PUBLICATION-STATUS.md).

**Network bridge and virtual modem for retro computers and handhelds**

RetroModem turns a Raspberry Pi into a standalone internet bridge and Hayes
modem for vintage handhelds and computers. Devices can connect through a
supported IrDA/IrCOMM adapter or a USB-to-serial adapter. PPP traffic is routed
through the Pi's Wi-Fi network; Hayes dialing can open internet PPP or a BBS.

The project is hardware-independent. Adapter-specific details live in hardware
profiles; the web interface, PPP service and network management remain shared.

## Confirmed hardware

- Raspberry Pi 3 Model B Rev 1.2
- Mobile Action MA-620 (`0df7:0620`), using `pl2303`, `irtty-sir` and
  `ma600-sir`
- Psion 5mx and Palm IIIc direct PPP over IrCOMM, stable at 9600 bit/s
- Palm Beam (IrOBEX) sending of PRC/PDB files

## Status

The verified internet route is working end to end:

`Psion 5mx -> IrDA -> MA-620 -> PPP -> Raspberry Pi -> Wi-Fi -> internet`

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

De installer is bedoeld voor een schone **Raspberry Pi OS Legacy Bookworm
(32-bit) Lite**-installatie. Kies in Raspberry Pi Imager niet de gewone
32-bit image: die gebruikt inmiddels een nieuwere Debian-versie. De installer
stopt bewust wanneer het systeem niet Debian 12/Bookworm is. Hij bouwt de uit
de Linux-kernel verwijderde IrDA-stack als DKMS-
modules, installeert de PPP-server en zet IPv4-routing met nftables aan.

```sh
sudo ./install.sh
```

Sluit de MA-620 aan en controleer de installatie met:

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
