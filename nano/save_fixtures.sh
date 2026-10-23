#!/usr/bin/env bash
# Save a few real pages from sites that answer an honestly identified client from
# the Nano's home IP but not from the cloud (Supermicro, LDLC), so the parsers can
# be written and tested against them. Plain wget, the honest bot name, one request
# every 3 seconds, ~10 pages in total. A 403/429 stops that site: nothing retries.
#
#   bash nano/save_fixtures.sh && git add scraper/fixtures && git commit -m "fixtures: Nano pages" && git push
set -u
UA="MifratSpecBot/1.0 (+https://github.com/Av1zi/Mifrat; ziv.avivi.28.11@gmail.com)"
OUT="$(cd "$(dirname "$0")/.." && pwd)/scraper/fixtures"
mkdir -p "$OUT/supermicro" "$OUT/ldlc"

get() {  # get <url> <file>: prints the status line, keeps the body only on 200
  local url="$1" file="$2" status
  status=$(wget -S -q -U "$UA" -O "$file.tmp" "$url" 2>&1 | grep -m1 "HTTP/" | awk '{print $2}')
  if [ -s "$file.tmp" ] && [ "${status:-0}" = "200" ]; then mv "$file.tmp" "$file"; else rm -f "$file.tmp"; fi
  echo "${status:-none}  $url"
  sleep 3
}

# Supermicro: product pages for catalog boards / cases (robots.txt allows /en/products/).
for slug in motherboard/h12ssl-i motherboard/c9z790-cgw motherboard/c9z890-mw \
            chassis/4u/846/sc846be1c-r1k23b; do
  get "https://www.supermicro.com/en/products/$slug" "$OUT/supermicro/$(echo "$slug" | tr '/' '_').html"
done

# LDLC: a search per part number, then the first product page it lists.
for term in CP-9020247-EU GV-N5070WF3OC-12GD KF560C36BBE2-32 NH-U12A; do
  f="$OUT/ldlc/search_$term.html"
  get "https://www.ldlc.com/en/search/$term/" "$f"
  [ -f "$f" ] || continue
  link=$(grep -o -E 'href="[^"]*/(fiche|product)/PB[0-9A-Za-z]+\.html"' "$f" | head -1 | sed -E 's/^href="//; s/"$//')
  [ -n "$link" ] || { echo "no product link in the $term search page"; continue; }
  case "$link" in http*) ;; *) link="https://www.ldlc.com$link" ;; esac
  get "$link" "$OUT/ldlc/product_$term.html"
done
ls -la "$OUT/supermicro" "$OUT/ldlc"
