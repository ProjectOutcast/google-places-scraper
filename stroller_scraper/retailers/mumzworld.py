import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class MumzworldScraper(BaseStrollerScraper):
    RETAILER_NAME = "Mumzworld"
    BASE_URL = "https://www.mumzworld.com"
    LISTING_URL = "https://www.mumzworld.com/en/travel-gear/strollers-prams"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        # Mumzworld uses infinite scroll with Algolia backend
        await self._scroll_to_bottom(page, pause=2.0, max_scrolls=60)

        urls = set()
        links = await page.query_selector_all("a[href*='/en/']")
        for link in links:
            href = await link.get_attribute("href")
            if href and "/en/" in href and not any(x in href for x in [
                "/travel-gear", "/strollers-prams", "/brand", "/category",
                "/cart", "/account", "/wishlist", "/checkout",
            ]):
                # Product URLs typically have a long slug with SKU
                parts = href.split("/en/")
                if len(parts) > 1 and len(parts[1]) > 20 and "-" in parts[1]:
                    clean = href.split("?")[0]
                    urls.add(self._make_absolute(clean))

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(2)

        product = StrollerProduct()

        # Try JSON-LD first (most reliable)
        ld = await self._extract_json_ld(page)
        if ld:
            product.product = ld.get("name", "")
            product.description = ld.get("description", "")
            product.image_url = ld.get("image", "")
            if isinstance(product.image_url, list):
                product.image_url = product.image_url[0] if product.image_url else ""
            offers = ld.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if offers.get("price"):
                product.price = f"AED {offers['price']}"
            brand_info = ld.get("brand", {})
            if isinstance(brand_info, dict):
                product.brand = brand_info.get("name", "")

        # Fallback / supplement with DOM
        if not product.product:
            product.product = await self._safe_text(page, "h1")

        if not product.brand:
            product.brand = await self._safe_text(page, "a[href*='/en/'][class*='brand'], a[href*='brand']")

        if not product.price:
            product.price = await self._safe_text(page, "[class*='price'] span, [class*='Price']")

        # Extract specs from Overview/Details section
        # Mumzworld uses dt/dd pairs in specs
        specs = await self._extract_spec_table(page, "[class*='spec'], [class*='overview'], [class*='detail']")

        # Also try extracting from all dt/dd on page
        if not specs:
            specs = await self._extract_all_specs(page)

        product.weight = specs.get("weight", specs.get("product weight", specs.get("item weight", "")))
        product.color = specs.get("color", specs.get("colour", ""))
        product.frame_color = specs.get("frame color", specs.get("frame colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("recommended age",
                                  specs.get("age range", specs.get("age", ""))))

        # Features from bullet list
        if not product.description:
            features_list = await self._safe_all_text(page, "ul li")
            # Filter to likely product features (not nav items)
            features = [f for f in features_list if len(f) > 10 and len(f) < 200]
            if features:
                product.features = " ; ".join(features[:15])

        return product

    async def _extract_all_specs(self, page: Page) -> dict:
        specs = {}
        try:
            pairs = await page.evaluate("""
                () => {
                    const specs = {};
                    const dts = document.querySelectorAll('dt');
                    dts.forEach(dt => {
                        const dd = dt.nextElementSibling;
                        if (dd && dd.tagName === 'DD') {
                            specs[dt.textContent.trim().toLowerCase().replace(':', '')] = dd.textContent.trim();
                        }
                    });
                    return specs;
                }
            """)
            if pairs:
                specs.update(pairs)
        except Exception:
            pass
        return specs
