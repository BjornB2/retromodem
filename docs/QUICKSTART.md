# RetroModem quickstart

## Lokale pagina's op je retroapparaat

Open `http://start.retromodem/` na het verbinden via PPP (direct of via
inbellen op `5559000`). Bovenaan staan Zoeken en ChatGPT met hun functie.
De link **Instellingen** opent `http://setup.retromodem/`; daar vind je de
beschikbare instellingen voor je retroapparaat. Beide pagina's werken zonder
JavaScript en volgen de ingestelde taal.

Wi-Fi kun je ook vanaf het aangesloten apparaat instellen via
`http://wifi.retromodem/`: bekijk je huidige verbinding, scan netwerken en kies
een netwerk met wachtwoord. Internet is hiervoor niet nodig. Gebruik RetroModem
als DNS-server (`192.168.77.1`), ook bij dial-up internet. De lokale pagina's
werken zonder browserproxy en via de ingebouwde proxy. Voor ChatGPT moet je
eerst je account koppelen in de beheerinterface; zoeken en chat vereisen internet.



## Standaardgegevens

| Functie | Adres of login |
|---|---|
| Nood-accesspoint | `retromodem` |
| Wifi-wachtwoord nood-accesspoint | `12345678` |
| Webinterface | `http://retromodem.local` |
| Webinterface via nood-accesspoint | `http://10.42.0.1` |
| Weblogin | `retromodem` / `retromodem` |
| SSH | je eigen account en wachtwoord/key uit Raspberry Pi Imager |

## Eerste ingebruikname

1. Zet RetroModem aan en wacht ongeveer twintig seconden.
2. Als geen bekend wifi-netwerk beschikbaar is, verschijnt het accesspoint
   `retromodem`. Verbind met wachtwoord `12345678`. Kies op telefoons zo nodig
   expliciet **verbonden blijven**, omdat dit configuratienetwerk aanvankelijk
   geen internettoegang heeft.
3. Open `http://retromodem.local`. Werkt de lokale naam nog niet, open dan
   `http://10.42.0.1`. Log in met `retromodem` / `retromodem`.
4. Open **Wi-Fi**, selecteer het gewone draadloze netwerk en vul het wachtwoord
   in. De pagina is tijdens het overschakelen kort onbereikbaar.
5. Verbind telefoon of laptop weer met het gewone netwerk en open voortaan
   `http://retromodem.local`.
6. Gebruik bij voorkeur **MY018** voor infrarood, **Prolific RS-232** voor
   computers zonder infrarood, of **MA-620** als infraroodfallback.
   Kies onder **Verbinding** de adapter en daarna **Direct internet (PPP)** of
   **Hayes-inbelmodem/BBS**.

## Telefoonboek en inbellen

Open de aparte tab **Telefoonboek** voor alle nummers en om publieke BBS'en toe
te voegen of te wijzigen.

| Nummer | Functie | Aanmelding |
|---|---|---|
| `5559000` | Inbelinternet (PPP) | gebruiker `user`, leeg wachtwoord, IP en DNS automatisch |
| `5551000`–`5551009` | Meegeleverde publieke BBS'en | geen algemene aanmelding; verschilt per BBS |
| `5559999` | ChatGPT BBS | eerst autoriseren via de webinterface |

Zet RetroModem voor deze nummers op **Hayes-inbelmodem/BBS**. Stuur in een
terminal zo nodig eerst `AT`; bel daarna bijvoorbeeld met `ATDT5551000`.
Windows XP-inbelinternet via het door Windows aangemaakte infraroodmodem en
nummer `5559000` is fysiek getest.

Nieuwe installaties gebruiken standaard **115200 bit/s** voor de virtuele
Hayes/Comms-poort. Dit verhoogt de fysieke MY018-linksnelheid niet: die blijft
voor de voorkeursopbouw maximaal **57600 bit/s**. Stel de terminal in op de
virtuele poortsnelheid die op de Modem-pagina staat; bestaande zelf gekozen
instellingen blijven bij een update behouden. Voor RS-232 moet de seriële
poortsnelheid aan beide kanten gelijk zijn.

## Palm: handmatige IP- en DNS-instellingen

Werkt automatische toewijzing op de Palm niet, open dan **Prefs → Network →
Details**. Zet **Query DNS** en **IP Address Automatic** uit en vul in:

| Instelling | Adres |
|---|---|
| Eigen IP-adres van de Palm | `192.168.77.2` |
| Primaire DNS | `192.168.77.1` |
| Secundaire DNS | `192.168.77.1` |

De DNS-server is RetroModem. Gebruik hier geen `1.1.1.1` of `8.8.8.8`, want die
kennen `search.retromodem` en `chatgpt.retromodem` niet. RetroModem zoekt ook
gewone internetadressen op. Verbreek na de wijziging de netwerkverbinding op de
Palm en verbind opnieuw. Open vervolgens **http://search.retromodem** of
**http://chatgpt.retromodem**; daarvoor is geen browserproxy nodig.

## ChatGPT via web en BBS

Open **Instellingen** en kies **Continue with ChatGPT**. Rond de toestemming af
in de OpenAI-pagina. De browser probeert daarna een adres op `127.0.0.1` te
openen; deze pagina mag mislukken. Kopieer de volledige URL uit de adresbalk en
plak hem in het daarvoor bestemde veld in RetroModem.

Open via PPP **http://chatgpt.retromodem**, of kies **Hayes-inbelmodem/BBS** en
bel `5559999`. De webversie werkt zonder JavaScript, cookies of proxyinstelling.
De zoekpagina **http://search.retromodem** en de ChatGPT-pagina volgen de
taalkeuze in de webinterface (Nederlands of Engels). Een wijziging geldt vanaf
de volgende pagina-aanvraag; bestaande gespreksberichten worden niet vertaald.
Standaard begint iedere oproep of nieuw geopende webpagina een nieuw gesprek.
Met **Instellingen → ChatGPT → Gesprek voortzetten in web en BBS** aan hervatten
beide hetzelfde gesprek. **Nieuw gesprek**, `/new`, een reboot of het uitschakelen
van deze optie wist de gedeelde geschiedenis. Een herstart van alleen de web- of
BBS-service bewaart haar. Bij lange gesprekken vervallen de oudste berichten.
Dit deelt geen gesprekken met de gewone ChatGPT-app.
ChatGPT mag actuele informatie op het web zoeken, maar heeft standaard geen
toegang tot RetroModem, lokale bestanden of systeemcommando's.

Optioneel kan **Netwerkagent toestaan** voor web en BBS worden aangezet. ChatGPT kan dan vanaf
de Pi zijn eigen netwerkadres laten bekijken en DNS, ping, poorttests, HTTP/API
en SSH gebruiken voor andere apparaten op
het netwerk. Leesacties lopen direct; voor wijzigende HTTP- of SSH-acties vraagt
de terminal eerst om `ja` of `nee`, of toont de webversie knoppen **Ja** en **Nee**.
De webbevestiging verloopt na drie minuten; zonder toestemming wordt de actie
geweigerd. De agent beheert RetroModem zelf niet.

Vraag bijvoorbeeld **"Scan mijn lokale netwerk en toon de apparaten en open
poorten"**. De agent gebruikt Nmap voor het rechtstreeks aangesloten wifi- of
ethernet-LAN, standaard maximaal een /24 en 19 gangbare TCP-poorten. Je kunt ook
een lokaal IP-adres of kleiner subnet en specifieke poorten opgeven (maximaal
64 poorten). Bij meer dan 64 gevonden apparaten worden alle apparaten vermeld,
maar alleen de eerste 64 op poorten gecontroleerd. Een apparaat dat niet reageert
kan alsnog aanwezig zijn, bijvoorbeeld door wifi-isolatie. De Pi heeft ook
arp-scan, dig/nslookup en traceroute voor diagnose. Buren bekijken en traceroute
zijn eveneens agentacties.

## Knop en leds

- Kort indrukken: wisselt tussen Direct PPP en Hayes-inbelmodem/BBS.
- Drie seconden ingedrukt houden: beide leds knipperen en de Raspberry Pi wordt
  netjes afgesloten. Wacht daarna tot de leds uit zijn voordat je de voeding
  losneemt.
- De PPP-led en dial-up-led tonen welke modemmodus actief is.

## SSH

Op hetzelfde netwerk:

```sh
ssh JOUW_GEBRUIKERSNAAM@retromodem.local
```

Vervang `JOUW_GEBRUIKERSNAAM` door je Imager-account. Via het nood-accesspoint
kan ook `ssh JOUW_GEBRUIKERSNAAM@10.42.0.1` worden gebruikt.
