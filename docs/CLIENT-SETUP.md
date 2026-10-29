# Configure a Psion 5mx or Palm for RetroModem

This guide describes the client-side settings for a direct PPP connection to
RetroModem. The original setup was documented in
[How to connect your Psion or Palm PDA to the internet](https://www.bjornsblog.nl/general/how-to-connect-your-psion-to-the-internet-in-2024/);
the addresses and RetroModem-specific details below reflect the current build.

## Psion 5mx

1. Open **Tools → Remote Link** and set Remote Link to **Off**. It otherwise
   occupies the serial/infrared connection.
2. Open **Control panel → Dialing** and open or create a location once. The
   defaults are normally sufficient, but EPOC may report that connection
   information is missing until a location has been opened.
3. Under **Modems**, create a modem with these settings:

| Tab | Setting |
| --- | --- |
| Modem | 115200 baud; Serial; Auto |
| Options | Leave the defaults |
| Initializing | Init string `AT` |
| Advanced | Hardware (RTS/CTS); Terminal detect off; Carrier detect off; Fixed line |

4. Under **Internet/Network**, create a service and select **Direct**.
5. Disable manual login, enter username `user` and leave the password empty.
6. Enable **Get IP address from server** and **Get DNS address from server**.
7. Under Advanced, enable only **Accept plain text authentication**.

The direct PPP service does not dial a phone number. To use Hayes dial-up
internet or a BBS instead, select RetroModem's dial-up mode and use a terminal
application such as Hermes. Dial internet PPP with `ATDT5559000`, a configured
BBS with its phone-book number, or the ChatGPT BBS with `ATDT5559999`.

## Palm OS

Open **Prefs → Connection**, create a connection and configure it as follows:

| Setting | Value |
| --- | --- |
| Connect to | PC |
| Via | Serial for a cable, or Infrared for MY018/MA-620 |
| Speed | 115200 bit/s virtual port speed |
| Flow control | Automatic |

Then open **Prefs → Network**, create a service and select the connection above:

| Setting | Value |
| --- | --- |
| Username | empty |
| Password | Prompt, then submit an empty password |
| Connection type | PPP |
| Idle timeout | Never |
| Query DNS | enabled |
| IP address | Automatic |
| Script | a single `End` line |

If automatic addressing fails, disable **Query DNS** and **IP Address
Automatic**, then use:

| Setting | Address |
| --- | --- |
| Palm IP address | `192.168.77.2` |
| Primary DNS | `192.168.77.1` |
| Secondary DNS | `192.168.77.1` |

Use RetroModem as DNS so names such as `start.retromodem`,
`search.retromodem` and `chatgpt.retromodem` resolve correctly. Disconnect and
reconnect PPP after changing these values.

## Local pages

Once PPP is connected, open:

- `http://start.retromodem/` — search, ChatGPT and links to settings;
- `http://setup.retromodem/` — configuration pages for the retro client;
- `http://wifi.retromodem/` — scan and configure Wi-Fi without another device;
- `http://proxy.retromodem/` — page-size and image settings for RetroWEB.

Modern HTTPS sites can be simplified by RetroModem's built-in RetroWEB proxy.
In manual mode configure HTTP proxy `192.168.77.1`, port `8080`; automatic mode
does not require a browser proxy setting.

Original configuration research:
[Björns Blog](https://www.bjornsblog.nl/general/my-take-on-a-retro-proxy/).
