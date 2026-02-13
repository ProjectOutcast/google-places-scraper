import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class MomStoreScraper(BaseStrollerScraper):
    RETAILER_NAME = "Mom Store"
    BASE_URL = "https://www.momstore.ae"
    LISTING_URL = "https://www.momstore.ae/collections/strollers"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()
        page_num = 1

        while page_num <= 20:
            url = f"{self._get_start_url()}?page={page_num}" if page_num > 1 else self._get_start_url()
            await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(2)

            links = await page.query_selector_all("a[href*='/products/']")
            if not links:
                # Try search fallback
                if page_num == 1:
                    await page.goto(f"{self.BASE_URL}/search?q={self.keyword}", wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                    await asyncio.sleep(2)
                    links = await page.query_selector_all("a[href*='/products/']")
                if not links:
                    break

            new_count = 0
            for link in links:
                href = await link.get_attribute("href")
                if href and "/products/" in href:
                    clean = href.split("?")[0]
                    full = self._make_absolute(clean)
                    if full not in urls:
                        urls.add(full)
                        new_count += 1

            if new_count == 0:
                break
            page_num += 1
            await random_delay(1.5, 3.0)

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
            product.brand = await self._safe_text(page, ".product-vendor, [class*='vendor'], [class*='brand']")
        if not product.price:
            product.price = await self._safe_text(page, ".product-price, .price, [class*='price'] .money")
        if not product.description:
            product.description = await self._safe_text(page, ".product-description, [class*='description']")

        features = await self._safe_all_text(page, ".product-description li")
        if features:
            product.features = " ; ".join(features[:15])

        return product
