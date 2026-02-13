import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class BloomingdalesScraper(BaseStrollerScraper):
    """Bloomingdale's UAE - searches for strollers within kids section."""
    RETAILER_NAME = "Bloomingdales"
    BASE_URL = "https://www.bloomingdales.ae"
    LISTING_URL = "https://www.bloomingdales.ae/kids-baby/"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        # Try direct search for strollers
        search_url = f"{self.BASE_URL}/search?q={self.keyword}"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(4)

        # Scroll to load all results
        await self._scroll_to_bottom(page, pause=2.0, max_scrolls=30)

        urls = set()
        links = await page.query_selector_all(
            "a[href*='/product/'], a[href*='/kids/'], "
            ".product-card a, .product-tile a, [class*='product'] a[href]"
        )
        for link in links:
            href = await link.get_attribute("href")
            if href and ("/product/" in href or ("/kids" in href and href.count("/") > 3)):
                clean = href.split("?")[0]
                full = self._make_absolute(clean)
                if full != f"{self.BASE_URL}/kids-baby/":
                    urls.add(full)

        # Also try the kids-baby category page
        if not urls:
            await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(3)
            await self._scroll_to_bottom(page, pause=2.0, max_scrolls=20)

            links = await page.query_selector_all("a[href]")
            for link in links:
                href = await link.get_attribute("href")
                if href and "stroller" in href.lower():
                    urls.add(self._make_absolute(href.split("?")[0]))

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        product = StrollerProduct()

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

        if not product.product:
            product.product = await self._safe_text(page, "h1, [class*='product-name']")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand")
        if not product.price:
            product.price = await self._safe_text(page, "[class*='price']")
        if not product.description:
            product.description = await self._safe_text(page, "[class*='description'], .product-details")

        features = await self._safe_all_text(page, "[class*='feature'] li, .product-description li")
        if features:
            product.features = " ; ".join(features[:15])

        specs = await self._extract_spec_table(page, "[class*='spec'], table")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))

        return product
