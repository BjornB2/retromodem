# RetroModem clean-installacceptatie

Deze procedure bewijst of de projectmap een nieuwe RetroModem-installatie kan
reproduceren. De bestaande, werkende SD-kaart blijft tijdens deze test
onaangeraakt.

## Benodigd

- een tweede SD-kaart;
- Raspberry Pi OS **Legacy Bookworm (32-bit) Lite**;
- Raspberry Pi met netwerkaansluiting;
- MY018 met de gedocumenteerde A/B/C- en 2N3904-bedrading (voorkeursopbouw);
- Prolific USB-naar-RS-232 voor computers zonder infrarood;
- MA-620 als alternatieve infraroodadapter;
- Psion 5mx en Palm IIIc voor de fysieke acceptatietests.

Wifi-profielen, ontvangen bestanden en zelf geüploade software zijn
apparaatgegevens en horen niet in de installer. Het basistelefoonboek hoort er
wel in en wordt hieronder expliciet gecontroleerd.

## 1. Installeren

1. Kies in Raspberry Pi Imager **Raspberry Pi OS (other) → Raspberry Pi OS
   Legacy (32-bit) Lite** en flash die image. De gewone 32-bit image is geen
   Bookworm meer en wordt door de installer geweigerd. Een tijdelijk via
   Raspberry Pi Imager ingesteld account mag worden gebruikt om de installer
   te starten; dit blijft daarna ook het SSH-beheerdersaccount.
2. Volg [INSTALL.md](INSTALL.md) om de gepinde testcommit uit de private
   repository te downloaden en kies MY018 als voorkeursopbouw. De bootstrap
   start de installer; uitvoeren vanuit een gedownloade bronmap kan ook:

   ```sh
   sudo sh install.sh --adapter my018 --my018-wiring-confirmed
   sudo reboot
   ```

   Gebruik `--my018-wiring-confirmed` uitsluitend bij de beschreven aangepaste
   bedrading. De installer vraagt interactief om bevestiging als deze vlag ontbreekt.
3. Controleer na herstart eerst MY018. Test daarna de seriële route en de
   MA-620-fallback op dezelfde Pi, met de aanwezige apparatuur.

## 2. Automatische acceptatie

Voer uit:

```sh
sudo retromodem-verify | tee retromodem-clean-install.txt
```

Acceptatiecriterium: **0 fouten**. Een waarschuwing over niet-aangesloten
optionele hardware is toegestaan. Bewaar het tekstbestand als testrapport.

Controleer daarna de interne wisseltests:

```sh
sudo /usr/local/lib/retromodem/selftest
```

Deze test wisselt tijdelijk tussen PPP, Hayes-dial-up, IrDA en USB-serieel en
herstelt daarna automatisch de oorspronkelijke configuratie. Gebruik hem pas
als beide adapters aangesloten zijn; anders zijn hardwaregerelateerde fouten
verwacht.

## 3. Netwerk en herstelgedrag

- Zonder bekend wifi-netwerk verschijnt accesspoint `retromodem` met
  wachtwoord `12345678`.
- `http://10.42.0.1` opent de webinterface met `retromodem` / `retromodem`.
- Voeg via de webinterface een wifi-netwerk toe.
- Na herstart verdwijnt het accesspoint, werkt `http://retromodem.local` en
  blijft de webinterface bereikbaar.
- Verwijder of maak het bekende wifi-netwerk tijdelijk onbereikbaar. Het
  accesspoint moet zelfstandig terugkeren.

## 4. Configuratie en basisdata

- Het telefoonboek bevat `5559000` en de standaard BBS-reeks vanaf `5551000`.
- Voeg tijdelijk een BBS toe en herstart de Pi: de invoer moet blijven staan.
- Voer `sudo sh install.sh` nogmaals uit: het aangepaste telefoonboek en de
  gekozen instellingen mogen niet worden overschreven.
- Een naar een handleiding geüpload bestand moet een herstart en herinstallatie
  eveneens overleven.

## 5. Fysieke acceptatiematrix

Noteer per test datum, apparaat, adapter en uitkomst.

| Test | Verwacht resultaat |
|---|---|
| Psion 5mx, direct PPP via IrDA | HTTP-pagina wordt geladen |
| Palm IIIc, direct PPP via IrDA | HTTP-pagina wordt geladen |
| Windows XP, inbel-PPP via IrDA naar `5559000` | internetverbinding wordt opgebouwd met gebruiker `user` en leeg wachtwoord |
| Psion Comms, `AT` | antwoord `OK` |
| Psion Comms, `ATDT5559000` | internet-PPP wordt gestart |
| Psion Comms, BBS-nummer | BBS opent, zonder dubbele tekens bij local echo uit |
| Palm Beam, PRC naar Palm | bestand wordt geïnstalleerd/ontvangen |
| YMODEM via Comms | bestand komt met oorspronkelijke naam binnen |
| Overdracht annuleren | gekozen modemmodus komt automatisch terug |
| USB-serieel, direct PPP | internetverbinding werkt |
| USB-serieel, Hayes/BBS | `AT` en een BBS-nummer werken |

De experimentele EPOC EikonIr-overdracht is geen blokkade voor een geslaagde
installatieacceptatie: die route is apparaat- en adapterafhankelijk en staat
niet als stabiel aangemerkt.

## 6. Geslaagd

Een release is reproduceerbaar wanneer:

1. `retromodem-verify` nul fouten rapporteert;
2. de relevante wisseltests slagen;
3. de hierboven als stabiel beschreven fysieke routes werken;
4. een tweede uitvoering van de installer gebruikersdata bewaart;
5. alle afwijkingen en hardwarebeperkingen in het testrapport staan.
