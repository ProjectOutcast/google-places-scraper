import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class MothercareScraper(BaseStrollerScraper):
    RETAILER_NAME = "Mothercare"
    BASE_URL = "https://www.mothercare.ae/en"
    LISTING_URL = "https://www.mothercare.ae/en/shop-strollers"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        await page.goto(self._get_start_url(), wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

        # Try Load More button first
        for _ in range(30):
            btn = await page.query_selector(
                "button:has-text('Load More'), button:has-text('Show More'), "
                ".load-more-btn, .btn-load-more, [class*='loadMore']"
            )
            if not btn:
                break
            try:
                visible = await btn.is_visible()
                if not visible:
                    break
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await asyncio.sleep(2)
                await random_delay(0.5, 1.5)
            except Exception:
                break

        # If no load more, try infinite scroll
        await self._scroll_to_bottom(page, pause=2.0, max_scrolls=30)

        urls = set()
        links = await page.query_selector_all(
            ".product-tile a[href], .product-card a[href], "
            "a[href*='/stroller'], a[href*='/pushchair'], "
            "[class*='product'] a[href]"
        )

        for link in links:
            href = await link.get_attribute("href")
            if href and not any(x in href for x in ["/shop-strollers", "/category", "/cart"]):
                clean = href.split("?")[0]
                full = self._make_absolute(clean)
                if full not in urls and len(clean) > 20:
                    urls.add(full)

        # Fallback: paginated URLs
        if not urls:
            page_num = 1
            while page_num <= 30:
                url = f"{self._get_start_url()}?page={page_num}" if page_num > 1 else self._get_start_url()
                await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(2)

                links = await page.query_selector_all("a[href]")
                found = False
                for link in links:
                    href = await link.get_attribute("href")
                    if href and "/en/" in href and len(href.split("/")[-1]) > 10:
                        clean = href.split("?")[0]
                        full = self._make_absolute(clean)
                        if full not in urls:
                            urls.add(full)
                            found = True

                if not found:
                    break
                page_num += 1
                await random_delay(2.0, 4.0)

        return list(urls)

    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(2)

        product = StrollerProduct()

        # JSON-LD first
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
            product.product = await self._safe_text(page, "h1.product-name, h1.pdp-title, h1")

        if not product.brand:
            product.brand = await self._safe_text(page, ".product-brand, .brand-name, [class*='brand']")

        if not product.price:
            product.price = await self._safe_text(
                page, ".product-price .sale-price, .product-price .price, "
                "[class*='price'] [class*='sale'], [class*='price']"
            )

        # Specs
        specs = await self._extract_spec_table(page, ".product-specifications, .product-attributes, .pdp-specs, table")

        product.weight = specs.get("weight", specs.get("product weight", ""))
        product.color = specs.get("colour", specs.get("color", ""))
        product.frame_color = specs.get("frame colour", specs.get("frame color", ""))
        product.suitable_for = specs.get("suitable from", specs.get("suitable for",
                                  specs.get("age range", specs.get("age", ""))))

        # Features
        features = await self._safe_all_text(
            page, ".product-features li, .key-features li, "
            "[class*='feature'] li, .product-description ul li"
        )
        if features:
            product.features = " ; ".join(features[:15])

        # Expand Read More for description
        if not product.description:
            try:
                read_more = await page.query_selector("button:has-text('Read More'), .read-more-btn")
                if read_more:
                    await read_more.click()
                    await asyncio.sleep(0.5)
            except Exception:
                pass
            product.description = await self._safe_text(page, ".product-description, .pdp-description, [class*='description']")

        return product
