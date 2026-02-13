import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class BabiesAndMoreScraper(BaseStrollerScraper):
    RETAILER_NAME = "Babies and More"
    BASE_URL = "https://www.babiesandmore.com"
    LISTING_URL = "https://www.babiesandmore.com/en-ae/strollers"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()

        for try_url in [
            self._get_start_url(),
            f"{self.BASE_URL}/en-ae/search?q={self.keyword}",
            f"{self.BASE_URL}/en-ae/catalogsearch/result/?q={self.keyword}",
        ]:
            try:
                await page.goto(try_url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(3)
            except Exception:
                continue

            await self._scroll_to_bottom(page, pause=1.5, max_scrolls=20)

            links = await page.query_selector_all(
                "a[href*='/product'], a[href*='/products/'], "
                ".product-card a, .product-item a, [class*='product'] a[href]"
            )
            for link in links:
                href = await link.get_attribute("href")
                if href and len(href.split("/")[-1]) > 5:
                    clean = href.split("?")[0]
                    full = self._make_absolute(clean)
                    if not any(x in full for x in ["/category", "/search", "/cart", "/strollers"]):
                        urls.add(full)

            if urls:
                break

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(2)

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
            product.product = await self._safe_text(page, "h1")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand, .product-vendor")
        if not product.price:
            product.price = await self._safe_text(page, "[class*='price'], .product-price")
        if not product.description:
            product.description = await self._safe_text(page, "[class*='description'], .product-description")

        features = await self._safe_all_text(page, "[class*='description'] li")
        if features:
            product.features = " ; ".join(features[:15])

        specs = await self._extract_spec_table(page, "table, [class*='spec']")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("age", ""))

        return product
