# Clean-SD installation test

This is the test procedure for `BjornB2/retromodem`, temporarily public for testing.
Use a clean second SD card in the Pi 3B. Keep the working SD card as your
reference. The installer is prepared for Raspberry Pi OS Legacy Bookworm
32-bit Lite; physical clean-install acceptance is still required.

## Prepare the Pi

1. Flash **Raspberry Pi OS Legacy Bookworm (32-bit) Lite** with Raspberry Pi Imager.
2. Set your own SSH username, password/key, Wi-Fi and locale in Imager.
3. Boot the Pi and connect over SSH using that account.
4. Use the pinned candidate below, or select a full 40-character commit SHA.
   Use the same commit for both the bootstrap and its source download. Record
   that SHA in the test report; do not use a moving branch such as `main`.

## Single-command installation (no GitHub login)

> **Test version:** clean-SD acceptance is in progress. Keep the working card
> available. No stable release date is guaranteed.

For the preferred MY018 build, paste this into the SSH session as your own
Imager user. It downloads the pinned candidate and asks for the documented
MY018 wiring confirmation before installation:

```sh
curl -fsSL https://raw.githubusercontent.com/BjornB2/retromodem/f332397ad3445528b915a1d1f516f054f4982ab5/bootstrap.sh | sh -s -- --ref f332397ad3445528b915a1d1f516f054f4982ab5
```

The installer includes all three connection options and asks which one should be
active first; MY018 is the suggested choice. To preselect the main RS-232 route,
append `--adapter serial`; for the MA-620 infrared fallback append `--adapter ma620`.

After installation, continue at **Reboot and verify** below. The following
authentication procedure is only needed if the repository is made private again.

## Download when the repository is private

Private GitHub files require authentication. Make a temporary fine-grained
GitHub token with **Contents: read-only** access to only `BjornB2/retromodem`.
Enter it into the Pi's Bash session with a hidden prompt. The token value does
not appear in the command history:

```bash
read -r -p 'Full tested commit SHA: ' RETROMODEM_REF
read -r -s -p 'Temporary GitHub read token: ' RETROMODEM_GITHUB_TOKEN
printf '\n'
export RETROMODEM_GITHUB_TOKEN
```

Fetch the bootstrap through GitHub's API. The authorization header is supplied
over stdin rather than as a command-line argument or token-bearing URL:

```bash
RETROMODEM_BOOTSTRAP=$(mktemp /tmp/retromodem-bootstrap.XXXXXX)
if [[ "$RETROMODEM_REF" =~ ^[0-9a-fA-F]{40}$ ]] &&
   [[ "$RETROMODEM_GITHUB_TOKEN" =~ ^[A-Za-z0-9_]+$ ]]; then
  printf 'header = "Authorization: Bearer %s"\n' "$RETROMODEM_GITHUB_TOKEN" |
    env -u RETROMODEM_GITHUB_TOKEN curl -q --config - --fail --silent --show-error \
      --proto '=https' --output "$RETROMODEM_BOOTSTRAP" \
      "https://api.github.com/repos/BjornB2/retromodem/contents/bootstrap.sh?ref=$RETROMODEM_REF" \
      --header 'Accept: application/vnd.github.raw+json'
else
  printf 'Invalid commit SHA or token format\n' >&2
fi
```

Check that the download succeeded before proceeding. Review the script:

```bash
less "$RETROMODEM_BOOTSTRAP"
```

Download and validate the pinned sources as the SSH user; the bootstrap invokes
`sudo` only when it starts the installer. It removes GitHub token variables from
the installer's environment. Your interactive shell still holds its token until
you unset it below.

## Choose the connection

**MY018 is the preferred infrared build.** For the modified A/B/C selector and
2N3904 transistor circuit described in [MY018-SETUP.md](MY018-SETUP.md):

```bash
sh "$RETROMODEM_BOOTSTRAP" --ref "$RETROMODEM_REF" --adapter my018
```

The installer asks you to confirm the documented hardware before enabling the
MY018 power-control GPIOs. For an unattended installation after checking that
circuit, add `--my018-wiring-confirmed --non-interactive`.

**Prolific USB-to-RS-232** is the main route for computers without infrared.
Use a real RS-232 adapter and the cable/null-modem arrangement required by the
computer, rather than a USB-TTL lead:

```bash
sh "$RETROMODEM_BOOTSTRAP" --ref "$RETROMODEM_REF" --adapter serial
```

**MA-620 is the USB infrared fallback:**

```bash
sh "$RETROMODEM_BOOTSTRAP" --ref "$RETROMODEM_REF" --adapter ma620
```

To inspect the complete source without installing anything, use a new directory:

```bash
sh "$RETROMODEM_BOOTSTRAP" --ref "$RETROMODEM_REF" --download-only "$HOME/retromodem-test-source"
```

After the download/install finishes:

```bash
unset RETROMODEM_GITHUB_TOKEN
rm "$RETROMODEM_BOOTSTRAP"
```

Revoke the temporary token after testing. No GitHub token is needed by RetroModem
at runtime, and none should be put into the distributable image.

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

Record the selected adapter and source commit, then follow
[CLEAN-INSTALL-ACCEPTANCE.md](CLEAN-INSTALL-ACCEPTANCE.md) for the physical tests.
Installer and image acceptance are separate checks; no downloadable image is
provided yet.

## Download integrity

The bootstrap can download a pinned commit without a token while the repository
is public. Both the script URL and source revision above point to the same commit.
HTTPS plus a pinned Git commit identifies the requested source revision; the
bootstrap does not claim an independently verified release-archive checksum.
