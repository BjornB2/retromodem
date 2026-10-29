# Publication preparation

This is the preparation repository for the first RetroModem release.
It is private again at the owner's request after successful update testing.
It is not a stable release. Snapshot date: 2026-10-29.
The development selection contains 120 source files,
plus repository metadata. The publication branch now also contains the
bootstrap, adapter configuration helper and their tests.

## Scope

- Raspberry Pi 3B with Raspberry Pi OS Legacy Bookworm 32-bit Lite.
- MY018 GPIO/UART infrared as the preferred build.
- MA-620 USB infrared and Prolific USB-to-RS-232 in the same release.
- Installer and a clean Raspberry Pi OS image from the same release sources.
- Compact image with automatic expansion on first boot; size must be measured.
  The selected Legacy OS reports 5.2 GB, so 4 GB is not promised.
- Other Pi models are untested; further model testing is not required for release.

## Current validation

The publication installer has offline tests for adapter selection, boot changes,
configuration preservation and authenticated bootstrap downloads. Selected
source files passed checksum and basic secret-pattern checks. These results do
not establish clean-install, kernel-build or physical hardware acceptance.
All 299 Python unit tests pass on the development computer; installer,
bootstrap and verifier shell syntax checks also pass.
Retro Wi-Fi setup at wifi.retromodem adds cookie-free localized HTML forms,
current uplink/AP status, explicit scanning and asynchronous connection status.
It has PPP/admin peer gating, action-specific CSRF, serialized NetworkManager
operations and root-only persistent profiles. Full installation is required
once for the DNS alias. See docs/RETRO-WIFI.md for scope and acceptance limits.
Installed on the original Pi via the full installer on 2026-10-29 and rebooted.
Live checks passed for current connected status, direct/proxied HTML and real
scans (four networks after reboot), local DNS, unauthorized/forged-peer rejection
and invalid connect selections. The active Wi-Fi UUID remained unchanged.
NetworkManager accepted the generated credential profile in offline parsing.
A real switch and saved-credential reconnection are not yet physically tested.
The DKMS inventory now follows target-kernel capabilities; unsupported ISA/PCI
drivers are not required on the Pi. Full clean-SD acceptance remains pending.
The modem discovery helper now uses the bundled legacy IrDA header directory.
The full installer also patches tcpser flow-control handling: software flags
belong to c_iflag, not c_cflag, where IXOFF overlaps the extended baud bit on
Linux. Live diagnosis found a requested 115200 port reporting 75. A C regression
checks baud preservation, but the patched modem still needs physical testing.
The web-only feature updater does not rebuild tcpser; use the full installer.
The IrCOMM search watchdog now retries the cached discovery log every three
seconds after unsuccessful setup. Normal discovery only notifies new peers;
the upstream disabled retry could leave a visible peer indefinitely in SEARCH.
The patch is part of the DKMS version hash. A C regression checks retry and
timer cancellation on synchronous completion. Physical acceptance is pending.
Search/recovery waits are now one second instead of three: initial search,
search retry and the return to search after failed query/setup or disconnect.
The three-second deadlines for an in-flight IAS query or setup are unchanged,
as are discovery frequency, slots and hardware power-cycle timing. The extra
timer patch is also included in the DKMS source hash.

The full installer with both modem fixes and the shorter search waits was
applied to the original Pi and rebooted successfully. The loaded driver version
was verified. The owner subsequently confirmed that PPP-to-dial-up switching
and AT response felt fast and accepted this for now. No exact post-update
connection duration was measured; do not claim a numerical speedup.
Installer C commands are checked for header resolution as part of the tests.

Feature updates were applied on the original Pi through the guarded installer,
with backups and unchanged configuration, ChatGPT credentials and PPP process.
Live HTTP checks cover NOS images, snapshot view switching, localized compact
controls and page choices up to 2,000 kB. The size estimates HTML plus decoded
image pixels, not download bytes. Tweakers main-content selection and duplicate
nested articles are fixed; upstream consent pages can still prevent a fetch.
See docs/FEATURE-UPDATES.md. Physical browser memory acceptance and a new
clean-SD run remain required.

The next clean-SD candidate also contains the byte-safe snapshot encoding fix,
search descriptions and cached next/previous results, corrected public-IP image
validation, explicit HTTP-origin recovery for legacy TLS-incompatible sites,
source-error handling and bounded 429 backoff. Live Pi checks passed for McGST
image conversion, Foldsoc, Wikiwand/Wikipedia recovery and search credits.
The browser fallback is not included: isolated local Chromium tests still got
Cloudflare challenges on Psionex, including after JavaScript waiting. Cloudflare
pages remain an explicit unresolved limitation. No external reader service is
used. Do not describe the next installation candidate as universal web access.

## Outstanding before release

- Clean-SD validation of the bootstrap, adapter selection, MY018 UART/boot
  setup, preserved Imager SSH account and adapter-aware verifier now implemented.
- Final web/access-point password policy (test defaults remain documented).
- Versioned updates, data preservation and recovery procedure.
- Exact OS baseline and clean image build.
- Updated wiring, serial RS-232/null-modem and usage guides.
- License texts, third-party notices and corresponding-source provisions.
- Clean-SD acceptance for installer and image on the Pi 3B.

EudoraWeb and MochaTelnet are included at the project owner's request. They are
third-party software and are not relicensed under this project's GPL notice.
Redistribution terms and guide-image provenance still need recording.

The personal SD backup, local administration files, credentials, logs and
development caches are not included. Do not add device-state backups here.

The owner confirmed the latest updates worked and requested private visibility.
Do not make the repository public without renewed authorization.
Final release
checks, including license documentation and physical acceptance, remain pending.
