import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class MamasAndPapasScraper(BaseStrollerScraper):
    RETAILER_NAME = "Mamas & Papas"
    BASE_URL = "https://www.mamasandpapas.ae"
    LISTING_URL = "https://www.mamasandpapas.ae/travel-strollers-carrycots-all-strollers/"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        # Scroll to load all and try load more
        await self._scroll_to_bottom(page, pause=2.0, max_scrolls=30)

        for _ in range(20):
            btn = await page.query_selector(
                "button:has-text('Load More'), button:has-text('Show More'), "
                "a:has-text('Load More'), [class*='loadMore']"
            )
            if not btn:
                break
            try:
                if not await btn.is_visible():
                    break
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await asyncio.sleep(2)
            except Exception:
                break

        urls = set()
        links = await page.query_selector_all(
            "a[href*='/product/'], a[href*='/stroller'], "
            ".product-card a, .product-tile a, [class*='product'] a[href]"
        )
        for link in links:
            href = await link.get_attribute("href")
            if href and not any(x in href for x in ["/travel-strollers", "/category", "/cart", "#"]):
                clean = href.split("?")[0]
                full = self._make_absolute(clean)
                if len(clean.split("/")[-1]) > 5:
                    urls.add(full)

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
            product.brand = "Mamas & Papas"  # Own brand store
        if not product.price:
            product.price = await self._safe_text(page, "[class*='price'], .product-price")
        if not product.description:
            product.description = await self._safe_text(page, "[class*='description'], .product-description")

        features = await self._safe_all_text(page, "[class*='feature'] li, .product-description li, [class*='detail'] li")
        if features:
            product.features = " ; ".join(features[:15])

        specs = await self._extract_spec_table(page, "[class*='spec'], table")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))
        product.suitable_for = specs.get("suitable from", specs.get("suitable for", specs.get("age", "")))

        return product
