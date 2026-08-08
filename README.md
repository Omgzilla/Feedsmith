# Feedsmith
*Forging clean feeds from arbitrary sources*

`feedsmith` is a small scheduled Python application that collects public metadata from configured sites, keeps canonical article history in SQLite, and publishes RSS 2.0 and Atom feeds to Cloudflare R2.

The first adapter is `omni`; the application is deliberately structured as a generic engine plus source adapters:

```text
feedsmith/
  core/       SQLite, feeds, R2 publishing, metrics
  sources/    site-specific discovery and cleanup
  sources/omni.py
```

It does not download or proxy article images, retrieve subscriber-only article bodies, run a persistent web server, or use Docker, Workers, Pages, GitHub Actions, or GitHub as generated-feed storage.

## Outputs

The initial Omni feed endpoints are:

```text
https://rss.example.com/omni/rss.xml
https://rss.example.com/omni/atom.xml
```

`/senaste` runs every five minutes and publishes immediately. Homepage/category discovery runs every thirty minutes to improve coverage and then publishes the same feeds. The configured 90-day Omni override retains source history; the global default for later sources is 30 days.

Future filters are configuration-driven and use the same SQLite data:

```text
/omni/free/rss.xml
/omni/premium/rss.xml
/omni/ekonomi/rss.xml
```

## Omni adapter behavior

The Omni adapter collects only public title, teaser, URL, timestamps, category, author, tags, premium flag, and hotlinked Omni image URL. It preserves useful existing metadata if a later scrape omits it.

Premium articles remain in the feed with their original title and a `Premium` RSS/Atom category in addition to their normal section. The adapter removes known Omni Mer promotional UI and the standalone `Kontakta redaktionen` UI link from a teaser before it enters generic storage. These are Omni-only rules; other sources must opt into their own cleanup.

Before deploying, review Omni's current terms and crawler guidance, identify the scraper accurately with `FEEDSMITH_USER_AGENT`, and keep the configured request delay conservative.

## Configuration and install

On Ubuntu 24.04, install `python3`, `python3-venv`, `sqlite3`, and `ca-certificates`. Use a non-login `feedsmith` account and install the source at `/srv/feedsmith`.

```bash
python3 -m venv /srv/feedsmith/.venv
/srv/feedsmith/.venv/bin/pip install /srv/feedsmith
install -d -o feedsmith -g feedsmith /var/lib/feedsmith /var/lib/feedsmith/public
install -d -o root -g feedsmith -m 0750 /etc/feedsmith
install -m 0640 config.toml.example /etc/feedsmith/config.toml
install -m 0600 systemd/feedsmith.env.example /etc/feedsmith/feedsmith.env
```

Edit `/etc/feedsmith/config.toml` for non-secret application/source settings and `/etc/feedsmith/feedsmith.env` for R2 credentials. Do not commit either deployment copy. R2 needs only a bucket, a custom domain, and a bucket-restricted Object Read & Write API token.

Test without network publishing:

```bash
sudo -u feedsmith /srv/feedsmith/.venv/bin/feedsmith run --config /etc/feedsmith/config.toml --source omni --mode latest --no-upload
```

Then install and activate the three timers:

```bash
install -m 0644 systemd/feedsmith-*.service /etc/systemd/system/
install -m 0644 systemd/feedsmith-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now feedsmith-latest.timer feedsmith-full.timer feedsmith-maintenance.timer
```

Operational output is structured for the journal:

```bash
journalctl -u feedsmith-latest.service -n 100 --no-pager
systemctl list-timers 'feedsmith-*'
```

There is intentionally no public status object. Optional Prometheus metrics are written to node_exporter's textfile collector if `PROMETHEUS_TEXTFILE_PATH` is configured.

## Safety and validation

SQLite remains unchanged on an unsuccessful parse. Before replacing a local feed or uploading to R2, generated XML is parsed and checked for the configured minimum entry count, titles, canonical Omni links, and recency. Local files are atomically replaced. R2 objects are uploaded only after all local feeds validate; RSS and Atom remain separate complete objects because R2 has no multi-object atomic transaction.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/python -m pytest -q
```

Fixtures cover parser and cleanup behavior without live Omni requests. Add a source by implementing `SourceAdapter` in `feedsmith/sources/`, then registering it in the CLI; shared SQLite, feed, publishing, retention, and metrics behavior remains untouched.
