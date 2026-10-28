# RetroModem protocol- en implementatie-audit

Laatst bijgewerkt: 25 oktober 2026.

## Ontwerpgrens

RetroModem is geen Psion-emulator. De kern selecteert twee onafhankelijke
eigenschappen:

1. transport: IrDA/IrCOMM of een echte seriële adapter;
2. dienst: directe PPP, Hayes-modem/tcpser of een bestandsoverdrachtsprotocol.

Merkgebonden bestandsoverdracht hoort in een aparte protocolbackend. Een
succesvolle PPP-route bewijst daarom niet dat EPOC EikonIr, Palm Beam, Windows
Wireless Link of HP HPSIR werkt.

## Ondersteuningsmatrix

| Route | Protocol | Huidige status | Bewijs |
|---|---|---|---|
| MA-620 naar internet | IrCOMM + PPP | Geverifieerd op 9600 bit/s | Psion 5mx en Palm IIIc met Palm OS 4.1 maken verbinding; Palm vereist de normale PPP-herstarttijd van 3 seconden |
| Windows XP inbelinternet via IR | IrCOMM + Hayes/tcpser + PPP | Fysiek geverifieerd | Windows XP belt via het infraroodmodem naar `5559000`; gebruiker `user`, leeg wachtwoord en automatische IP/DNS werken |
| USB-serieel naar internet | Serieel + PPP | Backend geverifieerd | Proces-, apparaat- en hersteltest; fysieke clienttest blijft apparaatafhankelijk |
| MA-620/USB-serieel naar BBS | IrCOMM/serieel + tcpser | Backend geverifieerd | AT/ATDT en BBS-sessie getest; tcpser upstream ondersteunt phonebookregels |
| Terminalbestandsoverdracht | X/Y/ZMODEM via seriële stroom | YMODEM met Psion Comms geverifieerd | Met een tweede Psion 5mx fysiek in beide richtingen geslaagd |
| Psion ingebouwde IR-ontvangst | EPOC EikonIr/TinyTP | Geverifieerd, apparaatafhankelijk | Met een tweede Psion 5mx snel en betrouwbaar; de eerste 5mx blijft onbetrouwbaar |
| Psion ingebouwde IR-verzending | EPOC EikonIr/TinyTP | Geverifieerd, apparaatafhankelijk | Met een tweede Psion 5mx werkend; de eerste 5mx vertoont uitval |
| Palm Beam naar Palm | IrOBEX | Geverifieerd | `irobex_palm3` stuurde EudoraWeb 2.1 volledig naar een Palm IIIc met Palm OS 4.1 |
| Palm Beam vanaf Palm | IrOBEX | Geverifieerd | Een memo kwam als tekstbestand binnen en een PRC als applicatiebestand |
| Windows Wireless Link | IrOBEX | Geïmplementeerd, niet fysiek getest | Microsoft documenteert de IrDA OBEX PUT/CONNECT-route |
| HP 200LX infrarood | raw HPSIR | Niet ondersteund | Vereist een backend buiten IrLAP/IrLMP/IrCOMM |

## Bevindingen uit broncode en documentatie

### IrDA en EPOC

De MA-620 wordt door de actuele out-of-tree Linux-IrDA-stack ondersteund via
`pl2303`, `irtty-sir` en `ma600-sir`. De driver beschrijft de MA-620 expliciet
als de USB-versie van de MA-600. De fysieke link is op dit exemplaar alleen op
9600 bit/s geverifieerd.

Een controletest met een tweede Psion 5mx op exact dezelfde Pi, MA-620 en
softwareconfiguratie verliep anders dan met het eerste testapparaat: de native
EPOC-overdracht werkte snel en YMODEM via Comms werkte in beide richtingen. De
eerste mislukte poging met dit tweede apparaat bleek waarschijnlijk slechte
uitlijning van de infraroodpoorten. Daarmee zijn een algemeen defect in de
RetroModem-backend en een fundamentele incompatibiliteit van de MA-620
uitgesloten. De hieronder beschreven FRMR-uitval is reproduceerbare informatie
over de combinatie met de eerste 5mx, niet langer een algemene eigenschap van
de EPOC- of YMODEM-backend. Goede uitlijning en de toestand van de IR-hardware
van het retroapparaat zijn onderdeel van de fysieke acceptatietest.

`irpsion5` is experimentele software uit 1999. Het maakt rechtstreeks een
TinyTP-verbinding met `Epoc32:EikonIr:v1.0`; het gebruikt dus niet IrCOMM.

De terugkerende 95%-melding heeft daarnaast een concrete verklaring op
applicatieniveau. De ongewijzigde `irda-utils 0.9.18`-bron negeert bewust de
door `IRTTP_MAX_SDU_SIZE` gerapporteerde waarde, gebruikt altijd logische
blokken van 2044 bytes en bevat de waarschuwing dat een Psion bij kleinere
buffers niet lijkt te herkennen dat het om kortere frames gaat. Het apparaat
stopt dan na het aantal frames dat het op basis van de volledige MTU verwacht.
RetroModem was hiervan afgeweken door de onderhandelde MTU van 253 bytes als
lees- en schrijfblok te gebruiken. Dat past exact bij het verschijnsel dat
Linux alle bytes denkt te hebben geschreven terwijl de Psion nog op 80-95%
staat. Het is echter niet de enige fout: een gecontroleerde herstelproef met
logische blokken van 2044 bytes verloor de onderliggende verbinding al rond
30%. De blokgrootte verklaart dus het reproduceerbare onvolledige einde, maar
herstelt de daarnaast gemeten IrLAP/FRMR-uitval niet vanzelf. De live sender is
daarom niet blijvend op die mislukte proef blijven staan.

De grens van 253 bytes is rechtstreeks te verklaren uit de actuele
Linux-IrDA-bron. `SOCK_STREAM` schakelt TinyTP-SAR uit en `irda_sendmsg()` kapt
een write af op de door IrLAP onderhandelde segmentgrootte. Bij 9600 bit/s
geeft de officiële QoS-tabel slechts 400 bytes lijncapaciteit; daardoor wordt
een 256-byte IrLAP-frame en 253 bytes applicatiedata gekozen. Bij 57.600 bit/s
is de lijncapaciteit 2360 bytes en past het historische frame van 2044 bytes
wel. RetroModem begrenst IrDA echter op 9600 omdat deze MA-620-route daar als
enige betrouwbaar PPP levert.

Dit is fysiek gecontroleerd met twee identieke pogingen waarbij alleen voor
EPOC tijdelijk 57.600 werd toegestaan en de originele 2044-bytewrites werden
hersteld. In beide gevallen vond discovery dezelfde `Symbian EPOC`, maar
`connect()` eindigde direct daarna met `No route to host`: de snelheidswissel
kwam niet tot stand. Op 9600 accepteerde dezelfde originele write exact 253
van 2044 bytes. De 95%-uitval is daarmee geen willekeurige webinterfacefout:
de betrouwbare fysieke snelheid en de door de historische EikonIr-client
vereiste blokgrootte zijn op deze adaptercombinatie onderling onverenigbaar.
Na de proeven zijn de 9600-instelling, de gedeeltelijk werkende kleine-buffer-
sender en PPP automatisch hersteld.

Op de actuele verbinding onderhandelt IrLAP feitelijk al de conservatiefste
waarden: 64 bytes datagrootte en window 1. Dit gebeurt ondanks de hogere
sysctl-maxima. De online aanbevolen workarounds `max_tx_window=1` en een
kleinere `max_tx_data_size` zijn daarmee voor deze sessie al effectief, naast
het feit dat beide eerder afzonderlijk fysiek zijn getest. De in RetroModem
vastgezette commit van `cschramm/irda` is bovendien op 6 oktober 2026 identiek
aan de actuele upstream-hoofdbranch; er is geen niet-geïnstalleerde nieuwere
driverfix.

Drie `irdadump`-traces van hetzelfde bestand tonen dat het probleem een laag
lager begint. Met de standaard IrLAP-windowwaarde 7 kwamen 12 FRMR-responses
voor in 135 uitgaande dataframes; de sessie eindigde op 30.107 van 98.700
bytes. Met `max_tx_window=1` kwamen nog steeds 14 FRMR-responses voor in 236
uitgaande dataframes. De kernel herstelde meerdere IrLAP-resets transparant,
waarna de sessie op 54.395 bytes zonder nieuwe TinyTP-credits bleef staan. Een
derde proef met `max_tx_data_size=128` was aantoonbaar slechter: al bij 18,6%
waren 13 FRMR-responses en 166 uitgaande dataframes zichtbaar, gevolgd door
opnieuw een sessie zonder nieuwe TinyTP-credits. De standaardwaarden 2042 en 7
zijn daarom hersteld; de historische generieke aanbeveling om kleinere frames
te gebruiken geldt niet voor deze combinatie van MA-620 en Psion 5mx.

Een daaropvolgende, ongewijzigde baselinetest stuurde 8.192 bytes volledig in
15 seconden. De eerstvolgende test van 16.384 bytes verloor de verbinding na
8.855 bytes. Een exacte herhaling van dezelfde 8.192 bytes en checksum verloor
de verbinding al na 3.795 bytes. Dit is dus geen harde bestandsgroottelimiet
maar een stochastisch linkprobleem: zelfs 8 KiB is niet reproduceerbaar
betrouwbaar. USB-runtime-autosuspend is op de geteste Pi uitgesloten
(`power/control=on`, `runtime_status=active`).

De FRMR-responses volgen steeds op de hertransmissie van een al verstuurd
I-frame. Volgens IrLAP 1.1 past dit bij een ongeldig N(R)-volgnummer: de Psion
heeft het oorspronkelijke frame kennelijk ontvangen, terwijl Linux geen geldig
antwoord zag en hetzelfde volgnummer opnieuw verstuurt. Dit gebeurt ook bij
kleine besturingsframes en is dus niet uitsluitend een probleem met grote
datapakketten. De geïnstalleerde `irtty-sir`/`ma600-sir`-code is vrijwel de
Linux 4.15-implementatie met alleen compatibiliteitsupdates voor moderne
kernels; upstream bevat geen bekende correctie voor deze MA-620/PL2303-
turnaroundroute. Kunstmatige applicatievertraging en automatische volledige
overdrachtsretry blijven uitgesloten: ze herstellen een verloren IrLAP-
bevestiging niet en kunnen op het doelapparaat een gedeeltelijk of dubbel
bestand achterlaten.

Een gerichte controle van de historische Linux-IrDA-aanbevelingen leverde geen
nog ontbrekende generieke timingcorrectie op. De documentatie adviseert bij
snelle USB-routes minimaal 1 ms zendomkeertijd, maar `ma600-sir` adverteert zelf
al 10 ms (`min_turn_time.bits = 0x01`). De actieve algemene ondergrens van 10
microseconden verlaagt die adapterspecifieke eis niet. Ook het online verhogen
van `min_tx_turn_time` naar 1 ms zou deze verbinding daarom feitelijk niet
veranderen. De andere gedocumenteerde noodmaatregel, `max_tx_window=1`, is al
fysiek getest en bleek niet stabieler. Opvallend is bovendien dat de historische
kernelconfiguratie de MA-600-driver aanvankelijk alleen als getest voor IrCOMM
beschreef en ondersteuning van de MA-620 via zijn PL2303 USB-serieelomzetter
slechts als *should also support* aanduididt. Dat verklaart waarom werkende
IrCOMM/PPP geen bewijs is voor betrouwbare EikonIr/TinyTP-bestandsoverdracht.

Bronnen:

- <https://github.com/cschramm/irda>
- <https://manpages.debian.org/stretch/irda-utils/irpsion5.8.en.html>
- <https://legacy.redhat.com/pub/redhat/linux/7.1/en/doc/HOWTOS/other-formats/html/Infrared-HOWTO/x2179.html>
- <https://actisys.com/Documents/1IR8200PSpec-v0.6-031217.pdf>
- <https://irda.sourceforge.net/docs/advanced.html>
- <https://sparcher.blogspot.com/2016/11/howto-some-experience-with-usb-irda.html>
- <https://sourceforge.net/p/irda/mailman/irda-users/thread/1153784288.6094.47.camel%40finnest/>
- <https://android.googlesource.com/kernel/msm/+/7bc30c23c8ace3821a6732bfbe7e8f1b0995a63e/net/irda/qos.c>

### PPP

`pppd` draait rechtstreeks op het geselecteerde apparaat. Voor IrDA is dat
`/dev/ircomm0` zonder hardware-flow-control; voor USB-serieel is het de via USB
ID gevonden tty met RTS/CTS. `passive`, `silent`, `persist`, LCP/IPCP-retries en
LCP-echo's zijn gedocumenteerde pppd-opties. IPv4-forwarding en nftables-NAT
vormen de netwerkbrug; dit staat los van het gebruikte retroapparaat.

Een live trace met het Psion-profiel **Infrarode mobiele telefoon** liet zien
dat EPOC tijdens IPCP twee WINS-adressen met waarde `0.0.0.0` aanvraagt. Zonder
`ms-wins` antwoordt `pppd` met `ConfRej`, waarna EPOC de volledige LCP/IPCP-
onderhandeling meerdere keren herstart. RetroModem biedt daarom tweemaal
`ms-wins 192.168.77.1` aan. Dit dient alleen om IPCP meteen te laten
convergeren; webbrowsen en hostnaamresolutie blijven DNS gebruiken.

Bron: <https://man7.org/linux/man-pages/man8/pppd.8.html>

### Hayes-modem en inbel-PPP

tcpser emuleert Hayes-commando's en ondersteunt telefoonboekregels met `-n`.
Nummer `5559000` wijst naar een uitsluitend lokaal luisterende xinetd-dienst
die `pppd notty` rechtstreeks op de ruwe TCP-socket uitvoert. Een telnetlaag is
hier bewust niet gebruikt: de NVT-onderhandeling kan PPP blokkeren voordat LCP
begint. De installer levert tcpser, xinetd, de configuratie voor poort 2323 en
de mode/tcpser-units. tcpser is vastgezet op upstream 1.1.4 commit
`234ccfde0bb6a874c353c0cdca0fa0ca76c5cca3`.

Bronnen:

- <https://github.com/go4retro/tcpser>
- <https://dyn.manpages.debian.org/bookworm/xinetd/xinetd.8.en.html>
- <https://manpages.debian.org/bookworm/inetutils-telnetd/index.html>

### Bestandsoverdracht

XMODEM gebruikt `sx`/`rx`, YMODEM `sb`/`rb` en ZMODEM `sz`/`rz`. Deze
protocollen verwachten een transparante seriële byteverbinding en zijn daarom
transportneutraal: ze kunnen over IrCOMM of USB-serieel lopen wanneer het
retroapparaat een overeenkomstig terminalprogramma heeft.

Palm OS Exchange Manager gebruikt IrOBEX. Windows Wireless Link gebruikt
eveneens IrDA OBEX. Die functies mogen niet als gewone terminaltransfer worden
voorgesteld en krijgen later een OpenOBEX-backend.

Bronnen:

- <https://man.archlinux.org/man/lrzsz-rz.1.en>
- <https://palm.wiki/development/docs/601/PalmOSCompanion2/Beaming.html>
- <https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-irda/425b3085-3fcc-4a46-ac07-9f2e92afbaa9>

### Wi-Fi fallback

NetworkManager `ipv4.method shared` levert DHCP, DNS-forwarding en NAT voor het
setup-accesspoint. AP-modus, 2,4-GHz-band, vast kanaal en uitgeschakelde
wifi-powersave zijn gedocumenteerde profielopties. De fallback-loop mag een al
actief AP niet opnieuw activeren; dat veroorzaakte eerder periodieke
disconnects en is gecorrigeerd.

Bron: <https://www.networkmanager.dev/docs/api/latest/nm-settings-nmcli.html>

## Testbeleid

- Een servicestatus is geen protocoltest.
- De automatische regressietest bewijst exclusiviteit, juist apparaat,
  modewissel en herstel na afbreken.
- Een protocol krijgt pas status **geverifieerd** na een fysieke end-to-endtest.
- Experimentele routes mogen de PPP/Hayes-backend nooit blijvend bezet houden.
- Elke driver- of protocolwijziging krijgt eerst een trace, een rollback en een
  herhaalbare acceptatietest.
