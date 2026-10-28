# Publication preparation

This is the private preparation repository for the first RetroModem release.
Snapshot date: 2026-10-28. It contains 92 selected development-source files,
plus repository metadata and the test-status banner in README.md.

## Scope

- Raspberry Pi 3B with Raspberry Pi OS Legacy Bookworm 32-bit Lite.
- MY018 GPIO/UART infrared as the preferred build.
- MA-620 USB infrared and Prolific USB-to-RS-232 in the same release.
- Installer and a clean Raspberry Pi OS image from the same release sources.
- Approximately 4 GB uncompressed image target, subject to measured size, with
  automatic expansion on first boot.
- Other Pi models are untested; further model testing is not required for release.

## Current validation

All 100 existing Python unit tests pass on the development computer. Selected
source files passed checksum and basic secret-pattern checks. These results do
not establish clean-install, kernel-build or physical hardware acceptance.

## Outstanding before release

- Bootstrap download script and private-download test procedure.
- MY018 defaults/adapter selection and first-start configuration.
- Password/account handling, including the installation verifier.
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

Keep this repository private until release checks are complete. Before making
it public, review the full Git history and any Actions logs/artifacts as well.
