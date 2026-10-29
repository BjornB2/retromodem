# Clean-install verification

Use this checklist after installing RetroModem on Raspberry Pi OS Legacy
Bookworm 32-bit Lite. The installer preserves the SSH account configured in
Raspberry Pi Imager.

## Automated verification

After the required reboot, run:

```sh
sudo retromodem-verify
```

A successful installation reports **0 errors**. Warnings about optional
hardware that is not connected are allowed.

For a more invasive internal switching test, with the relevant adapters
connected, run:

```sh
sudo /usr/local/lib/retromodem/selftest
```

This temporarily switches between PPP, Hayes dial-up, IrDA and USB serial and
then restores the original configuration.

## Network and recovery

- Without a known Wi-Fi network, access point `retromodem` appears with the
  initial password `12345678`.
- `http://10.42.0.1/` opens administration while connected to that access
  point; the initial login is `retromodem` / `retromodem`.
- After joining Wi-Fi and rebooting, administration is available at
  `http://retromodem.local/`.
- If the saved Wi-Fi network becomes unavailable, the fallback access point
  should return automatically.

Change the initial passwords after installation.

## Data preservation

The default phone book includes internet PPP number `5559000` and BBS numbers
starting at `5551000`. Phone-book changes, uploaded files and selected settings
must remain after a reboot and after running the installer again.

## Useful connection checks

- Psion 5mx, direct PPP via IrDA: a local page loads.
- Palm IIIc, direct PPP via IrDA: a local page loads.
- From a terminal, `AT` returns `OK` in Hayes mode.
- `ATDT5559000` starts internet PPP.
- A configured virtual BBS number opens its Telnet-backed BBS connection.
- Direct PPP receives an IP address and RetroModem DNS.
- YMODEM through Psion Comms preserves the original file name.
- Cancelling a file transfer restores the selected modem mode.

The experimental Psion EikonIr transfer route is device- and adapter-dependent
and is not treated as a stable interface.
