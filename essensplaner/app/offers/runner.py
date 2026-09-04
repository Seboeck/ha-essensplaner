"""Führt einen einzelnen Connector aus, ersetzt dessen alte Offer-Zeilen
und schreibt Erfolg/Fehler in OfferSourceConfig. Ein Lauf betrifft immer
nur die eigene `source` — andere Quellen bleiben unberührt."""
import asyncio
import logging
from datetime import datetime

from sqlalchemy.orm import Session

import ha_client
from models import Offer, OfferSourceConfig
from offers import kaufland_scraper, edeka_scraper, marktguru_connector
from offers.matching import is_watchlist_match

logger = logging.getLogger(__name__)

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

    db.flush()  # ohne Flush sieht die folgende Query die eben hinzugefügten Zeilen nicht (autoflush ist in Tests aus)
    new_offers = db.query(Offer).filter(Offer.source == source, Offer.notified_at.is_(None)).all()
    matched = [o for o in new_offers if is_watchlist_match(o.product_name, db)]
    if matched:
        lines = [f"- {o.product_name}" + (f" ({o.discount_text})" if o.discount_text else "") for o in matched]
        message = f"{len(matched)} neue Angebote zu deiner Merkliste ({source}):\n" + "\n".join(lines)
        try:
            asyncio.run(ha_client.notify(message))
        except Exception:
            logger.exception("Benachrichtigung für %s fehlgeschlagen", source)
            pass  # Benachrichtigung ist ein Nice-to-have, darf den Lauf nicht scheitern lassen
        for offer in matched:
            offer.notified_at = now

    config.last_run_at = now
    config.last_status = "ok"
    db.commit()
    db.refresh(config)
    return config
