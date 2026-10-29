# Proxy instellen vanaf het retroapparaat / Retro-device proxy settings

## Nederlands

Open `http://start.retromodem/` → **Instellingen** → **Webproxy**, of direct
`http://proxy.retromodem/`. Dit werkt na direct PPP of inbel-PPP via `5559000`,
zonder browserproxy of via de ingebouwde proxy. Gebruik DNS `192.168.77.1`.

- **Paginagrootte per deel:** HTML plus geschatte uitgepakte afbeeldingen na
  conversie, niet de downloadgrootte. Bij afbeeldingen als links telt alleen HTML.
  Een kleiner budget is veiliger bij weinig geheugen; 250 kB is de standaard voor
  nieuwe installaties. De instelling garandeert geen maximale geheugenbelasting.
- **Afbeeldingen bij nieuwe verbinding:** laten zien, als links of vorige keuze.
  Dit geldt bij de volgende PPP-verbinding. De weergave van de huidige verbinding
  verander je bovenaan een geopende proxypagina.
- **Afbeeldingsformaat:** kies een apparaatpreset, of **Huidig / aangepast** met
  breedte en hoogte van 16–4096 pixels. Presets worden bij opslaan toegepast;
  JavaScript is niet nodig. De ingevulde afmetingen gelden alleen bij Aangepast.

Kies **Opslaan** en open de oorspronkelijke website opnieuw voor nieuwe delen en
afbeeldingsformaten. Deze instellingen zijn gedeeld met de beheerinterface en
gelden ook voor andere clients. Er worden geen services herstart. Routering,
uitzonderingen, wifi en modeminstellingen worden hier niet gewijzigd.

De pagina gebruikt eenvoudige HTML zonder cookies, CSS of JavaScript en volgt
de taalkeuze. Alleen de lokale retro-PPP-peer of een gebruiker met beheerderslogin
kan wijzigen. Een formulier verloopt na vijftien minuten: open het dan opnieuw.
De eerste installatie vereist de volledige installer voor het nieuwe DNS-adres.

## English

Open `http://start.retromodem/` → **Settings** → **Webproxy**, or open
`http://proxy.retromodem/` directly. Use direct PPP or dial-up PPP (`5559000`),
with DNS `192.168.77.1`. A browser proxy is not required for local pages;
the built-in proxy also relays them.

- **Page size per part:** estimates HTML plus decoded images after conversion,
  not download size. With images as links, only HTML counts. Smaller budgets are
  safer on low-memory devices. New installations default to 250 kB; this is not
  a guaranteed memory ceiling.
- **Images at new connection:** show images, links or remember the previous
  choice. Applies at the next PPP connection. Change the current connection's
  image view at the top of an open proxy page.
- **Image size:** choose a device preset or **Current / custom**, with width and
  height between 16 and 4096 pixels. Presets are applied on save, without
  JavaScript. Entered dimensions apply only when Custom is selected.

Choose **Save**, then reopen the original website for new parts and image sizes.
These settings are shared with administration and other clients. No services
are restarted. Routing, exceptions, Wi-Fi and modem settings are unchanged.

The page follows the language setting and uses simple HTML without cookies,
CSS or JavaScript. Changes require the local retro PPP peer or administrator
authentication. Forms expire after fifteen minutes; reopen the page if needed.
The first installation requires the full installer for the new DNS alias.
