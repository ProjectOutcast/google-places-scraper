import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class OunassScraper(BaseStrollerScraper):
    """Ounass - Luxury SPA retailer with aggressive anti-bot."""
    RETAILER_NAME = "Ounass"
    BASE_URL = "https://www.ounass.ae"
    LISTING_URL = "https://www.ounass.ae/kids/accessories/strollers/"
    RETRY_DELAY = 8.0

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(4)

        # Scroll to load all products
        await self._scroll_to_bottom(page, pause=2.0, max_scrolls=30)

        urls = set()
        links = await page.query_selector_all(
            "a[href*='/product/'], a[href*='/en-ae/'], "
            ".product-card a, .ProductCard a, [class*='product'] a[href]"
        )
        for link in links:
            href = await link.get_attribute("href")
            if href and ("/product/" in href or len(href.split("/")[-1]) > 15):
                clean = href.split("?")[0]
                full = self._make_absolute(clean)
                # Exclude category/listing pages
                if not any(x in full for x in ["/kids/", "/accessories/", "/strollers/"]) or full.count("/") > 5:
                    urls.add(full)

        # Fallback: try paginated approach
        if not urls:
            page_num = 1
            while page_num <= 10:
                url = f"{self._get_start_url()}?page={page_num}" if page_num > 1 else self._get_start_url()
                await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(3)

                links = await page.query_selector_all("a[href]")
                found = False
                for link in links:
                    href = await link.get_attribute("href")
                    if href and "/product/" in href:
                        urls.add(self._make_absolute(href.split("?")[0]))
                        found = True

                if not found:
                    break
                page_num += 1
                await random_delay(3.0, 6.0)

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        product = StrollerProduct()

        # JSON-LD (Ounass often has it)
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

        # DOM
        if not product.product:
            product.product = await self._safe_text(page, "h1, [class*='product-name'], [data-testid='product-name']")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], [data-testid='product-brand']")
        if not product.price:
            product.price = await self._safe_text(page, "[class*='price'], [data-testid='product-price']")

        # Expand details section
        try:
            details_btn = await page.query_selector("button:has-text('Details'), button:has-text('Description'), [class*='details-toggle']")
            if details_btn:
                await details_btn.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

        if not product.description:
            product.description = await self._safe_text(page, "[class*='detail'], [class*='description']")

        # Features
        features = await self._safe_all_text(page, "[class*='detail'] li, [class*='feature'] li")
        if features:
            product.features = " ; ".join(features[:15])

        # Color
        product.color = await self._safe_text(page, "[class*='color-name'], [class*='colorName'], [class*='selected-color']")

        return product
