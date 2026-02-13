#!/usr/bin/env python3
"""
UAE Baby Product Scraper
========================
Scrapes baby products from 22 UAE online retailers.

Usage:
    python -m stroller_scraper.main                          # All retailers, default keyword
    python -m stroller_scraper.main --keyword cribs          # Search for cribs
    python -m stroller_scraper.main --retailers Mumzworld    # Specific retailer(s)
    python -m stroller_scraper.main --resume                 # Resume interrupted run
    python -m stroller_scraper.main --headful                # Show browser window
    python -m stroller_scraper.main --list                   # List all retailers
"""

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from retailers import get_scraper_registry
from exporter import export_combined_csv, normalize_product
from progress import ProgressTracker


async def run_all_scrapers(
    retailers=None,
    headless=True,
    resume=False,
    output_dir="output",
    keyword="strollers",
    progress_callback=None,
):
    """Main scraping orchestration. Can be called from CLI or Flask."""
    os.makedirs(output_dir, exist_ok=True)
    progress = ProgressTracker(output_dir)

    if not resume:
        progress.reset()

    def log(msg, percent=None):
        print(msg)
        if progress_callback:
            progress_callback(msg, percent)

    all_products = []
    registry = get_scraper_registry()
    targets = retailers or list(registry.keys())

    total = len(targets)
    completed = 0
    failed = []

    for name in targets:
        if name not in registry:
            log(f"[WARN] Unknown retailer: {name}")
            continue

        if resume and progress.is_retailer_done(name):
            log(f"[SKIP] {name} (already completed)")
            completed += 1
            continue

        retailer_pct = int((completed / total) * 100)
        log(f"Scraping: {name} ({completed + 1}/{total})", retailer_pct)

        scraper_cls = registry[name]
        scraper = scraper_cls(progress=progress, headless=headless, keyword=keyword)

        try:
            products = await scraper.run()
            products = [normalize_product(p) for p in products]
            all_products.extend(products)
            progress.mark_retailer_done(name)
            completed += 1

            partial_path = os.path.join(output_dir, "products_partial.csv")
            export_combined_csv(all_products, partial_path)
            log(f"[OK] {name}: {len(products)} products scraped", int((completed / total) * 100))

        except Exception as e:
            logging.exception(f"Failed to scrape {name}")
            progress.mark_retailer_failed(name, str(e))
            failed.append(name)
            log(f"[FAIL] {name}: {e}")

    log(f"DONE — {len(all_products)} products from {completed}/{total} retailers", 100)

    return all_products


def main():
    parser = argparse.ArgumentParser(
        description="Scrape baby products from UAE online retailers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--retailers", nargs="+", help="Specific retailer(s)")
    parser.add_argument("--keyword", default="strollers", help="Product keyword (default: strollers)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--headful", action="store_true", help="Show browser")
    parser.add_argument("--output", default="output/uae_products.csv", help="Output CSV")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--list", action="store_true", help="List retailers")

    args = parser.parse_args()

    if args.list:
        print("\nAvailable retailers:")
        for name in sorted(get_scraper_registry().keys()):
            print(f"  {name}")
        print(f"\nTotal: {len(get_scraper_registry())} retailers")
        return

    os.makedirs(args.output_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(args.output_dir, "scraper.log"), encoding="utf-8"),
        ],
    )

    products = asyncio.run(
        run_all_scrapers(
            retailers=args.retailers,
            headless=not args.headful,
            resume=args.resume,
            output_dir=args.output_dir,
            keyword=args.keyword,
        )
    )

    if products:
        export_combined_csv(products, args.output)
        print(f"\nOutput saved to: {args.output}")
        print(f"Total products: {len(products)}")
    else:
        print("\nNo products were scraped.")


if __name__ == "__main__":
    main()
