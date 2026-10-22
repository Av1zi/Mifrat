"""
scraper/icecat - Open Icecat product sheets (spec tier `catalog`, 0.75).

Open Icecat is the free tier of Icecat's product-data syndication catalog: the
brand's own structured spec sheet, served as JSON by part number or barcode.
It reaches brands whose own sites block us (Gigabyte, MSI answer 403) and
carries what retailer pages leave out (GPU fan counts, PSU connector counts,
case fan mounts, drive MTBF and warranty).

    python -m scraper.icecat --dry-run          # which products would be queried
    python -m scraper.icecat --limit 200        # fetch (cached), parse, write data/icecat/*.json
    python -m scraper.icecat --offline          # re-parse the cache only
    python -m scraper.icecat --trust            # Icecat vs sourced values, per field

Rules (same politeness as scraper/mfr, see its README):
- the documented JSON API only (live.icecat.biz/api), one request per second;
- a 429, or a 403 that is not Icecat's JSON "needs a Full Icecat key" answer,
  stops the run; nothing retries, no proxies;
- a sheet is used only when its own part number or one of its barcodes equals
  one of ours (Icecat's lookup is lenient; ours is not);
- values go through mfr.common.typed() (coerce + canon + validator);
- fields whose Icecat values disagree with sourced values more than
  mapping.TRUST_MAX_DISAGREE are listed in mapping.DISABLED and never merged.

Credentials: set ICECAT_USERNAME to a registered Open Icecat account (free at
icecat.biz). Without it the public `openIcecat-live` account is used and the
run says so.
"""
