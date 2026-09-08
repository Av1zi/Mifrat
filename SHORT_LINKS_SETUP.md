# Short build links (`/list/<id>`) — setup guide

All the code is done and in this repo. Short links like
`https://mifrat.net/list/aB3!xQ9` need one server-side piece — a tiny
Cloudflare D1 table that maps each 6-char id to its build — so there are a
few one-time steps only you can do (they need *your* Cloudflare login).
After that, everything deploys itself on every push to `main` as usual.

Expect ~15 minutes. Steps 1–3 are terminal commands run from `site/`;
step 4 is clicking in the Cloudflare dashboard; step 5 is testing.

## Before you start

- Install dependencies once (if you haven't): `npm install` inside `site/`.
- Log in to Cloudflare from the terminal (opens a browser window):

```bash
cd site
npx wrangler login
npx wrangler whoami   # should print your account — if not, stop here
```

## Step 1 — create the D1 database (terminal)

```bash
cd site
npx wrangler d1 create mifrat-lists
```

The output contains a `database_id`, e.g.:

```
✅ Successfully created DB 'mifrat-lists'
database_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Open `site/wrangler.jsonc`, find this line:

```jsonc
"database_id": "REPLACE_WITH_D1_DATABASE_ID"
```

and paste your real id in its place:

```jsonc
"database_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

> Until you do this, `wrangler deploy` refuses to run — that is
> intentional, so the site can never deploy with link storage unwired.

## Step 2 — create the table (terminal)

One command, run from `site/` (the SQL file is `site/migrations/0001_lists.sql`):

```bash
cd site
npx wrangler d1 execute mifrat-lists --remote --file=migrations/0001_lists.sql
```

You should see `Executed 1 command`. The table holds one row per shared
build (`id`, `build`, `build_hash`, `created_at`) and is **insert-only** —
rows are never updated or deleted, which is what makes every link permanent.

## Step 3 — verify locally, then commit (terminal)

```bash
cd site
npm run build                        # tsc + vite, must pass with no errors
npx wrangler deploy --dry-run        # bundles worker.ts, checks the config
```

`--dry-run` should print both bindings with no errors:

```
env.LISTS_DB (mifrat-lists)      D1 Database
env.ASSETS                       Assets
```

Then commit **only the files this feature added/changed** and push:

```bash
git add site/worker.ts site/src/lists.ts site/src/state.ts site/src/main.ts \
  site/src/i18n.ts site/src/icons.ts site/src/views/builder.ts \
  site/wrangler.jsonc site/migrations/0001_lists.sql \
  site/README.md AGENTS.md SHORT_LINKS_SETUP.md
git commit -m "Short permanent build links (/list/<id>) via Worker + D1"
git push
```

> `decisions.md` documents the change but is gitignored — it stays local,
> do not commit it.

## Step 4 — Cloudflare dashboard (one-time, ~2 minutes)

Your project already builds with Workers Builds (that's what
`wrangler.jsonc` + root `package.json:build` are for). On the next push it
will deploy the Worker automatically — just confirm these two things:

1. **Workers & Pages → `mifrat` → Settings → Build:**
   - Root directory: `site`
   - Build command: `npm run build` (so `site/dist` exists for the
     `assets.directory`)
   - Deploy command: `npx wrangler deploy`
2. **Workers & Pages → `mifrat` → Settings → Bindings** (after the first
   deploy with the new config): you should see the `LISTS_DB` D1 binding
   and the `ASSETS` assets binding. If the deploy failed, it is almost
   certainly the placeholder `database_id` — go back to step 1.

Custom domain: nothing to change. `mifrat.net/list/*` is served by the same
Worker that now also answers `/api/*`.

Optional but recommended — abuse protection (the API validates + caps body
size already, this adds rate limiting):
**Security → Rate Limiting → Create rule** matching
`mifrat.net/api/lists` with POST, e.g. 20 requests / 10 minutes / IP.

## Step 5 — test on production

1. Open `https://mifrat.net/#/build`, add 2–3 parts.
2. Click the new **link icon** (⛓) next to the copy button. The share box
   should swap to a short `https://mifrat.net/list/xxxxxx` URL and copy it.
3. Open that URL in an incognito window — the same parts must load with
   current prices.
4. Open an old long `#/build?cpu=...` link — it must still work (kept
   forever as the offline fallback).
5. Open `https://mifrat.net/list/000000` — you must get the friendly
   "link wasn't found" panel, not a blank page.

## Local development notes

- `npm run dev` (Vite only) has **no** `/api/*` — clicking the link icon
  there just keeps the long URL. That is the intended offline fallback,
  not a bug.
- To test the real API locally: `npm run build`, apply the migration to
  the local D1 (`npx wrangler d1 execute mifrat-lists --local
  --file=migrations/0001_lists.sql`), then `npx wrangler dev` and open the
  printed URL.

## If something breaks

| Symptom | Cause / fix |
|---|---|
| Deploy fails mentioning `database_id` | Placeholder not replaced (step 1) |
| Short-link button does nothing, long URL stays | Worker not deployed or D1 missing — POST returns 500, client keeps the working long URL |
| `/list/xxxxxx` shows "link wasn't found" right after creating it | Migration not applied to the **remote** DB (step 2 needs `--remote`) |
| Whole site down after push | Unrelated to links would be surprising (static assets serve without the Worker), but `git revert` the commit and push — the previous deploy stays live until the new one succeeds |

Zero secrets are involved anywhere: no API tokens in the repo, no
environment variables — the Worker uses only its D1 + assets bindings.
