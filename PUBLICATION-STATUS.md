# Publication status

RetroModem 1.0 is publicly released. The clean-SD installer completed on a
Raspberry Pi 3 Model B and `retromodem-verify` reported zero errors on
2026-10-29.

The release includes:

- MY018 GPIO/UART infrared support for the documented modified wiring;
- MA-620 USB infrared and Prolific USB-to-RS-232 connection options;
- direct PPP and Hayes-compatible dial-up/BBS modes;
- RetroWEB, local administration and retro-device configuration pages;
- file-transfer support and the documented hardware/enclosure files.

Installation starts from Raspberry Pi OS Legacy Bookworm 32-bit Lite. The
project does not distribute a prebuilt SD-card image. Hardware constraints and
protocol-specific limitations remain documented in the README and protocol
audit.

Device configuration, credentials, logs, received files and local backups are
not part of the repository.
