# Install RetroModem on a clean SD card

The supported base system is Raspberry Pi OS Legacy Bookworm 32-bit Lite on a
Raspberry Pi 3 Model B.

## Prepare the Pi

After installation and reboot, open `http://start.retromodem/` from the connected
retro browser. Search and ChatGPT are at the top; Settings links to
`http://setup.retromodem/`. Wi-Fi can be configured from the retro device at
`http://wifi.retromodem/`, without internet access. Use RetroModem DNS
`192.168.77.1` over direct PPP or dial-up PPP (`5559000`).

1. Flash **Raspberry Pi OS Legacy Bookworm (32-bit) Lite** with Raspberry Pi Imager.
2. Set your own SSH username, password/key, Wi-Fi and locale in Imager.
3. Boot the Pi and connect over SSH using that account.
4. The bootstrap resolves `main` once to a full commit SHA, then downloads that
   immutable revision. Record the displayed SHA in the test report. You can
   still explicitly select a full SHA with `--ref` for repeat tests.

## Single-command installation

For the preferred MY018 build, paste this into the SSH session as your own
Imager user. It resolves the current release and asks for the documented
MY018 wiring confirmation before installation:

```sh
curl -fsSL https://raw.githubusercontent.com/BjornB2/retromodem/main/bootstrap.sh | sh
```

The installer includes all three connection options and asks which one should be
active first; MY018 is the suggested choice. To preselect the main RS-232 route,
append `--adapter serial`; for the MA-620 infrared fallback append `--adapter ma620`.

After installation, continue at **Reboot and verify** below.

## Choose the connection

**MY018 is the preferred infrared build.** For the modified A/B/C selector and
2N3904 transistor circuit described in [MY018-SETUP.md](MY018-SETUP.md):

```bash
curl -fsSL https://raw.githubusercontent.com/BjornB2/retromodem/main/bootstrap.sh | sh -s -- --adapter my018
```

The installer asks you to confirm the documented hardware before enabling the
MY018 power-control GPIOs. For an unattended installation after checking that
circuit, add `--my018-wiring-confirmed --non-interactive`.

**Prolific USB-to-RS-232** is the main route for computers without infrared.
Use a real RS-232 adapter and the cable/null-modem arrangement required by the
computer, rather than a USB-TTL lead:

```bash
curl -fsSL https://raw.githubusercontent.com/BjornB2/retromodem/main/bootstrap.sh | sh -s -- --adapter serial
```

**MA-620 is the USB infrared fallback:**

```bash
curl -fsSL https://raw.githubusercontent.com/BjornB2/retromodem/main/bootstrap.sh | sh -s -- --adapter ma620
```

To inspect the complete source without installing anything, use a new directory:

```bash
curl -fsSL https://raw.githubusercontent.com/BjornB2/retromodem/main/bootstrap.sh | \
  sh -s -- --download-only "$HOME/retromodem-test-source"
```

## Reboot and verify

Follow the installer's reboot instructions. MY018 UART/boot configuration needs
a reboot before the first connection test.

```sh
sudo reboot
```

Reconnect using your own SSH account, then run:

```sh
sudo retromodem-diagnose
sudo retromodem-verify
```

The command must finish with zero errors. The selected adapter and source
commit are included in the output. See
[CLEAN-INSTALL-ACCEPTANCE.md](CLEAN-INSTALL-ACCEPTANCE.md) for additional
verification and recovery checks.

## Download integrity

The bootstrap can download a pinned commit without a token while the repository
is public. Both the script URL and source revision above point to the same commit.
HTTPS plus a pinned Git commit identifies the requested source revision; the
bootstrap does not claim an independently verified release-archive checksum.
