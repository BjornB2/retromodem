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

Under Settings → Built-in web proxy, choose an explicit HTML size per part:
12, 18 (default), or 25–200 kB in steps of 25 kB, or Entire page. Only HTML
determines pagination. Image counts, GIF file bytes and decoded image memory
are not included. The legacy PAGE_IMAGES configuration key is ignored.

Images at session start offers Show images, Show as links, or Remember previous
choice. Existing IMAGE_MODE is the fallback when IMAGE_START is absent. On
the retro connection, a session is one PPP connection (its interface index).
The chosen view persists across websites during that connection. A successful
explicit image toggle from the PPP client records only its last mode in
`/var/lib/retromodem/proxy-image-choice.json`; Remember reads that value on the
next connection. Fixed start modes still reset on a new connection. Local QA
clients neither overwrite this remembered PPP preference nor need cookies.

Every new document has Images: Inline | As links at the top and bottom. Both
views derive from the same cached source snapshot, without refetching the site.
Switching targets the part containing the same source block; part numbers may
change. Back/reload keep each variant stable. Snapshot links expire after an hour.
Reopen the original website after changing size settings. Old snapshots remain
readable but cannot gain a missing image variant: reopen their original URL.

Small functional images, links and labels are retained. Removed site-wide
images are not blindly appended after the article. Resize hints survive the
internal image route; images load individually, not as a preflight of the page.
There is no pixel/download budget in this version, nor a guaranteed safe
memory limit for a particular Psion or Palm browser.

Saving content settings does not restart the proxy or PHP services. Image
dimensions are read from the local configuration on each PHP request. Only
switching manual/automatic mode reapplies firewall routing; existing settings
are restored if that routing operation fails. The proxy handshake queue is 128.
Installing changed runtime code still requires a one-time service restart.

RetroWEB defaults to approximately 18 kB HTML parts with previous/next navigation
and a full-page link. These budgets still require physical browser acceptance.
Extremely large indivisible markup can use a small placeholder/text fallback;
the full-page link retains the original processed content.
