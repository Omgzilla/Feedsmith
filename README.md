# Feedsmith

*Forging clean feeds from public web sources.*

Feedsmith runs on linux (probably runs on other OS's as well), stores article metadata in SQLite, and publishes RSS and Atom XML to Cloudflare R2. Its first source is Omni.se.

The result is a feed such as:

```text
https://rss.example.com/omni/rss.xml
```

## Quick start

These steps set up Feedsmith on a fresh Ubuntu 24.04 container. Replace the Git URL and email address before running them.

### 1. Install Feedsmith

Run as `root` inside the container:

```bash
apt update
apt full-upgrade -y
apt install -y ca-certificates curl git python3 python3-venv sqlite3

adduser --system --group --home /var/lib/feedsmith feedsmith
install -d -o feedsmith -g feedsmith /var/lib/feedsmith /var/lib/feedsmith/public
install -d -o root -g feedsmith -m 0750 /etc/feedsmith

git clone https://github.com/Omgzilla/feedsmith.git /srv/feedsmith
python3 -m venv /srv/feedsmith/.venv
/srv/feedsmith/.venv/bin/pip install --upgrade pip
/srv/feedsmith/.venv/bin/pip install /srv/feedsmith

install -m 0640 -o root -g feedsmith /srv/feedsmith/config.toml.example /etc/feedsmith/config.toml
install -m 0600 -o root -g root /srv/feedsmith/systemd/feedsmith.env.example /etc/feedsmith/feedsmith.env
```

### 2. Create the R2 bucket and API token

In Cloudflare:

1. Create an R2 bucket, for example `feedsmith`.
2. Create an **Account API token** limited to that bucket with **Object Read & Write** permission.
3. Add the bucket custom domain, for example `rss.example.com`.
4. Copy the S3 endpoint, access-key ID, and secret-key value.

### 3. Add your settings

Edit the non-secret settings:

```bash
nano /etc/feedsmith/config.toml
```

Set `public_base_url` to your domain:

```toml
[publishing]
public_base_url = "https://rss.example.com"
```

Then edit the secrets file:

```bash
nano /etc/feedsmith/feedsmith.env
```

Set these values:

```ini
FEEDSMITH_USER_AGENT="feedsmith/1.0 (+mailto:you@example.com)"
R2_ENDPOINT_URL=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
R2_BUCKET=feedsmith
R2_ACCESS_KEY_ID=replace-me
R2_SECRET_ACCESS_KEY=replace-me
```

Keep this file private. It contains the R2 secret and must never be committed.

### 4. Make a safe first run

This fetches Omni’s public metadata and creates local feed files without uploading anything to R2:

```bash
runuser -u feedsmith -- /srv/feedsmith/.venv/bin/feedsmith run \
  --config /etc/feedsmith/config.toml \
  --source omni --mode latest --no-upload
```

Confirm that the files exist and are valid XML:

```bash
ls -lh /var/lib/feedsmith/public/omni/
python3 -c 'from xml.etree import ElementTree as ET; ET.parse("/var/lib/feedsmith/public/omni/rss.xml"); ET.parse("/var/lib/feedsmith/public/omni/atom.xml")'
```

### 5. Publish once, then enable timers

Install the units and run the first real publish:

```bash
install -m 0644 /srv/feedsmith/systemd/feedsmith-*.service /etc/systemd/system/
install -m 0644 /srv/feedsmith/systemd/feedsmith-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl start feedsmith-latest.service
systemctl status feedsmith-latest.service --no-pager
```

Check the public feed:

```bash
curl --fail --silent --show-error https://rss.example.com/omni/rss.xml >/dev/null
```

Enable scheduled updates:

```bash
systemctl enable --now feedsmith-latest.timer feedsmith-full.timer feedsmith-maintenance.timer
systemctl list-timers 'feedsmith-*'
```

That is it. Add `https://rss.example.com/omni/rss.xml` to your reader. In [ReadYou](https://github.com/ReadYouApp/ReadYou), **do not select “Parse full content”** when adding this feed: Feedsmith already provides the cleaned public article content in the feed itself. That option fetches Omni’s original webpage and will show Omni’s own page UI and advertising.

If you are upgrading from a metadata-only Feedsmith release, run this one-off backfill after installing the updated systemd unit. It fetches public bodies for existing free articles and republishes the feeds; it never fetches Omni Mer bodies:

```bash
systemctl start feedsmith-backfill.service
journalctl -u feedsmith-backfill.service -n 100 --no-pager
```

## What runs when

| Unit | Schedule | Purpose |
| --- | --- | --- |
| `feedsmith-latest.timer` | Every 5 minutes | Scrape `/senaste` and publish immediately. |
| `feedsmith-full.timer` | Every 30 minutes | Scan the homepage and configured categories for coverage. |
| `feedsmith-maintenance.timer` | Daily | Prune expired history and optimize SQLite. |

## Day-to-day operations

```bash
# Recent run logs
journalctl -u feedsmith-latest.service -n 100 --no-pager

# Run a full coverage scan immediately
systemctl start feedsmith-full.service

# Test the configuration/R2 credentials
/srv/feedsmith/.venv/bin/feedsmith check --config /etc/feedsmith/config.toml
```

There is intentionally no public status endpoint. If configured, Prometheus metrics are written to the node_exporter textfile collector.

## Updating Feedsmith

Do not only pull the source: the systemd services run the package installed in `/srv/feedsmith/.venv`. Stop the timers, pull the reviewed update, reinstall the package, then run a fresh latest scrape:

```bash
systemctl stop feedsmith-latest.timer feedsmith-full.timer feedsmith-maintenance.timer

git -C /srv/feedsmith pull --ff-only
/srv/feedsmith/.venv/bin/pip install --upgrade /srv/feedsmith

systemctl daemon-reload
systemctl start feedsmith-latest.timer feedsmith-full.timer feedsmith-maintenance.timer
systemctl start feedsmith-latest.service
```

After upgrading to a release that adds or changes public-body extraction, also run `systemctl start feedsmith-backfill.service` once.

Verify the result:

```bash
systemctl status feedsmith-latest.service --no-pager
journalctl -u feedsmith-latest.service -n 100 --no-pager
```

## Configuration

[`config.toml.example`](config.toml.example) contains every non-secret setting. The global retention default is 30 days; Omni uses a 90-day override. Feed history defaults to 500 entries.

Future filtered feeds reuse the same SQLite data. Enable them under `[sources.omni.feeds]`:

```text
/omni/free/rss.xml
/omni/premium/rss.xml
/omni/ekonomi/rss.xml
```

## Omni behavior and limits

The Omni adapter reads public metadata plus the public body of free articles: title, teaser, public body, URL, time, category, author, tags, premium status, and hotlinked Omni image URL. It does not fetch subscriber-only bodies or download images.

Premium stories stay in the feed with their unchanged titles, public teasers, and a `Premium` category; their subscriber-only bodies are never included. Known Omni Mer promotional blocks and Omni’s contact-information UI are removed by the Omni adapter only.

Review Omni’s current terms and crawler guidance before deployment. Identify the scraper honestly with `FEEDSMITH_USER_AGENT` and keep the request delay conservative.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/python -m pytest -q
```

The generic engine lives in `feedsmith/core/`; source-specific scraping and cleanup lives in `feedsmith/sources/`. Adding another source should not require changes to storage, feed rendering, R2 publishing, or scheduling.
