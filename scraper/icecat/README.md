# `scraper/icecat/` - Open Icecat product sheets (tier 0.75, `catalog`)

Icecat syndicates brands' own spec sheets to retailers. Its free tier, Open
Icecat, answers by brand + part number or by barcode with a structured JSON
sheet. It reaches brands whose sites block us (Gigabyte and MSI answer 403 to
any client) and carries facts Israeli retailers rarely print: GPU fan counts and
real port counts, PSU connector counts, case fan mounts and radiator lists,
drive cache / MTBF / warranty, memory module layouts.

```bash
python -m scraper.icecat --dry-run              # how many lookups a full run asks
python -m scraper.icecat --brand gigabyte       # one brand (merges into its file)
python -m scraper.icecat                        # everything (~1 h at 1 req/s, cached)
python -m scraper.icecat --offline              # re-parse the cache, no network

# trust: compare against a catalog built WITHOUT Icecat
MIFRAT_NO_ICECAT=1 python -m scraper.normalize_and_match
python -m scraper.icecat --trust
python -m scraper.normalize_and_match           # then rebuild with it
```

## Rules

- The documented JSON API only (`live.icecat.biz/api`), one request per second,
  every answer cached under `data/icecat/.cache/` (gitignored). Only the
  extracted `data/icecat/<brand>.json` files are committed.
- Icecat answers a product that exists only in its paid catalog with HTTP 403
  plus a JSON `StatusCode: 9`. That is "not open", not a block. A 429, or a 403
  without that JSON, stops the run. Nothing retries, and no proxies are used.
- A sheet is used only when its own part number or one of its barcodes equals
  one of ours. Icecat's lookup is lenient (it returns neighbours); ours is not.
  The first Gigabyte run rejected 33 such answers.
- Israeli vendors drop Gigabyte's `GV-` prefix from card order codes, so that
  variant is asked too (`runner._variants`).
- Values go through `mfr.common.typed()`: coerce, canonical form, validator.
- Set `ICECAT_USERNAME` to a registered (free) Open Icecat account. Without it
  the public `openIcecat-live` account is used and the run says so.

## Field trust (`mapping.DISABLED` / `mapping.REVIEWED_OVER`)

Every mapped field is compared with the vendor / maker / reference value of the
same product (`--trust`). A field disagreeing more than 3% on 10+ products is
either disabled, or, when a review shows the retailer side is the one that is
wrong, listed in `REVIEWED_OVER` with the evidence.

| Field | Verdict | Why |
| :--- | :--- | :--- |
| storage `nand` | disabled | the 990 PRO sheet says MLC; Samsung says TLC |
| motherboard `pcie_x16_slots`, `ecc_support` | disabled | counts every x16-length slot; "ECC & non-ECC" on consumer Intel boards |
| motherboard `color`, `memory_max_gb`, `pcie_x1_slots` | disabled | "Brown" black boards; BIOS-dependent memory ceilings; x1 off by one |
| gpu `length_mm`, `memory_speed_gbps`, `recommended_psu_w` | disabled | length is sometimes the height; data rate / PSU differ from chip and partner figures |
| gpu `dp_outputs`, `hdmi_outputs` | enabled (reviewed) | the retailer cells listed port kinds and our parser read one of each; fixed in `vendor_struct._emit_gpu_outputs` |
| motherboard `wireless` | enabled (reviewed) | retailers print "Wi-Fi 6" for Gigabyte AX boards with Wi-Fi 6E modules |
| gpu `color` | enabled (reviewed) | the one miss is a white AERO card a retailer lists as black |

Coverage measured on the first Gigabyte run: 193 of 349 products got a sheet.
Brands that only answered "needs a Full Icecat key" (Corsair, Cooler Master,
Crucial, WD, Lian Li, Palit, Sapphire) need a paid account, which was declined
(Oct 2026).
