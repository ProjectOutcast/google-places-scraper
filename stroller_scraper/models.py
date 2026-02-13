from dataclasses import dataclass, field, fields, asdict
from typing import Optional


@dataclass
class StrollerProduct:
    retailer: str = ""
    brand: str = ""
    product: str = ""
    description: str = ""
    make: str = ""
    weight: str = ""
    features: str = ""
    color: str = ""
    frame_color: str = ""
    suitable_for: str = ""
    price: str = ""
    price_aed: Optional[float] = None
    currency: str = "AED"
    link: str = ""
    travel_friendly: str = ""
    image_url: str = ""
    scraped_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def csv_headers() -> list:
        return [
            "Retailer", "Brand", "Product", "Description", "Make", "Weight",
            "Features", "Color", "Frame Color", "Suitable For", "Price",
            "Price (AED)", "Currency", "Link", "Travel Friendly", "Image URL",
            "Scraped At",
        ]

    def csv_row(self) -> list:
        return [
            self.retailer, self.brand, self.product, self.description,
            self.make, self.weight, self.features, self.color, self.frame_color,
            self.suitable_for, self.price,
            str(self.price_aed) if self.price_aed is not None else "",
            self.currency, self.link, self.travel_friendly, self.image_url,
            self.scraped_at,
        ]
