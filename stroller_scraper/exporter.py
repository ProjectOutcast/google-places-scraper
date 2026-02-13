import csv
import re
from datetime import datetime
from typing import List, Tuple, Optional

from models import StrollerProduct
from config import KNOWN_BRANDS, TRAVEL_KEYWORDS


def normalize_price(price_text: str) -> Tuple[str, Optional[float]]:
    if not price_text:
        return ("", None)

    cleaned = price_text.replace("AED", "").replace("د.إ", "")
    cleaned = cleaned.replace("Dhs.", "").replace("Dhs", "")
    cleaned = cleaned.replace(",", "").strip()

    # Take the first number found (handles "AED 999 AED 1299" sale patterns)
    match = re.search(r"[\d.]+", cleaned)
    if match:
        try:
            numeric = float(match.group())
            return (f"AED {numeric:,.2f}", numeric)
        except ValueError:
            pass

    return (price_text.strip(), None)


def normalize_weight(weight_str: str) -> str:
    if not weight_str:
        return ""

    weight_str = weight_str.strip().lower()
    match = re.search(r"([\d.]+)\s*(kg|kgs|kilograms?|lbs?|pounds?|g|grams?)", weight_str)
    if not match:
        return weight_str

    value = float(match.group(1))
    unit = match.group(2)

    if unit.startswith("lb") or unit.startswith("pound"):
        value = value * 0.453592
    elif unit.startswith("g") and not unit.startswith("kg"):
        if value > 100:
            value = value / 1000

    return f"{value:.1f} kg"


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def infer_travel_friendly(product: StrollerProduct) -> str:
    text = f"{product.product} {product.features} {product.description}".lower()
    for kw in TRAVEL_KEYWORDS:
        if kw in text:
            return "Yes"
    return ""


def infer_brand(product_name: str) -> str:
    name_lower = product_name.lower()
    for brand in KNOWN_BRANDS:
        if brand.lower() in name_lower:
            return brand
    return ""


def normalize_product(product: StrollerProduct) -> StrollerProduct:
    product.price, product.price_aed = normalize_price(product.price)
    product.currency = "AED"

    if not product.brand and product.product:
        product.brand = infer_brand(product.product)

    if not product.make:
        product.make = product.brand

    if not product.travel_friendly:
        product.travel_friendly = infer_travel_friendly(product)

    if product.weight:
        product.weight = normalize_weight(product.weight)

    product.description = strip_html(product.description)
    product.features = strip_html(product.features)

    if not product.scraped_at:
        product.scraped_at = datetime.now().isoformat()

    return product


def export_combined_csv(products: List[StrollerProduct], filepath: str):
    import os
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(StrollerProduct.csv_headers())
        for product in products:
            writer.writerow(product.csv_row())
