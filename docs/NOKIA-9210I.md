# Nokia 9210i via IrDA verbinden met RetroModem

Deze fysiek geteste route geeft een Nokia 9210i internet via RetroModem:

`Nokia 9210i -> IrDA/IrCOMM -> Hayes-modem -> PPP -> internet`

De werkende combinatie is **eInternet 1.10F**, **Standard Hayes modem**,
**57600 bit/s** en inbelnummer `5559000`.

## eInternet downloaden en installeren

Download uitsluitend
[Extended Internet 1.10F (ZIP)](https://my9210.bs0dd.net/Arch/Apps/Network/eInternet/Extended%20Internet%20v1%5B1%5D.10f.zip)
uit het onafhankelijke
[Nokia 9210-softwarearchief](https://my9210.bs0dd.net/index.php?lang=eng&page=cfil&dir=Apps/Network/eInternet).
Het ZIP-bestand bevat `eInternet 1.10F.sis`, `Link.SIS` en een meegeleverde
handleiding die uitlegt hoe de app wordt geïnstalleerd en geregistreerd. Volg
voor de registratie die handleiding en de licentievoorwaarden van de
oorspronkelijke software. De inhoud is software van derden en maakt geen deel
uit van RetroModem; bewaar een lokale kopie omdat de archieflink kan veranderen.

1. Pak het ZIP-bestand uit op een Windows XP-computer.
2. Lees eerst de meegeleverde installatie- en registratiehandleiding.
3. Activeer infrarood op de Nokia en leg de IrDA-poorten tegenover elkaar.
4. Stuur `eInternet 1.10F.sis` met Windows **Verzenden naar →
   Infraroodontvanger**. Dit werkt buiten Nokia PC Suite om; de precieze naam
   van de Windows-opdracht kan verschillen.
5. Accepteer het bestand op de Nokia, open het ontvangen SIS-bestand en bevestig
   de installatie. Het interne geheugen volstaat; een MMC-kaart is niet nodig.
6. Voer daarna de installatie- en registratiestappen uit de meegeleverde
   handleiding uit, waaronder `Link.SIS` wanneer die procedure dat voorschrijft.

Nokia PC Suite mag geïnstalleerd zijn, maar is voor het beamen niet nodig. De
geslaagde overdracht bevestigt dat Windows XP en de Nokia onderling IrOBEX
kunnen gebruiken.

## RetroModem voorbereiden

1. Open `http://retromodem.local`.
2. Selecteer de aangesloten MY018- of MA-620-infraroodadapter.
3. Kies **Hayes-inbelmodem/BBS**, niet Direct PPP.
4. Controleer dat `5559000` naar de lokale PPP-dienst wijst.
5. Richt beide IrDA-vensters zonder obstakels op elkaar.

## eInternet instellen

Selecteer het ingebouwde profiel **Standard Hayes modem**. Maak geen eigen
modemprofiel: de tijdens de test aangemaakte modem stopte na `ATH` met
*Telefoon uitgeschakeld of niet gereed* of een onbekende fout. Het standaard
Hayes-profiel doorliep de initialisatie wel.

| Instelling | Waarde |
| --- | --- |
| Modemprofiel | **Standard Hayes modem** |
| Verbinding | Infrarood / IrDA |
| Snelheid | **57600 bit/s (57k6)** |
| Fax class | Automatisch |
| Resetstring | `ATZ` |
| Telefoonnummer | `5559000` |
| Gebruikersnaam | `user` |
| Wachtwoord | leeg |
| IP-adres | automatisch van server |
| DNS-adres | automatisch van server |

57k6 is onderdeel van de geteste combinatie. Kies niet zonder reden 115200
bit/s wanneer 57600 betrouwbaar werkt.

## Verbinden

Activeer infrarood op de Nokia, plaats beide poorten tegenover elkaar en laat
eInternet via het standaard Hayes-modem `5559000` bellen. Open na het opbouwen
van PPP bijvoorbeeld `http://start.retromodem/`.

## Problemen oplossen

### Telefoon uitgeschakeld of niet gereed

Als RetroModem alleen `ATH` ontvangt, `OK` terugstuurt en de Nokia daarna DTR
laag maakt, stopt eInternet vóór de initialisatie. Controleer **Standard Hayes
modem** en 57600 bit/s. Schakel infrarood eenmaal uit en weer aan of verbreek de
zichtlijn vijf seconden om een oude IrCOMM-sessie op te ruimen.

### Onbekende fout bij fax class

eInternet stuurt onder andere `AT+FCLASS=?` en `AT+FCLASS=0`. RetroModem
antwoordt daarop als data-only modem met class `0`. Deze compatibiliteit zit in
de meegeleverde tcpser-patch. Werk een oudere installatie bij als deze
opdrachten nog `ERROR` geven.

### D-led blijft knipperen

De D-led knippert tijdens activiteit. Blijft hij na een afgebroken poging
knipperen, verbreek dan kort de IrDA-zichtlijn, activeer infrarood opnieuw en
probeer nogmaals.

## Bekende beperking: bestanden via RetroModem

Windows XP kon buiten Nokia PC Suite om rechtstreeks een bestand naar de Nokia
9210i beamen. Dezelfde overdracht via RetroModems huidige Windows-IrOBEX-pad
werkte niet. Waarschijnlijk is die implementatie nog niet volledig compatibel
met de Nokia. Dit staat los van IrCOMM/PPP: internet via eInternet en het
standaard Hayes-modem werkt wel. IrOBEX wordt later apart onderzocht.
