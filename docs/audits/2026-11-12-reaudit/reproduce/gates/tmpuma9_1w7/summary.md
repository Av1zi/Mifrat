### Golden spec fixtures

**pass (identity churn)** — 0 assertions over 0 product(s), 1 case(s).

| | count |
| :--- | ---: |
| resolved by own product id | 0 |
| resolved through an anchor (re-keyed) | 0 |
| no product at all (budget 2) | 1 |
| products re-keyed since the baseline | 0 |

**Missing cases**

- mpn:motherboard:gone (Test board)

Repair: `python -m scraper.specs.golden.check_golden --update-anchors --apply` after a normalize run, or retire the case with a `_pins` note.
