import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class BabyshopScraper(BaseStrollerScraper):
    """Babyshop (Landmark Group) - React/Next.js SPA."""
    RETAILER_NAME = "Babyshop"
    BASE_URL = "https://www.babyshopstores.com/ae/en"
    LISTING_URL = "https://www.babyshopstores.com/ae/en/c/baby-gear-strollersandprams-strollers"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(4)

        # Babyshop uses infinite scroll or Load More
        await self._scroll_to_bottom(page, pause=2.0, max_scrolls=40)

        # Also try clicking Load More / Show More
        for _ in range(20):
            btn = await page.query_selector(
                "button:has-text('Load More'), button:has-text('Show More'), "
                "[class*='loadMore'], [class*='showMore']"
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
            "a[href*='/p/'], a[href*='/product/'], "
            ".product-card a, .product-tile a, [class*='product'] a[href]"
        )
        for link in links:
            href = await link.get_attribute("href")
            if href:
                clean = href.split("?")[0]
                full = self._make_absolute(clean)
                urls.add(full)

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        product = StrollerProduct()

        # Try __NEXT_DATA__ for Next.js sites
        next_data = await self._extract_next_data(page)
        if next_data:
            try:
                props = next_data.get("props", {}).get("pageProps", {})
                prod_data = props.get("product", props.get("productData", {}))
                if prod_data:
                    product.product = prod_data.get("name", prod_data.get("title", ""))
                    product.brand = prod_data.get("brand", {}).get("name", "") if isinstance(prod_data.get("brand"), dict) else prod_data.get("brand", "")
                    product.description = prod_data.get("description", "")
                    price_info = prod_data.get("price", {})
                    if isinstance(price_info, dict):
                        product.price = f"AED {price_info.get('current', price_info.get('value', ''))}"
                    elif price_info:
                        product.price = f"AED {price_info}"
                    product.image_url = prod_data.get("image", prod_data.get("imageUrl", ""))
            except Exception:
                pass

        # JSON-LD fallback
        if not product.product:
            ld = await self._extract_json_ld(page)
            if ld:
                product.product = ld.get("name", "")
                product.description = ld.get("description", "")
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
            product.product = await self._safe_text(page, "h1")
        if not product.brand:
            product.brand = await self._safe_text(page, "[class*='brand'], .product-brand")
        if not product.price:
            product.price = await self._safe_text(page, "[class*='price'], .product-price")

        # Specs
        specs = await self._extract_spec_table(page, "[class*='spec'], [class*='detail'], table")
        product.weight = specs.get("weight", "")
        product.color = specs.get("color", specs.get("colour", ""))
        product.suitable_for = specs.get("suitable for", specs.get("age", ""))

        # Features
        features = await self._safe_all_text(page, "[class*='feature'] li, .product-description li")
        if features:
            product.features = " ; ".join(features[:15])

        return product
