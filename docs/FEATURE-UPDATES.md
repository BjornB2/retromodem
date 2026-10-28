# Guarded updates for an existing installation

The full installer has a feature-only mode. It does not install packages, build
drivers, change boot settings, adapter selection, Wi-Fi or ChatGPT credentials.
Run from a reviewed source checkout:

```sh
sh install.sh --features-check
sudo sh install.sh --features-only
```

The check does not change installed files or services. Applying an update backs
up all affected originals under `/var/lib/retromodem/update-backups/`, replaces
only explicitly mapped feature files and restarts only affected active web/proxy
services. The existing installation checksum manifest is adjusted transactionally.
Write or restart failures trigger rollback; incomplete rollback is reported.

Unknown local versions and symlinks are rejected before changes. Do not bypass
this check: first compare that installation with the reviewed source baseline.
This initial update covers RetroWEB pagination, chat connection/cache notices and
adapter-aware diagnosis. Existing explicitly configured speeds remain unchanged.

Under Settings → Built-in web proxy, choose Small (12 kB), Normal (18 kB), or
25, 50, 75, 100, 125, 150, 175 or 200 kB, Entire page, and 1–10 images per part. Defaults are 18 kB and five images.
There is no five-part limit: five refers to images per part, not article length.
Choose No image limit to split by HTML size only. Image files and decoded image
memory are not included in the HTML byte budget. The default remains five.
Entire page disables both limits. Reopen the original website after changing
settings; existing snapshot links intentionally keep their original division.

RetroWEB splits processed pages into approximately 18 kB parts with at most five
inline images, previous/next navigation and a full-page link. Snapshots expire
after one hour. These budgets still require physical Palm-browser acceptance.
Extremely large indivisible markup can use a small placeholder/text fallback;
the full-page link retains the original processed content.
