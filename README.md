# Omni RSS

A small, self-hosted publisher that reads public Omni.se pages, records seen stories in SQLite, and writes a compatible RSS 2.0 feed and Atom feed. It stores no images: article images remain direct HTTPS links to Omni (`gfx.omni.se`/other Omni subdomains), so each feed reader retrieves an image from Omni only when it chooses to display it.

The intended production layout is deliberately minimal:

```text
Omni.se -> LXD Ubuntu 24.04 container -> SQLite + Python publisher -> Cloudflare R2 bucket -> rss.example.com/rss.xml
                                                                        -> rss.example.com/atom.xml
```

There are no containers, Workers, Pages, databases in Cloudflare, GitHub data backups, or image copies. R2 is used only for the two static XML objects. The application also keeps local copies in `/var/lib/omni-rss/public` for diagnosis and recovery.

> Before running a scraper, review Omni's current terms and robots policy, identify yourself honestly in `OMNI_USER_AGENT`, keep the conservative request delay, and stop if Omni asks you to. This project is not affiliated with Omni.

## What it does

- Starts at `https://omni.se/senaste` (the all-category latest-news page) and `https://omni.se/` (top stories). Add or remove source pages with one configuration value.
- Finds canonical article links, fetches article metadata, and uses JSON-LD plus Open Graph fallbacks so routine markup changes are less brittle.
- Deduplicates by a SHA-256 hash of each canonical article URL; state and run history are stored in SQLite.
- Produces RSS 2.0 with Media RSS image elements and an HTML image in the description, plus Atom with image enclosures.
- Validates the XML and item count before changing either local public feed, uses atomic file replacement, then uploads to R2 using its S3-compatible API.
- Keeps the latest 100 articles by default and prunes local state after 30 days. These are configuration values, not hard limits.

## 1. Create the Ubuntu 24.04 LXD container

On the LXD host:

```bash
lxc launch ubuntu:24.04 omni-rss
lxc config set omni-rss limits.cpu 2
lxc config set omni-rss limits.memory 1GiB
lxc config set omni-rss boot.autostart true
lxc shell omni-rss
```

Inside the container, install the small base set:

```bash
apt update
apt full-upgrade -y
apt install -y ca-certificates python3 python3-venv sqlite3 curl
```

Create a non-login service account and its state directory:

```bash
adduser --system --group --home /var/lib/omni-rss omni-rss
install -d -o omni-rss -g omni-rss /srv/omni-rss /var/lib/omni-rss /var/lib/omni-rss/public
install -d -o root -g omni-rss -m 0750 /etc/omni-rss
```

Copy this project to `/srv/omni-rss` by your preferred trusted route (for example, `scp` from the machine where you extracted the archive), then set the executable tree owner:

```bash
chown -R root:root /srv/omni-rss
python3 -m venv /srv/omni-rss/.venv
/srv/omni-rss/.venv/bin/pip install --upgrade pip
/srv/omni-rss/.venv/bin/pip install /srv/omni-rss
```

## 2. Configure R2 once

Use the Cloudflare dashboard:

1. Go to **R2 Object Storage** and create a bucket, for example `omni-rss`. It needs only two objects: `rss.xml` and `atom.xml`.
2. In **R2 > Overview > Manage API Tokens**, create an **Account API token** with **Object Read & Write** access limited to that one bucket. Copy the access key ID and secret now; the secret cannot be viewed again.
3. In the bucket’s **Settings > Custom Domains**, connect `rss.example.com`. The domain must be a zone in the same Cloudflare account. Wait until the connection is Active.
4. Leave the `r2.dev` development URL disabled. It is not used by this setup.

This is the only Cloudflare configuration needed. It has no Worker invocation, Pages build, or database cost. Use the exact S3 endpoint displayed by R2, normally `https://ACCOUNT_ID.r2.cloudflarestorage.com`; R2’s S3 region is `auto`. Cloudflare’s current [public-bucket custom-domain guide](https://developers.cloudflare.com/r2/buckets/public-buckets/) and [S3 API guide](https://developers.cloudflare.com/r2/get-started/s3/) document these steps.

For a low-change feed, the configured five-minute cache control is intentional: clients get a quick update without the stale cache commonly caused by a one-day static-object policy. You may set an ordinary Cloudflare cache rule for this hostname if desired, but none is required.

## 3. Add the secret configuration

Copy and edit the example. This file contains the R2 secret and must stay readable only by root.

```bash
install -m 0600 -o root -g root /srv/omni-rss/deploy/omni-rss.env.example /etc/omni-rss/omni-rss.env
nano /etc/omni-rss/omni-rss.env
```

Set at least these values:

```ini
FEED_BASE_URL=https://rss.example.com
R2_ENDPOINT_URL=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
R2_BUCKET=omni-rss
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
OMNI_USER_AGENT="omni-rss/1.0 (+mailto:your-address@example.com)"
```

`OMNI_SOURCE_URLS=https://omni.se/senaste,https://omni.se/` is the default. Add an Omni category page to this comma-separated list if you want it scanned too. It remains deduplicated in the one feed.

## 4. Test locally, then enable scheduled publishing

Run once without any remote change. It will create SQLite state plus locally inspectable XML in `/var/lib/omni-rss/public`:

```bash
sudo -u omni-rss /srv/omni-rss/.venv/bin/omni-rss run --no-upload
```

The publisher already parses and checks both XML documents before it writes them. If you would also like an independent command-line XML inspection, install `xmllint` and run:

```bash
apt install -y libxml2-utils
xmllint --noout /var/lib/omni-rss/public/rss.xml /var/lib/omni-rss/public/atom.xml
```

Install the systemd units before the real upload. The service loads `/etc/omni-rss/omni-rss.env` itself, and its pre-flight check verifies the R2 settings. Do **not** run `omni-rss check` directly with `sudo -u omni-rss`: that shell command does not load systemd's `EnvironmentFile`.

```bash
install -m 0644 /srv/omni-rss/deploy/omni-rss.service /etc/systemd/system/omni-rss.service
install -m 0644 /srv/omni-rss/deploy/omni-rss.timer /etc/systemd/system/omni-rss.timer
systemctl daemon-reload
```

Run the real upload once through systemd:

```bash
systemctl start omni-rss.service
systemctl status omni-rss.service --no-pager
curl --fail --silent --show-error https://rss.example.com/rss.xml >/dev/null
curl --fail --silent --show-error https://rss.example.com/atom.xml >/dev/null
```

Then activate the timer:

```bash
systemctl enable --now omni-rss.timer
systemctl list-timers omni-rss.timer
```

The timer fires about every five minutes with up to 30 seconds of jitter. `flock` makes a slow prior run skip the overlap instead of running two scrapes concurrently.

## Operations

```bash
# Last run and errors
systemctl status omni-rss.service
journalctl -u omni-rss.service -n 100 --no-pager

# Trigger a one-time update
systemctl start omni-rss.service

# Inspect local state without printing secrets
sudo -u omni-rss sqlite3 /var/lib/omni-rss/omni.sqlite3 \
  'select status, discovered, published, finished_at, error from runs order by id desc limit 10;'
```

The failure behavior is conservative: invalid XML, too few items, an unexpected parse failure, or an R2 error causes a non-zero service result. The local files are written only after both generated feeds pass their sanity checks. R2 has no two-object atomic publish operation, so a network failure while uploading may update one XML object but not the other; the next successful scheduled run reconciles them. Keeping the feeds small and issuing the two updates back-to-back makes this window very short.

### Optional Prometheus metric

If the container already runs node_exporter with its textfile collector enabled, set this in `/etc/omni-rss/omni-rss.env` and make that directory writable by `omni-rss`:

```ini
PROMETHEUS_TEXTFILE_PATH=/var/lib/node_exporter/textfile_collector/omni_rss.prom
```

It exports `omni_rss_last_run_success`, the run timestamp, discovered article count, and published item count. No HTTP server or extra daemon is added.

## Development and verification

On a development machine using Python 3.10+:

```bash
python3 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/python -m pytest -q
.venv/bin/omni-rss run --no-upload
```

The test fixtures cover article-link filtering, metadata extraction and image hotlink protection, plus parseable RSS/Atom output and their image elements. The live scrape is intentionally not a unit test.

## Updating

Stop the timer, replace `/srv/omni-rss` with the reviewed new release, recreate/update its virtual environment, run the local no-upload command, then start the timer:

```bash
systemctl stop omni-rss.timer
python3 -m venv /srv/omni-rss/.venv
/srv/omni-rss/.venv/bin/pip install --upgrade /srv/omni-rss
sudo -u omni-rss /srv/omni-rss/.venv/bin/omni-rss run --no-upload
systemctl start omni-rss.timer
```

Never include `/etc/omni-rss/omni-rss.env`, SQLite state, or the local public files in a source archive or repository.
