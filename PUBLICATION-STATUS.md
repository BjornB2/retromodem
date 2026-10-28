# Publication preparation

This is the private preparation repository for the first RetroModem release.
It was temporarily public for installation testing and is private again.
It is not a stable release. Snapshot date: 2026-10-28.
The development selection contains 109 source files,
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
All 240 Python unit tests pass on the development computer; installer,
bootstrap and verifier shell syntax checks also pass.
The DKMS inventory now follows target-kernel capabilities; unsupported ISA/PCI
drivers are not required on the Pi. Full clean-SD acceptance remains pending.
The modem discovery helper now uses the bundled legacy IrDA header directory.
Installer C commands are checked for header resolution as part of the tests.

Feature updates were applied on the original Pi through the guarded installer,
with backups and unchanged configuration, ChatGPT credentials and PPP process.
Live HTTP checks cover NOS images, snapshot view switching, localized compact
controls and page choices up to 2,000 kB. The size estimates HTML plus decoded
image pixels, not download bytes. Tweakers main-content selection and duplicate
nested articles are fixed; upstream consent pages can still prevent a fetch.
See docs/FEATURE-UPDATES.md. Physical browser memory acceptance and a new
clean-SD run remain required.

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

The repository remains private; updates do not authorize making it public.
Final release
checks, including license documentation and physical acceptance, remain pending.
