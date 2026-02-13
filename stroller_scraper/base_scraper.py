import asyncio
import logging
import json
from abc import ABC, abstractmethod
from typing import List, Optional
from playwright.async_api import async_playwright, Page, BrowserContext

from models import StrollerProduct
from anti_bot import get_random_user_agent, random_delay, setup_stealth
from progress import ProgressTracker
from config import RETAILERS, DEFAULT_KEYWORD


class BaseStrollerScraper(ABC):
    RETAILER_NAME: str = ""
    BASE_URL: str = ""
    LISTING_URL: str = ""
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 5.0
    PAGE_LOAD_TIMEOUT: int = 30000

    def __init__(self, progress: ProgressTracker, headless: bool = True, keyword: str = ""):
        self.progress = progress
        self.headless = headless
        self.keyword = keyword or DEFAULT_KEYWORD
        self.logger = logging.getLogger(f"scraper.{self.RETAILER_NAME}")
        self.products: List[StrollerProduct] = []

    def _get_start_url(self) -> str:
        """Return search URL when keyword differs from default, otherwise listing URL."""
        if self.keyword.lower() != DEFAULT_KEYWORD:
            cfg = RETAILERS.get(self.RETAILER_NAME, {})
            search_tpl = cfg.get("search_url", "")
            if search_tpl:
                return search_tpl.format(keyword=self.keyword)
        return self.LISTING_URL

    async def run(self) -> List[StrollerProduct]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent=get_random_user_agent(),
                viewport={"width": 1920, "height": 1080},
                locale="en-AE",
                timezone_id="Asia/Dubai",
            )
            page = await context.new_page()
            await setup_stealth(page)

            try:
                await self._dismiss_cookies(page)
                product_urls = await self._get_all_product_urls(page)
                self.logger.info(f"Found {len(product_urls)} product URLs for {self.RETAILER_NAME}")
                print(f"  Found {len(product_urls)} product URLs")

                for i, url in enumerate(product_urls):
                    if self.progress.is_already_scraped(self.RETAILER_NAME, url):
                        continue

                    product = await self._scrape_with_retry(page, url)
                    if product:
                        product.retailer = self.RETAILER_NAME
                        product.link = url
                        self.products.append(product)
                        self.progress.mark_scraped(self.RETAILER_NAME, url)

                    await random_delay(1.5, 4.0)

                    if (i + 1) % 5 == 0 or i + 1 == len(product_urls):
                        self.progress.update(self.RETAILER_NAME, i + 1, len(product_urls))

            finally:
                await browser.close()

        return self.products

    async def _scrape_with_retry(self, page: Page, url: str) -> Optional[StrollerProduct]:
        for attempt in range(self.MAX_RETRIES):
            try:
                product = await self._scrape_product_page(page, url)
                return product
            except Exception as e:
                self.logger.warning(
                    f"Attempt {attempt + 1}/{self.MAX_RETRIES} failed for {url}: {e}"
                )
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))
        return None

    @abstractmethod
    async def _get_all_product_urls(self, page: Page) -> List[str]:
        ...

    @abstractmethod
    async def _scrape_product_page(self, page: Page, url: str) -> Optional[StrollerProduct]:
        ...

    # ── Shared helpers ──

    async def _safe_text(self, page_or_el, selector: str, default: str = "") -> str:
        try:
            el = await page_or_el.query_selector(selector)
            if el:
                text = await el.inner_text()
                return text.strip()
        except Exception:
            pass
        return default

    async def _safe_attr(self, page_or_el, selector: str, attr: str, default: str = "") -> str:
        try:
            el = await page_or_el.query_selector(selector)
            if el:
                val = await el.get_attribute(attr)
                return val.strip() if val else default
        except Exception:
            pass
        return default

    async def _safe_all_text(self, page_or_el, selector: str) -> List[str]:
        try:
            elements = await page_or_el.query_selector_all(selector)
            texts = []
            for el in elements:
                text = await el.inner_text()
                t = text.strip()
                if t:
                    texts.append(t)
            return texts
        except Exception:
            return []

    async def _extract_spec_table(self, page: Page, selector: str) -> dict:
        specs = {}
        try:
            rows = await page.query_selector_all(f"{selector} tr")
            for row in rows:
                label = await self._safe_text(row, "th, td:first-child, .label, dt")
                value = await self._safe_text(row, "td:last-child, .value, dd")
                if label and value and label != value:
                    specs[label.lower().strip().rstrip(":")] = value
        except Exception:
            pass

        # Also try dl/dt/dd pattern
        try:
            dts = await page.query_selector_all(f"{selector} dt")
            dds = await page.query_selector_all(f"{selector} dd")
            for dt, dd in zip(dts, dds):
                label = (await dt.inner_text()).strip().lower().rstrip(":")
                value = (await dd.inner_text()).strip()
                if label and value:
                    specs[label] = value
        except Exception:
            pass

        return specs

    async def _extract_json_ld(self, page: Page) -> Optional[dict]:
        try:
            result = await page.evaluate("""
                () => {
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    for (const s of scripts) {
                        try {
                            const data = JSON.parse(s.textContent);
                            if (data['@type'] === 'Product') return data;
                            if (Array.isArray(data)) {
                                const p = data.find(d => d['@type'] === 'Product');
                                if (p) return p;
                            }
                            if (data['@graph']) {
                                const p = data['@graph'].find(d => d['@type'] === 'Product');
                                if (p) return p;
                            }
                        } catch {}
                    }
                    return null;
                }
            """)
            return result
        except Exception:
            return None

    async def _extract_next_data(self, page: Page) -> Optional[dict]:
        try:
            result = await page.evaluate("""
                () => {
                    const el = document.getElementById('__NEXT_DATA__');
                    return el ? JSON.parse(el.textContent) : null;
                }
            """)
            return result
        except Exception:
            return None

    async def _scroll_to_bottom(self, page: Page, pause: float = 1.0, max_scrolls: int = 50):
        previous_height = 0
        for _ in range(max_scrolls):
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == previous_height:
                break
            previous_height = current_height
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(pause)

    async def _dismiss_cookies(self, page: Page):
        """Try to dismiss cookie consent banners."""
        cookie_selectors = [
            "button:has-text('Accept')",
            "button:has-text('Accept All')",
            "button:has-text('Accept Cookies')",
            "button:has-text('Got it')",
            "button:has-text('OK')",
            "[data-testid='cookie-accept']",
            ".cookie-accept",
            "#cookie-accept",
            ".accept-cookies",
        ]
        for selector in cookie_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    break
            except Exception:
                continue

    def _make_absolute(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("/"):
            return f"{self.BASE_URL}{url}"
        return f"{self.BASE_URL}/{url}"
