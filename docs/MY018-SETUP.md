# MY018: automatische linksnelheid met transistorschakeling

Deze optie is uitsluitend voor de aangepaste en geteste Pi 3/MY018-opstelling.
Een ongewijzigde module blijft op 9600 met de soldeerbruggen A0/B0/C0.
Een algemene IrDA-snelheidslimiet van 57k6 bestaat niet; de bevindingen hieronder
gelden voor onze combinatie van module, aansturing, voeding en retroapparaten.

## Bewezen resultaten

| Maximum | Bevinding |
| --- | --- |
| 9600 | Werkende basis voor PPP en Palm Beam |
| 19200 | Beam gestart; volledige overdracht niet geverifieerd |
| 38400 | Nog niet getest |
| 57600 | PPP met Palm IIIc/OS 4.1 en Psion 5mx; volledige Beam naar Palm |
| 115200 | Experimenteel; Palm Beam kon niet verbinden, Psion PPP niet bevestigd |

MochaTelnet (79.026 bytes) is op 57k6 volledig overgedragen in 23,910 seconden:
3,305 kB/s of 26,44 kbit/s nuttige bestandsdata, inclusief verbinden. Dit is geen
meting van de optische baudrate en geen uitgebreide stabiliteitscertificering.
Ontvangen vanaf Palm op 57k6 en EPOC/X/YMODEM op de nieuwe module zijn niet opnieuw
geverifieerd. De algemene handleidingen behouden daarvoor hun eerdere beperkingen.

## Aansluitingen (fysiek pinnummer versus BCM)

Voeding volledig los, inclusief accu, tijdens aanpassen. Pin 4 van het IC wordt
niet gebruikt. IC-identiteit en schema van MY018 zijn niet bevestigd.

| Functie | Fysieke Pi-pin | BCM / details |
| --- | --- | --- |
| Board VCC | 1 | vaste 3,3 V; nooit rechtstreeks uit een GPIO voeden |
| Board TXD | 8 | BCM14 / Pi TX; op dit board host-perspectief, niet kruisen |
| Board RXD | 10 | BCM15 / Pi RX |
| A middenpad | 11 | BCM17, via 1 kΩ |
| B middenpad | 13 | BCM27, via 1 kΩ |
| C middenpad | 15 | BCM22, via 1 kΩ |
| 2N3904 basis | 22 | BCM25, via 1 kΩ; oude R6/resetdraad verwijderen |
| 2N3904 emitter | 6 | echte Pi-GND |
| 2N3904 collector | — | board-GND, zonder andere rechtstreekse Pi-GND-verbinding |

Met de platte tekstkant van deze 2N3904 naar je toe en pootjes omlaag:
links emitter, midden basis, rechts collector. Elk A/B/C-middenpad heeft een eigen
10 kΩ-pulldown naar **board-GND**. Verwijder eerst de A/B/C-soldeerbruggen. De
middenpads blijven onderling gescheiden. Houd rekening met LED-gronden op fysieke
14 en 20 en de knop op fysieke 36 / BCM16. Een HDMI-afscherming is niet onze
meetreferentie. De transistor heeft geen bewezen stroommarge onder alle
zendomstandigheden; onvoldoende voeding kan de betrouwbaarheid beïnvloeden.

## Software

Gebruik de meegeleverde driverbron en helper. Zet alleen voor deze bedrading in
`/etc/retromodem/retromodem.env`:

```
RETROMODEM_MY018_POWER_CYCLE=1
RETROMODEM_MY018_BITRATE=57600
RETROMODEM_IRDA_BITRATE=57600
```

De publieke testinstaller doet dit bij `--adapter my018` na bevestiging van de
bedrading. Hij stelt tevens `enable_uart=1` en `dtoverlay=disable-bt` in, schakelt
`hciuart` en de UART-loginconsole uit en bewaart de oorspronkelijke bootbestanden
als `.pre-retromodem`. Bluetooth is daardoor niet beschikbaar bij deze opbouw.
Een herstart is vereist voordat de PL011-UART als `/dev/serial0` gebruikt wordt.
Zie [INSTALL.md](INSTALL.md) voor de volledige schone-SD-procedure.

De installer neemt de gewijzigde irtty-sir-bron mee in DKMS en installeert de
helper. Bij deze expliciete opt-in wordt ook de modprobe-optie geïnstalleerd en
de bootconfig uitgebreid met `include retromodem-my018.txt`. Die bootconfig zet
BCM25 vroeg hoog, zodat de transistor board-GND verbindt, en laat A/B/C als
ingangen zonder interne pulls. De boot-/power-cycle-test van de publieke
installer op een schone SD-kaart hoort bij de releaseacceptatie.

Bij iedere nieuwe IrDA-attachment reset de voorbereiding de module naar 9600.
Bij een snelheidswissel geeft de driver eerst UART en A/B/C vrij, schakelt de
transistor uit, wacht 100 ms, zet alleen de gewenste hoge bits, schakelt in,
wacht 50 ms en herstelt de UART. Lage bits worden door de board-pulldowns bepaald:
GPIO-uitgangen laag zouden bij afgeschakelde massa een alternatieve stroomroute
kunnen vormen. De uitvoering gebeurt in de slaapbare IrDA-thread, vóór de
UART-termioswisseling. Dit is experimentele laagzijdige voeding, geen generieke
oplossing voor willekeurige andere boards of GPIO-toewijzingen.

## Gebruik

Kies bij Modem de MY018 en het gewenste maximum. De instelling wordt per adapter
bewaard; opslaan verbreekt de huidige verbinding. Nieuwe ontdekking begint op
9600; de verbinding onderhandelt daarna tot het ingestelde maximum. De
verbinding-/modempoortsnelheid van het retroapparaat is niet op zichzelf bewijs
van de fysieke snelheid. Beam gebruikt niet noodzakelijk het PPP-profiel.
Start met 57k6 of herstel 9600 bij problemen. Remote Link op de Psion blijft uit.

De bestaande MY018-opstelling werkt; de publieke installer wordt nog op een
schone SD-kaart geaccepteerd, inclusief herstart. Bewaar toegang tot de SD-kaart.
Na een kernelupdate moet de driver opnieuw compatibel gebouwd en geverifieerd worden.

Bronnen voor het ontwerp (niet voor bevestiging van het MY018-IC):

- [Microchip AN756: BAUD-pinnen worden bij reset ingelezen](https://www.microchip.com/content/dam/mchp/documents/APID/ApplicationNotes/ApplicationNotes/00756a.pdf)
- [Raspberry Pi boot-GPIO-configuratie](https://www.raspberrypi.com/documentation/computers/config_txt.html#gpio-control)
- [2N3904 datasheet](https://www.onsemi.com/pdf/datasheet/2n3904-d.pdf)
