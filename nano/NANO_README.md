# Nano — home-vendor setup and operations

TMS, 1PC and KSP use the home connection. Follow the binding
[scraping rules](../README.md#scraping-rules) before any live run. These are
owner setup instructions, not commands to execute during unrelated work.

**Current KSP state (Nov 22): paused.** The delayed recovery ran and failed;
its one-shot marker is consumed. Listing/detail timers remain disabled. Do
not reinstall the old recovery timer, enable KSP timers or delete pause/attempt
markers. The fixed header patch has not restored live-price collection.
[Transport status and evidence](../docs/ksp-stream-transport.md).

## Environment and checkout

System Python on the stock Nano is too old for Scrapy. Use Miniforge/Python
3.11 and the exact pinned dependencies in `requirements.txt`:

```bash
wget -O Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh"
bash Miniforge3.sh -b
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda create -n pc-parts-il python=3.11 -y
conda activate pc-parts-il
git clone git@github.com:Av1zi/Mifrat.git ~/pc-parts-il
cd ~/pc-parts-il
pip install -r requirements.txt
pip check
```

Use an unprivileged service account. Existing units/scripts are configured for
`avizi`, `/home/avizi/pc-parts-il` and its Miniforge environment; a different
account requires updating those paths together, not just creating `pcparts`.
Avoid a heavyweight browser install: no scheduled home spider needs one.

### Repo-scoped SSH key and clock

```bash
ssh-keygen -t ed25519 -C "pc-parts-il-nano" -f ~/.ssh/pc_parts_il_deploy_key -N ""
cat ~/.ssh/pc_parts_il_deploy_key.pub # public key only
```

Add that public key as a write-enabled deploy key for **this repo only**. Add
a dedicated host to `~/.ssh/config`:

```text
Host github.com-pc-parts-il
  HostName github.com
  User git
  IdentityFile ~/.ssh/pc_parts_il_deploy_key
  IdentitiesOnly yes
```

```bash
git remote set-url origin git@github.com-pc-parts-il:Av1zi/Mifrat.git
timedatectl status
```

NTP must be active. Wrong clocks misfile snapshots/history. Private keys and
provider/notification credentials stay outside git and shared output.

## Install active TMS and 1PC schedules

Only after dependency/path/clock checks and owner approval:

```bash
sudo cp nano/pc-parts-il-tms.service nano/pc-parts-il-tms.timer /etc/systemd/system/
sudo cp nano/pc-parts-il-tms-fallback.service nano/pc-parts-il-tms-fallback.timer /etc/systemd/system/
sudo cp nano/pc-parts-il-onepc*.service nano/pc-parts-il-onepc*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pc-parts-il-tms.timer pc-parts-il-tms-fallback.timer
sudo systemctl enable --now pc-parts-il-onepc.timer pc-parts-il-onepc-fallback.timer
systemctl list-timers 'pc-parts-il-*'
```

Timers are the authority for exact times: TMS starts at 21:15 UTC with jitter,
1PC at 23:20 UTC, fallbacks later at night. Every home scrape/publish stays in
21:00–04:00 UTC. Timers have no persistent catch-up; fallback runs only when
there is no recent success marker (18h). Stale-forward covers missed nights.
Configured KSP times do **not** imply its timers are enabled or safe to enable.

Scheduled jobs share `~/.local/state/pc-parts-il/checkout.lock`. Keep this
checkout dedicated to automation: some non-KSP wrappers still pull with
rebase/autostash. Do not leave human work in it or run another job's git
commands while it is writing. KSP wrappers refuse unrelated dirt and use
fast-forward-only pulls. Windows-authored shell scripts need git exec bits.

A manual service start is a real crawl, not a diagnostic. Use one only with
approval, in the permitted window, and when no attempt/block/success marker
rules forbid it. Do not start another crawl merely to confirm timer setup.

## Snapshots, detail and Eilat

Wrappers pin `MIFRAT_NIGHT` using `scraper/night.py`: a night starts 21:00 UTC
and is named by its ending date. One snapshot per vendor-night, atomic install;
a thinner second crawl cannot overwrite a fuller file. Older UTC-named folders
stay readable. [Raw storage](../data/raw/RAW_README.md).

TMS publishes its listing snapshot before optional detail/images, so a later
failure cannot hide collected prices. 1PC detail remains a cloud job. TMS
detail normally caps at 50; `TMS_DETAIL_FULL_BACKFILL=1` is a separately
approved one-time operation with the same pacing/stop rules, not routine
verification. Missing usable specs stay pending.

TMS's Eilat view uses `?eilat=1` and the branch-stock widget. KSP's stream is
designed to capture regular/Eilat prices together; the legacy KSP Eilat leg
is disabled during recovery. Eilat failures preserve regular observations,
but a KSP block stops **all** later phases. Force flags never authorize retry
against a block.

## KSP state and diagnostics

Listing markers distinguish `attempted`, `validated` and pushed `success`.
Publication may reuse validated output without recrawling. Detail uses
`done`/`ready`/`pushed`; skipped prerequisites never claim successful fetching.
Any KSP phase block creates `ksp-<night>.blocked` and persistent `ksp.paused`.
Only owner-reviewed cooldown/recovery may change that state; force flags do
not bypass it.

KSP detail was implemented Nov 13 (bounded 150-item chunks, same stop rules),
but `run_ksp_detail.sh` currently returns without crawling while the listing
recovery configuration exists. Its installation/probe history is not a new
authorization. [Detail contract](../docs/ksp-detail-plan.md).

Read-only collector on the Nano:

```bash
python scripts/diagnose_nano_scrapes.py --since 2026-11-16
journalctl -u pc-parts-il-tms.service --since today
```

The collector prints fixed facts/redacted signal counts, not raw credentials.
Local development does not install it on the Nano: copy just the collector to
a private temporary path before rollout and use
`python3 /path/to/diagnose_nano_scrapes.py --repo "$HOME/pc-parts-il"`.
It supports older system Python without packages. Use latest-invocation
evidence; aggregate counts or a working homepage do not prove catalog access.
Share redacted diagnostics, not raw journals. Logging stays in journald.

## Optional verified extraction

[Extraction guide](../scraper/extract/README.md) defines providers, trust, audit
and cache rules. Keep keys in the Nano's ignored `.env` (mode 600); provider
configuration comes from `.env.example`, never from copied real credentials.

After an approved audit/fill trial, install the optional timer:

```bash
sudo cp nano/pc-parts-il-extract.service nano/pc-parts-il-extract.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pc-parts-il-extract.timer
```

`run_extract.sh` pulls current catalog data, retains cached answers and sweeps
entries unreached for more than 14 days before publishing its own output.
Use the model's audit before trusting a provider; no automatic source-policy
exception follows from a missing spec.

## Phone alerts

Units POST run facts to the Worker via `OnFailure` and `ExecStartPost` (systemd
237 has no `OnSuccess`). Live failures update `/admin/`; **the sole phone push
is the 10:00 Israel daily report**. Failed delivery logs locally, never direct
ntfy fallback. Pulling the current `ops_notify.sh` removes the old fallback;
no new notification secrets or timer changes are needed for that update.

[Worker setup](../docs/ops-alerts.md) explains `OPS_INGEST_TOKEN`. Store the
same token with `OPS_EVENT_URL` in
`~/.config/pc-parts-il/notify.env` (directory mode 700, file 600), never git.
Install `nano/pc-parts-il-notify@.service` with the approved scrape units and
reload systemd. `nano/ops_notify.sh <unit> success` posts an actual run event;
it is a separately approved notification test, not a read-only check.

## If a home vendor blocks

Stop, preserve any allowed collected output, leave failed parts pending and
maintain the pause. Review cooldown/pacing with the owner; repeated rejection
means drop the vendor. No profiles, proxies, automatic recrawls or marker
deletion to defeat the block.
