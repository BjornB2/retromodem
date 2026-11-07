# RetroWEB proxy settings

RetroModem uses the public HTTP proxy at `retroweb.bjrno.com:8081`. It no
longer contains a local RetroWEB content processor.

Choose a mode under **Settings → Web proxy**:

- **Manual:** configure `retroweb.bjrno.com`, port `8081`, as the HTTP proxy in
  the retro browser. Leave authentication empty.
- **Automatic:** leave browser proxy settings disabled. RetroModem redirects
  HTTP requests over the PPP link to the public proxy automatically.

The exception list applies only to Automatic mode. Matching domains and their
subdomains connect directly and are not processed by RetroWEB.

Open `http://retroweb.bjrno.com/` as a search engine or to enter a web address
in either mode. The public proxy requires internet access and must not be used
for passwords, accounts, payments or other sensitive information.

The local pages that remain are `start.retromodem`, `setup.retromodem`,
`wifi.retromodem` and `chatgpt.retromodem`. The former `proxy.retromodem` and
`search.retromodem` pages have been removed.
