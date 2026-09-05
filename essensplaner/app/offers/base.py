"""Gemeinsame Datenstruktur, die alle Angebots-Connectors zurückgeben.
Jeder Connector implementiert `fetch_offers(plz, store_url=None) -> list[OfferData]`."""
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class OfferData:
    retailer: str  # "kaufland" | "edeka"
    product_name: str
    valid_from: date
    valid_until: date
    description: Optional[str] = None
    price: Optional[float] = None
    discount_text: Optional[str] = None
