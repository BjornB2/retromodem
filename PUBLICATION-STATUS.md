# Publication preparation

This is the preparation repository for the first RetroModem release, temporarily
public for single-command installation testing. It is not a stable release.
Snapshot date: 2026-10-28. It contains 92 selected development-source files,
plus repository metadata. The publication branch now also contains the
bootstrap, adapter configuration helper and their tests.

## Scope

- Raspberry Pi 3B with Raspberry Pi OS Legacy Bookworm 32-bit Lite.
- MY018 GPIO/UART infrared as the preferred build.
- MA-620 USB infrared and Prolific USB-to-RS-232 in the same release.
- Installer and a clean Raspberry Pi OS image from the same release sources.
- Approximately 4 GB uncompressed image target, subject to measured size, with
  automatic expansion on first boot.
- Other Pi models are untested; further model testing is not required for release.

## Current validation

The publication installer has offline tests for adapter selection, boot changes,
configuration preservation and authenticated bootstrap downloads. Selected
source files passed checksum and basic secret-pattern checks. These results do
not establish clean-install, kernel-build or physical hardware acceptance.
All 115 Python unit tests pass on the development computer; installer,
bootstrap and verifier shell syntax checks also pass.

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

The owner authorized temporary public access for clean-SD installation testing.
The tracked Git history was checked before changing visibility. Final release
checks, including license documentation and physical acceptance, remain pending.
