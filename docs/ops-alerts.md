# Scrape console and phone alerts

What runs where, and the one-time setup only the owner can do (dashboards
and secrets). No secret ever goes into git or a GitHub workflow.

## What you get

- **`/admin/`**: the scrape console on the live site, behind a password
  the Worker checks (no Cloudflare Access, no card). It has these tabs:
  - Tonight: open problems, the last 30 hours of crawls on an Israel-time
    timeline, one card per vendor with a 14-crawl sparkline
  - Calendar: a month grid (‹ › to page through the last 120 days); each
    day is one night with a chip per vendor; click a day for its crawls
  - New: new products, a vendor started selling, back on sale
  - No longer sold: gone everywhere, a vendor stopped, missing once
  - Prices: moves of 5% or more over 14 days
  - Catalog: offers per vendor (fresh vs stale), one card per category
    (how many products 1 / 2 / 3+ vendors sell, vendor split, price range,
    stock), the quality queue
  - Header: **Reload** fetches the newest deployed report; **Rebuild report**
    regenerates it from the latest scrapes (needs `GH_DISPATCH_TOKEN`)
  - Alerts & runs
- **Phone pushes (ntfy)** when something breaks. Urgent ones (site down,
  API flood, a vendor blocking the scraper) push at any hour. The rest
  (scrape missing, Nano down, normalize stuck, partial crawl, double crawl,
  delisting spike) wait until 07:00 Israel time. An alert is pushed once,
  reminded after 24 h, and you get a "Resolved" push when it clears.
- **A daily scrape report at 10:00 Israel time**, one line per vendor. It is
  silent when every line is ✅ and buzzes once when anything is ⚠️ or ❌.

## How it works

```
data/raw/** + catalog ──normalize-and-deploy──► python -m scraper.ops.report
                                                ──► data/ops/status.json, changes.json, memory.json
site build (copy-data.mjs) ──► /admin/data/{status,changes}.json   (Worker checks ADMIN_PASSWORD)

Worker cron */30 ──► rules.ts evaluate() ──► ops_alerts (D1) ──► ntfy
                └──► 10:xx Israel, once a day ──► daily report ──► ntfy ──► Healthchecks ping
Nano scrape unit ──OnFailure / ExecStartPost──► nano/ops_notify.sh ──► POST /api/ops/event
                                                  (Worker down? straight to ntfy)
```

- `scraper/ops/` records facts only: every crawl (start, end, items, new,
  gone, missing, partial, misfiled, two crawls in one file). "Not scraped" and
  "late" depend on the clock, so `site/src/ops/rules.ts` decides them when
  read. A report that stopped updating is itself an alert.
- Lifecycle rules (owner, 2026-11-12): a listing absent from one crawl is
  *missing*. One absent from two crawls, at least 36 h apart, is *gone*. A
  partial crawl never counts an absence.
- A crawl belongs to the night it started in. The file name does not matter
  (the old `run_tms.sh` appended two nights to one file).

## One-time setup

1. **ntfy app.** Install ntfy (iOS/Android) and make a free account on
   ntfy.sh. Reserve a long random topic, for example
   `mifrat-` plus 20 random characters. Create an access token (Account →
   Access tokens). Subscribe to the topic in the app. Anyone who knows the
   topic name can read it, so treat the name like a password.
2. **Worker secrets.** Set these in Cloudflare → Workers & Pages → mifrat →
   Settings → Variables and secrets, all of type *Secret*:
   - `NTFY_TOPIC_URL` = `https://ntfy.sh/<your topic>`
   - `NTFY_TOKEN` = the `tk_...` token. Recommended: Workers share outgoing
     IPs, and ntfy.sh rate-limits anonymous senders per IP.
   - `OPS_INGEST_TOKEN` = a long random string. The Nano uses the same value.
   - `ADMIN_PASSWORD` = the password for `/admin/`. Use a long one; the
     browser remembers it. Any username works. Without this secret
     `/admin/` stays locked for everyone, and 10 wrong tries lock an IP out
     for 10 minutes.
   - `GH_DISPATCH_TOKEN` = optional, for the **Rebuild report** button.
     On GitHub go to Settings → Developer settings → Fine-grained tokens →
     Generate. Repository access: only `Av1zi/Mifrat`. Permissions:
     Actions → Read and write (nothing else). The button starts the
     `ops-report` workflow, which regenerates `data/ops` and redeploys the
     site; the page waits and reloads itself (about 3-5 minutes). Without
     the token the button says how to set it.
   - `HEALTHCHECK_URL` = optional, from step 5.
3. **D1 tables.** From `site/`, with your own wrangler login, run
   `npx wrangler d1 migrations apply mifrat-lists --remote`. This applies
   `migrations/0002_ops.sql`. The tables go in the existing short-link
   database.
4. **Log in.** Open `https://mifrat.avizi.workers.dev/admin/`. The browser
   asks for a username and password: type anything as the username and
   your `ADMIN_PASSWORD`. Add it to your phone's home screen. (Cloudflare
   Access was the first plan; Zero Trust asks for a card, so the Worker
   does the login itself.)
5. **Healthchecks.io (optional).** Free account. Create a check with period
   1 day and grace 1 hour, and add ntfy as an integration (same topic and
   token). Put its ping URL in `HEALTHCHECK_URL`. If the 10:00 report ever
   fails to go out, Healthchecks pushes "down" by ~11:00.
6. **Uptime (optional).** In UptimeRobot (free), add an HTTP monitor on
   `https://mifrat.avizi.workers.dev/data/site/meta.json` every 5 min, with
   a webhook to ntfy (JSON to `https://ntfy.sh/`, see ntfy docs
   "UptimeRobot"). This catches a site outage even when the Worker itself
   is down.
7. **GitHub Mobile.** Settings → Notifications → Actions → "Only failed
   workflows". This covers normalize / scrape-cloud failures with no secret
   in any workflow.
8. **Nano.** See `nano/NANO_README.md`, "Phone alerts".

## Test it

- Daily report text from real data, without sending: from `site/`, run
  `npx tsx` with a small script calling `dailyReport(status, evaluate(status,
  now), now)`.
- Send a test push: in the Worker dashboard (Settings → Triggers → Cron),
  use "Trigger". At 10:xx Israel it sends the daily report. At other times
  it pushes only real findings.
- Nano: `nano/ops_notify.sh pc-parts-il-ksp.service success` posts an `ok`
  run, which then shows under Alerts & runs.

## Gates

`python scripts/check_ops_report.py --self-test` (lifecycle rules,
mutation-checked), `python scripts/check_ops_report.py` (file budgets,
one run), `bash scripts/check_ops_notify.sh` (Nano notifier, stubbed),
`site/test/ops.test.ts` and `site/test/ops-worker.test.ts` (rules, report,
quiet hours, dedupe, DST, auth).
