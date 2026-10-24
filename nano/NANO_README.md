# Jetson Nano setup (TMS scraper)

One-time setup for the box that runs the TMS spider from home. Do these in order — step 1 is the most
common failure point on this hardware.

## 1. Python via Miniforge (not the system Python)

The stock Jetson image's system Python is too old for modern Scrapy.

```bash
wget -O Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh"
bash Miniforge3.sh -b
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda create -n pc-parts-il python=3.11 -y
conda activate pc-parts-il
```

Pin the **exact same Scrapy version** here as in `requirements.txt` /
GitHub Actions — version drift between the two environments is a listed
pitfall (§10).

## 2. Dedicated low-privilege user

```bash
sudo useradd -m pcparts
sudo -iu pcparts
```

Do the rest of this setup as `pcparts`, not your everyday user or root.

## 3. Clone the repo and install dependencies

```bash
git clone git@github.com:<you>/<repo>.git ~/pc-parts-il
cd ~/pc-parts-il
conda activate pc-parts-il
pip install -r requirements.txt
```

Keep the dependency list lean here — no `scrapy-playwright` browser install
unless a vendor genuinely needs it (§10); it's a heavy ARM64 install for a
box that only scrapes TMS.

## 4. SSH deploy key (repo-scoped, §9)

```bash
ssh-keygen -t ed25519 -C "pc-parts-il-nano" -f ~/.ssh/pc_parts_il_deploy_key -N ""
cat ~/.ssh/pc_parts_il_deploy_key.pub
```

Add the public key on GitHub: repo → Settings → Deploy keys → Add deploy
key → check **Allow write access**. Then point the repo's remote at that
key specifically (don't rely on a default `~/.ssh/id_ed25519` that might
have broader access elsewhere):

```bash
cat >> ~/.ssh/config << 'EOF'
Host github.com-pc-parts-il
  HostName github.com
  User git
  IdentityFile ~/.ssh/pc_parts_il_deploy_key
  IdentitiesOnly yes
EOF

git remote set-url origin git@github.com-pc-parts-il:<you>/<repo>.git
```

If this box is ever compromised, the blast radius is push access to this
one repo — nothing else.

## 5. NTP sync

```bash
timedatectl status | grep "NTP service"
```

Should say `active`. `nano/run_tms.sh` warns (but doesn't block) if the
clock isn't synchronized — wrong dates poison the daily-history data.

## 6. Install the systemd service + timer

```bash
sudo cp nano/pc-parts-il-tms.service nano/pc-parts-il-tms.timer /etc/systemd/system/
sudo cp nano/pc-parts-il-tms-fallback.service nano/pc-parts-il-tms-fallback.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pc-parts-il-tms.timer
sudo systemctl enable --now pc-parts-il-tms-fallback.timer
```

Check it's scheduled and see the next run time:

```bash
systemctl list-timers pc-parts-il-tms.timer pc-parts-il-tms-fallback.timer
```

Run it once by hand to confirm the whole chain works before trusting the
timer:

```bash
sudo systemctl start pc-parts-il-tms.service
journalctl -u pc-parts-il-tms.service -f
```

## 7. Verified AI extraction (optional, daily)

Fills spec fields that are still empty by reading each product's own listing
text (`scraper/extract/README.md`). It needs a model key, kept only on the Nano
in the gitignored `.env`:

```bash
cd ~/pc-parts-il
umask 077
cat > .env <<'ENV'
MIFRAT_EXTRACT_BACKEND=gemini
GOOGLE_KEY=paste-your-key-here
ENV
chmod 600 .env
git status --short .env        # prints nothing: .env is ignored
~/miniforge3/envs/pc-parts-il/bin/pip install requests   # if the env lacks it
```

First run, by hand (audit 300 products to measure accuracy, then fill):

```bash
AUDIT=300 bash nano/run_extract.sh
```

Then the daily timer:

```bash
sudo cp nano/pc-parts-il-extract.service nano/pc-parts-il-extract.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pc-parts-il-extract.timer
systemctl list-timers pc-parts-il-extract.timer
journalctl -u pc-parts-il-extract.service -n 50     # after a run
```

More providers go into the same `.env` (see `.env.example`):
`MIFRAT_EXTRACT_BACKEND=gemini,groq,intern`, `GROQ_KEY`, `INTERN_KEY`,
`INTERN_BASE_URL`, and `MIFRAT_EXTRACT_MODEL_<NAME>`. Run the audit once so
every model that answers gets its own accuracy table.

The free tier rate-limits (429 / 503): a run that is stopped keeps every answer
it already got (cached under `data/extract/.cache`, local to the Nano) and the
next day continues. The committed files are `data/extract/products.json` and
`trust.json`; the cloud's next normalize run merges them.

## 1PC listing scrape (also on the Nano)

1PC moved here 2026-10-24 (its site answers datacenter IPs with a CAPTCHA
page). Same home-IP rules as TMS; it runs after the TMS window. The spider
hard-stops after two 403/429 responses. Detail pages stay in the cloud job.

```bash
sudo cp nano/pc-parts-il-onepc*.service nano/pc-parts-il-onepc*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pc-parts-il-onepc.timer pc-parts-il-onepc-fallback.timer
sudo systemctl start pc-parts-il-onepc.service   # first run by hand
```

## Reading logs later

```bash
journalctl -u pc-parts-il-tms.service --since today
```

Nothing is written to a log file on disk — journald only (§4, SD card
health).

`run_tms.sh` refreshes the checkout with `git pull --rebase --autostash`
before both the listing crawl and the detail crawl. Each phase commits and
pushes its generated files immediately, so a later detail failure cannot
delay publication of the daily listing snapshot.

## One-time TMS detail backfill

After deploying a parser change, run the full existing TMS detail queue once
from the Nano home connection (never from a datacenter checkout):

```bash
cd ~/pc-parts-il
TMS_DETAIL_FULL_BACKFILL=1 ./nano/run_tms.sh
```

This temporarily removes the normal 50-item daily cap. The spider still keeps
one request at a time, a two-second delay, robots compliance, and the hard stop
after two block responses. If it stops, leave the remaining SKUs pending and
resume on a later day rather than retrying through a block.

## If TMS starts blocking the Nano too

That's the rule: pause several days, try slowing down further
(`DOWNLOAD_DELAY` in `scraper/spiders/tms.py`'s `custom_settings`), and if
still blocked, drop the vendor rather than escalating against active
defenses. Nothing here should ever be modified to defeat a block.
