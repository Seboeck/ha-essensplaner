"""Führt einen einzelnen Connector aus, ersetzt dessen alte Offer-Zeilen
und schreibt Erfolg/Fehler in OfferSourceConfig. Ein Lauf betrifft immer
nur die eigene `source` — andere Quellen bleiben unberührt."""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

import ha_client
from artikel_matching import resolve_artikel
from artikel_images import download_artikel_image
from models import Artikel, ArtikelPriceHistory, Offer, OfferSourceConfig, PendingArtikelMatch
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


def _record_artikel_match(offer_data, source: str, db: Session, now: str) -> None:
    """Ordnet ein Angebot einem Artikel zu: hohe Konfidenz -> Preis-Historie
    (+ Bild, falls noch keins gesetzt), mittlere Konfidenz -> Bestätigungs-
    Warteschlange. Niedrige Konfidenz wird ignoriert (kein bekannter Artikel
    passt)."""
    match = resolve_artikel(offer_data.product_name, db)

    if match.confidence == "high":
        artikel = match.artikel
        db.flush()  # ohne Flush sieht die Duplikat-Prüfung Zeilen nicht, die im selben Lauf schon (aber noch nicht committed) hinzugefügt wurden
        duplicate = (
            db.query(ArtikelPriceHistory)
            .filter(
                ArtikelPriceHistory.artikel_id == artikel.id,
                ArtikelPriceHistory.valid_from == offer_data.valid_from,
                ArtikelPriceHistory.valid_until == offer_data.valid_until,
                ArtikelPriceHistory.price == offer_data.price,
            )
            .first()
        )
        if not duplicate:
            db.add(ArtikelPriceHistory(
                artikel_id=artikel.id, price=offer_data.price, discount_text=offer_data.discount_text,
                retailer=offer_data.retailer, source=source,
                valid_from=offer_data.valid_from, valid_until=offer_data.valid_until, recorded_at=now,
            ))
        if not artikel.image_path and offer_data.image_url:
            image_path = download_artikel_image(artikel.id, offer_data.image_url)
            if image_path:
                artikel.image_path = image_path

    elif match.confidence == "medium":
        product_norm = offer_data.product_name.strip().lower()
        for artikel, score in match.candidates:
            existing = (
                db.query(PendingArtikelMatch)
                .filter(
                    func.lower(PendingArtikelMatch.product_name) == product_norm,
                    PendingArtikelMatch.artikel_id == artikel.id,
                    PendingArtikelMatch.status == "open",
                )
                .first()
            )
            if existing:
                existing.score = score
                existing.price = offer_data.price
                existing.discount_text = offer_data.discount_text
                existing.retailer = offer_data.retailer
                existing.source = source
                existing.valid_from = offer_data.valid_from
                existing.valid_until = offer_data.valid_until
            else:
                db.add(PendingArtikelMatch(
                    product_name=offer_data.product_name, artikel_id=artikel.id, score=score,
                    price=offer_data.price, discount_text=offer_data.discount_text,
                    retailer=offer_data.retailer, source=source,
                    valid_from=offer_data.valid_from, valid_until=offer_data.valid_until, created_at=now,
                ))


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

    # Vor dem Löschen: bereits benachrichtigte Angebote merken. Identität über
    # (product_name, valid_until), da Delete-then-Replace sonst jede Zeile mit
    # frischem notified_at=NULL neu anlegt und dieselbe wöchentliche Aktion bei
    # jedem Lauf erneut benachrichtigt würde.
    previously_notified = {
        (o.product_name, o.valid_until)
        for o in db.query(Offer).filter(Offer.source == source, Offer.notified_at.isnot(None)).all()
    }

    db.query(Offer).filter(Offer.source == source).delete()
    for offer_data in results:
        carried_notified_at = now if (offer_data.product_name, offer_data.valid_until) in previously_notified else None
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
            notified_at=carried_notified_at,
        ))
        _record_artikel_match(offer_data, source, db, now)

    db.flush()  # ohne Flush sieht die folgende Query die eben hinzugefügten Zeilen nicht (autoflush ist in Tests aus)
    new_offers = db.query(Offer).filter(Offer.source == source, Offer.notified_at.is_(None)).all()
    matched = [o for o in new_offers if is_watchlist_match(o.product_name, db)]
    if matched:
        lines = [f"- {o.product_name}" + (f" ({o.discount_text})" if o.discount_text else "") for o in matched]
        message = f"{len(matched)} neue Angebote zu deiner Merkliste ({source}):\n" + "\n".join(lines)
        try:
            asyncio.run(ha_client.notify(message, source=source))
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
