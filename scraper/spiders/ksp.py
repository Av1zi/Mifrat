"""
KSP spider — STRETCH GOAL, Phase 5 only. Do not build this yet.

Per plan §10/§16: KSP is flagged as hard (WAF/bot-management), and the
official-API application (submitted in Phase 0) is the preferred path over
scraping around its defenses. This file exists only so the repo layout
matches §14 and this vendor can be isolated without touching the other four.

If you're an agent picking this up and tempted to "just try scraping KSP
anyway" — don't, without checking:
  1. Did the Phase 0 API application get approved? If yes, integrate via API,
     not scraping — skip this file's approach entirely.
  2. Are the other four vendors (TMS, Ivory, 1PC, Plonter) fully working
     end to end, matched, and stable? If not, this is not the priority.
  3. Per §10: don't build anything specifically designed to defeat CAPTCHA
     or spoof detection signatures. If KSP's bot defenses block a slow,
     realistic, low-volume scrape, that's a signal to stop for this vendor,
     not to escalate the scraping technique.
"""
import scrapy


class KspSpider(scrapy.Spider):
    name = "ksp"
    allowed_domains = ["ksp.co.il"]
    start_urls = []  # intentionally empty — do not enable until Phase 5

    def parse(self, response):
        raise NotImplementedError(
            "KSP is a Phase 5 stretch goal. Check the official API "
            "application status before doing anything here."
        )
