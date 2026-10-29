# Wifi instellen vanaf het retroapparaat

Je kunt deze pagina ook bereiken via `http://start.retromodem/` →
**Instellingen** (`http://setup.retromodem/`) → **Wi-Fi**.

Open **http://wifi.retromodem/** via de lokale PPP-verbinding met RetroModem.
Internet is daarvoor niet nodig. Dit werkt zowel zonder browserproxy als via
de ingebouwde handmatige of automatische proxy.

De eerste pagina toont de huidige wifi-verbinding. Een actieve noodhotspot
wordt apart vermeld en telt niet als externe wifi-verbinding. Een aangesloten
wifi-netwerk is op zichzelf geen bewijs dat internet werkt.

1. Kies **Scan netwerken**.
2. Selecteer het netwerk en vul het wachtwoord in. Laat dit leeg bij open wifi.
3. Kies **Verbinden** en daarna **Status controleren**.

De pagina gebruikt kleine HTML 2.0-formulieren zonder JavaScript, CSS of cookies.
De teksten volgen de ingestelde taal. De retro-PPP-verbinding wordt bij een
wifiwissel niet herstart. De Pi-radio kan niet tegelijk hotspot en client zijn;
de hotspot verdwijnt daarom tijdens een overstap naar externe wifi. Bij een
mislukte poging wordt de vorige verbinding of de noodhotspot hersteld waar mogelijk.
Een scan die de radio niet ondersteunt geeft een fout; er wordt niet stilzwijgend
een werkende verbinding voor verbroken.

Ondersteund: open wifi en WPA/WPA2 Personal. Enterprise, WEP en WPA3-only worden
niet aangeboden als ondersteunde verbinding. Verborgen netwerken staan niet in
de scanlijst. Netwerknamen worden server-side bewaard zodat oude browsers hun
bijzondere tekens of voor-/achterliggende spaties niet wijzigen.

Toegang zonder beheerderslogin is beperkt tot de lokale retro-PPP-peer. Een
gewone LAN-client mag niet op basis van alleen de hostnaam wifi wijzigen.
Formulieren hebben tijdelijke, client- en actiegebonden tokens. Wachtwoorden
gaan alleen via POST; ze staan niet in URL, antwoordpagina of procesargumenten.
**Lokale HTTP is niet versleuteld.** NetworkManager bewaart de gekozen gegevens
in een afgeschermd profiel op de Pi voor toekomstige verbindingen.

Deze eerste versie vereist eenmaal de **volledige installer**, omdat ook de
lokale DNS-regel wordt toegevoegd. Een feature-only update weigert deze eerste
overgang wanneer die DNS-regel ontbreekt; latere webupdates nemen beide modules mee.

Lokale tests simuleren succes, fout wachtwoord/herstel, gelijktijdige acties en
onderbroken taken. Een echte wissel naar een ander netwerk en automatisch
herverbinden moeten nog met een door de gebruiker gekozen testnetwerk worden
gecontroleerd; tijdens uitrol wordt de bestaande wifi niet als proef vervangen.
