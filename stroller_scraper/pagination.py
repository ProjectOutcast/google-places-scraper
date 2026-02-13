import asyncio
from anti_bot import random_delay


async def paginate_by_url(page, base_url, param_name="page", start=1,
                          max_pages=50, product_selector="a", base_url_has_params=False):
    all_urls = []
    for page_num in range(start, start + max_pages):
        sep = "&" if base_url_has_params else "?"
        url = f"{base_url}{sep}{param_name}={page_num}" if page_num > start else base_url
        await page.goto(url, wait_until="networkidle", timeout=30000)

        links = await page.query_selector_all(product_selector)
        if not links:
            break

        new_urls = []
        for link in links:
            href = await link.get_attribute("href")
            if href:
                new_urls.append(href)

        if not new_urls:
            break

        all_urls.extend(new_urls)
        await random_delay(1.5, 3.0)

    return list(dict.fromkeys(all_urls))


async def paginate_by_load_more(page, button_selector, product_selector,
                                 max_clicks=30, wait_after_click=2.0):
    for _ in range(max_clicks):
        btn = await page.query_selector(button_selector)
        if not btn:
            break
        try:
            visible = await btn.is_visible()
            if not visible:
                break
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await asyncio.sleep(wait_after_click)
            await random_delay(0.3, 1.0)
        except Exception:
            break

    links = await page.query_selector_all(product_selector)
    urls = []
    for link in links:
        href = await link.get_attribute("href")
        if href:
            urls.append(href)
    return list(dict.fromkeys(urls))


async def paginate_by_scroll(page, product_selector, max_scrolls=50, scroll_pause=1.5):
    previous_count = 0
    for _ in range(max_scrolls):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(scroll_pause)

        current_count = len(await page.query_selector_all(product_selector))
        if current_count == previous_count:
            break
        previous_count = current_count

    links = await page.query_selector_all(product_selector)
    urls = []
    for link in links:
        href = await link.get_attribute("href")
        if href:
            urls.append(href)
    return list(dict.fromkeys(urls))
