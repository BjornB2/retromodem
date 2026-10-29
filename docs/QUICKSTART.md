# RetroModem quick reference

## Default access details

| Function | Address or login |
| --- | --- |
| Emergency access point | `retromodem` |
| Access-point password | `12345678` |
| Administration interface | `http://retromodem.local` |
| Interface through the access point | `http://10.42.0.1` |
| Web login | `retromodem` / `retromodem` |
| SSH | the account and password/key created in Raspberry Pi Imager |

## First use

1. Turn on RetroModem and wait approximately twenty seconds.
2. If no saved Wi-Fi network is available, connect to access point
   `retromodem` with password `12345678`. A phone may need **stay connected**
   to be selected because the configuration network initially has no internet.
3. Open `http://retromodem.local`, or `http://10.42.0.1` if local name
   resolution is not available yet. Log in with `retromodem` / `retromodem`.
4. Open **Wi-Fi**, select the normal wireless network and enter its password.
5. Reconnect the phone or laptop to that normal network and use
   `http://retromodem.local` from then on.
6. Select MY018 for the preferred infrared build, Prolific RS-232 for a wired
   computer, or MA-620 for USB infrared fallback. Then select Direct internet
   (PPP) or Hayes dial-up modem/BBS.

## Pages on the retro device

After establishing direct PPP or dial-up PPP through `5559000`, use RetroModem
DNS `192.168.77.1` and open:

| Address | Function |
| --- | --- |
| `http://start.retromodem/` | Search, ChatGPT and settings links |
| `http://setup.retromodem/` | Client-side settings overview |
| `http://wifi.retromodem/` | Wi-Fi configuration without another device |
| `http://proxy.retromodem/` | Proxy routing, page size and image settings |

These pages work without JavaScript and do not require a browser proxy.

## Phone book and dialing

| Number | Function | Login |
| --- | --- | --- |
| `5559000` | Dial-up internet PPP | username `user`, empty password, automatic IP/DNS |
| `5551000`–`5551009` | Included public BBS entries | depends on the BBS |
| `5559999` | ChatGPT BBS | authorize ChatGPT through the web interface first |

Select **Hayes dial-up modem/BBS**, send `AT` if necessary and dial with a
command such as `ATDT5551000`. New installations use 115200 bit/s for the
virtual Hayes/Comms port. This does not increase the physical MY018 link above
its tested maximum of 57600 bit/s.

The phone book translates these virtual telephone numbers into Telnet BBS
hostnames and ports. The retro computer can keep using its original modem and
terminal workflow even though the remote BBS no longer has a physical dial-up
line. No PSTN call is made: RetroModem answers locally and opens the matching
Telnet connection over the internet.

## Palm addressing fallback

If automatic addressing fails, open **Prefs → Network → Details**, disable
Query DNS and IP Address Automatic, and use:

| Setting | Address |
| --- | --- |
| Palm IP address | `192.168.77.2` |
| Primary DNS | `192.168.77.1` |
| Secondary DNS | `192.168.77.1` |

Reconnect PPP after changing these settings. Do not use a public DNS server if
you want names such as `search.retromodem` and `chatgpt.retromodem` to work.

See [Configure a Psion 5mx or Palm](CLIENT-SETUP.md) for the complete client
settings.

## Button and LEDs

- Short press: switch between Direct PPP and Hayes dial-up/BBS.
- Hold for three seconds: safely shut down the Pi; release when both LEDs flash
  and wait until they turn off before disconnecting power.
- The PPP and dial-up LEDs show the active modem mode and startup/network state.

## SSH

```sh
ssh YOUR_USERNAME@retromodem.local
```

Replace `YOUR_USERNAME` with the account created in Raspberry Pi Imager. When
connected to the emergency access point, use `10.42.0.1` instead.
