import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class FirstCryScraper(BaseStrollerScraper):
    RETAILER_NAME = "FirstCry"
    BASE_URL = "https://www.firstcry.ae"
    LISTING_URL = "https://www.firstcry.ae/baby-strollers-and-prams/7/44"
    RETRY_DELAY = 8.0  # FirstCry has aggressive anti-bot

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        all_urls = set()
        page_num = 1

        while page_num <= 50:
            url = f"{self._get_start_url()}?page={page_num}" if page_num > 1 else self._get_start_url()
            await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(4)

            links = await page.query_selector_all(
                "a[href*='/product/'], a[href*='/productdetail/'], .product-card a, .product-box a, .product_link"
            )

            if not links:
                # Try broader selector
                links = await page.query_selector_all("a[href]")
                links_filtered = []
                for link in links:
                    href = await link.get_attribute("href")
                    if href and ("/product/" in href or "/productdetail/" in href):
                        links_filtered.append(link)
                links = links_filtered

            if not links:
                break

            new_count = 0
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    full = self._make_absolute(href.split("?")[0])
                    if full not in all_urls:
                        all_urls.add(full)
                        new_count += 1

            if new_count == 0:
                break

            page_num += 1
            await random_delay(3.0, 5.0)

        return list(all_urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        product = StrollerProduct()

        # JSON-LD
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

        # DOM fallbacks
        if not product.product:
            product.product = await self._safe_text(page, "h1.product-title, h1.product-name, h1[class*='title'], h1")

        if not product.brand:
            product.brand = await self._safe_text(page, ".brand-name a, .product-brand, [class*='brand'] a")

        if not product.price:
            product.price = await self._safe_text(page, ".selling-price, .offer-price, .final-price, [class*='price']:not([class*='original'])")

        if not product.description:
            product.description = await self._safe_text(page, ".product-description, #product-desc, [class*='description']")

        # Key Features
        features = await self._safe_all_text(page, ".key-features li, .product-features li, [class*='feature'] li")
        if features:
            product.features = " ; ".join(features[:15])

        # Specs table
        specs = await self._extract_spec_table(page, ".specifications, .product-specs, [class*='specification']")
        if not specs:
            specs = await self._extract_spec_table(page, "table")

        product.weight = specs.get("weight", specs.get("product weight", ""))
        product.color = specs.get("color", specs.get("colour", ""))
        product.frame_color = specs.get("frame color", specs.get("frame colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("age", specs.get("age group", "")))

        return product
