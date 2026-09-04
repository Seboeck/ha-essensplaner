"""Führt einen einzelnen Connector aus, ersetzt dessen alte Offer-Zeilen
und schreibt Erfolg/Fehler in OfferSourceConfig. Ein Lauf betrifft immer
nur die eigene `source` — andere Quellen bleiben unberührt."""
from datetime import datetime

from sqlalchemy.orm import Session

from models import Offer, OfferSourceConfig
from offers import kaufland_scraper, edeka_scraper, marktguru_connector

CONNECTORS = {
    kaufland_scraper.SOURCE: kaufland_scraper,
    edeka_scraper.SOURCE: edeka_scraper,
    marktguru_connector.SOURCE: marktguru_connector,
}


def get_or_create_source_config(source: str, db: Session) -> OfferSourceConfig:
    config = db.query(OfferSourceConfig).filter(OfferSourceConfig.source == source).first()
    if not config:
        config = OfferSourceConfig(source=source, enabled=True)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def run_source(source: str, db: Session, plz: str, store_url: str | None = None) -> OfferSourceConfig:
    if source not in CONNECTORS:
        raise ValueError(f"Unbekannte Angebots-Quelle: {source}")

    config = get_or_create_source_config(source, db)
    connector = CONNECTORS[source]
    now = datetime.utcnow().isoformat()

    try:
        results = connector.fetch_offers(plz, store_url)
    except Exception as exc:
        config.last_run_at = now
        config.last_status = f"Fehler: {exc}"
        db.commit()
        db.refresh(config)
        return config

    db.query(Offer).filter(Offer.source == source).delete()
    for offer_data in results:
        db.add(Offer(
            retailer=offer_data.retailer,
            source=source,
            product_name=offer_data.product_name,
            description=offer_data.description,
            price=offer_data.price,
            discount_text=offer_data.discount_text,
            valid_from=offer_data.valid_from,
            valid_until=offer_data.valid_until,
            scraped_at=now,
        ))

    config.last_run_at = now
    config.last_status = "ok"
    db.commit()
    db.refresh(config)
    return config
