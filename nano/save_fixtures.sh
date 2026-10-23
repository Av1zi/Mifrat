#!/usr/bin/env bash
# Save real LDLC pages (answers an honestly identified client from the Nano's
# home IP, not from the cloud), so the parsers can
# be written and tested against them. Plain wget, the honest bot name, one request
# every 3 seconds, ~26 pages in total (~2 minutes). A 403/429 stops that site: nothing retries.
#
#   bash nano/save_fixtures.sh && git add scraper/fixtures && git commit -m "fixtures: Nano pages" && git push
set -u
UA="MifratSpecBot/1.0 (+https://github.com/Av1zi/Mifrat; ziv.avivi.28.11@gmail.com)"
OUT="$(cd "$(dirname "$0")/.." && pwd)/scraper/fixtures"
mkdir -p "$OUT/ldlc"

get() {  # get <url> <file>: prints the status line, keeps the body only on 200
  local url="$1" file="$2" status
  status=$(wget -S -q -U "$UA" -O "$file.tmp" "$url" 2>&1 | grep -m1 "HTTP/" | awk '{print $2}')
  if [ -s "$file.tmp" ] && [ "${status:-0}" = "200" ]; then mv "$file.tmp" "$file"; else rm -f "$file.tmp"; fi
  echo "${status:-none}  $url"
  sleep 3
}

# LDLC: a search per part number, then the first product page it lists.
# One or two real catalog part numbers per category, so every category's label
# vocabulary is on disk before its parser is written (cooler pages are saved).
for term in PC-A4H2OA4 90MB1JZ0-M0EAY0 AORUS-WATERFORCE-II-360 BW029EU 12ALV23W \
            90YV06N2-M0NA00 CB8GU3200 CMG16GX4M1E3200C16 7E19-001R 12102PXAFS \
            0B36404 CP-9020247-EU KF560C36BBE2-32; do
  f="$OUT/ldlc/search_$term.html"
  get "https://www.ldlc.com/en/search/$term/" "$f"
  [ -f "$f" ] || continue
  link=$(grep -o -E 'href="[^"]*/(fiche|product)/PB[0-9A-Za-z]+\.html"' "$f" | head -1 | sed -E 's/^href="//; s/"$//')
  [ -n "$link" ] || { echo "no product link in the $term search page"; continue; }
  case "$link" in http*) ;; *) link="https://www.ldlc.com$link" ;; esac
  get "$link" "$OUT/ldlc/product_$term.html"
done
ls "$OUT/ldlc"
