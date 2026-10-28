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

Under Settings → Built-in web proxy, choose a part budget:
12, 18 (default), 25–200 kB in steps of 25 kB, 250–2,000 kB in steps of
250 kB, or Entire page. This estimates page size including decoded images,
not data transfer or download size. Browser working memory is additional.
The legacy PAGE_IMAGES configuration key is ignored; no fixed image count
determines pagination.

Images at session start offers Show images, Show as links, or Remember previous
choice. Existing IMAGE_MODE is the fallback when IMAGE_START is absent. On
the retro connection, a session is one PPP connection (its interface index).
The chosen view persists across websites during that connection. A successful
explicit image toggle from the PPP client records only its last mode in
`/var/lib/retromodem/proxy-image-choice.json`; Remember reads that value on the
next connection. Fixed start modes still reset on a new connection. Local QA
clients neither overwrite this remembered PPP preference nor need cookies.

Every new document has language-aware image controls and pagination before the
page title and at the bottom. The separate reload link has been removed to save
screen space; use the browser. Both views derive from the same cached source
snapshot, without refetching the site.
Switching targets the part containing the same source block; part numbers may
change. Back/reload keep each variant stable. Snapshot links expire after an hour.
Reopen the original website after changing size settings. Existing canonical
snapshots are rebuilt locally under the current language and weighting policy.
Very old final-HTML-only snapshots return 410 with a reopen message rather than
serving an unbounded old page.

Small functional images, links and labels are retained. Removed site-wide
images are not blindly appended after the article. Resize hints survive the
internal image route; images load individually, not as a preflight of the page.
In inline view the part budget combines transmitted HTML bytes and an estimated
image weight of one byte per displayed pixel (the indexed GIF raster). In links
view only HTML counts, so it can have fewer parts. This is a pagination weight,
not a guarantee about actual browser RAM or download size. A single image too
large for a part stays available as a link. Entire-page view removes the budget
and may exhaust a retro browser's memory. No image downloads are needed to plan
the parts. Unknown dimensions are estimated conservatively.

Overview extraction prefers explicit main landmarks, including role="main",
and does not concatenate nested articles twice. This preserves featured content
on Tweakers rather than reducing its front page to duplicated headline lists.

The embedded image downloader checks and pins each redirect destination,
rejects private addresses, and bounds the download and total time. Its resolver
requires Linux `/usr/bin/timeout`, `/usr/bin/getent`, PHP proc_open and cURL,
which are part of the Raspberry Pi installation. Do not deploy this Pi-specific
transport to generic shared hosting without checking its runtime capabilities.

Saving content settings does not restart the proxy or PHP services. Image
dimensions are read from the local configuration on each PHP request. Only
switching manual/automatic mode reapplies firewall routing; existing settings
are restored if that routing operation fails. The proxy handshake queue is 128.
Installing changed runtime code still requires a one-time service restart.

RetroWEB defaults to an approximately 18 kB weighted budget with previous/next navigation
and a full-page link. These budgets still require physical browser acceptance.
Extremely large indivisible markup can use a small placeholder/text fallback;
the full-page link retains the original processed content.
