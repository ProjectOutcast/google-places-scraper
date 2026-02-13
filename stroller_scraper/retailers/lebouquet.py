import asyncio
from typing import List, Optional
from playwright.async_api import Page

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_scraper import BaseStrollerScraper
from models import StrollerProduct
from anti_bot import random_delay


class LeBouquetScraper(BaseStrollerScraper):
    """Le Bouquet Baby - Shopify-based store."""
    RETAILER_NAME = "Le Bouquet"
    BASE_URL = "https://www.lebouquetbaby.com"
    LISTING_URL = "https://www.lebouquetbaby.com/collections/strollers-prams"

    async def _get_all_product_urls(self, page: Page) -> List[str]:
        urls = set()
        page_num = 1

        while page_num <= 20:
            url = f"{self._get_start_url()}?page={page_num}" if page_num > 1 else self._get_start_url()
            await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(2)

            links = await page.query_selector_all(
                "a[href*='/products/'], .product-card a, .grid-product a, "
                ".product-item a, [class*='product'] a[href*='/products/']"
            )

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

        # Shopify stores often have JSON-LD
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

        # Shopify product JSON via JavaScript
        shopify_data = await page.evaluate("""
            () => {
                if (window.ShopifyAnalytics && window.ShopifyAnalytics.meta && window.ShopifyAnalytics.meta.product) {
                    return window.ShopifyAnalytics.meta.product;
                }
                return null;
            }
        """)
        if shopify_data:
            if not product.product:
                product.product = shopify_data.get("title", "")
            if not product.brand:
                product.brand = shopify_data.get("vendor", "")
            if not product.price:
                price_val = shopify_data.get("price", "")
                if price_val:
                    # Shopify prices are in cents
                    try:
                        product.price = f"AED {int(price_val) / 100:.2f}"
                    except (ValueError, TypeError):
                        product.price = str(price_val)

        # DOM fallbacks
        if not product.product:
            product.product = await self._safe_text(page, "h1.product-title, h1.product__title, h1")

        if not product.brand:
            product.brand = await self._safe_text(page, ".product-vendor, .product__vendor, [class*='vendor']")

        if not product.price:
            product.price = await self._safe_text(page, ".product-price, .price, [class*='price'] .money")

        if not product.description:
            product.description = await self._safe_text(page, ".product-description, .product__description, [class*='description']")

        # Features from description bullet points
        features = await self._safe_all_text(page, ".product-description li, .product__description li")
        if features:
            product.features = " ; ".join(features[:15])

        # Color from variant selector
        product.color = await self._safe_text(page, ".swatch-label, [class*='variant'] [class*='color'], .color-swatch.active")

        return product
