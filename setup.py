from setuptools import setup, find_packages

setup(
    name="pc_parts_il",
    version="1.0",
    packages=find_packages(),
    entry_points={"scrapy": ["settings = scraper.settings"]},
)
