# Guarded updates for an existing installation

Feature-only updates replace a reviewed set of application files without
installing packages, building drivers, changing boot settings, selecting an
adapter or changing credentials:

```sh
sh install.sh --features-check
sudo sh install.sh --features-only
```

The check has no side effects. Apply creates a transactional backup under
`/var/lib/retromodem/update-backups/`, updates the checksum manifest and
restarts only affected active services. Unknown local versions and symlinks are
rejected.

## Migration away from the local RetroWEB core

The release that removes the local PHP proxy changes DNS routes, removes a
systemd unit and deletes `/opt/retromodem/retroweb`. For that one transition,
feature-only mode stops and requests a full installer run. The full installer
does not upgrade the kernel; it installs only the packages required by the
current configuration, preserves settings and removes the obsolete components.
After this migration, guarded feature-only updates work normally again.
