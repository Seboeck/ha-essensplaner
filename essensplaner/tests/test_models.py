from models import Offer, WatchlistItem, OfferSourceConfig, Settings


def test_new_tables_exist_and_settings_has_new_columns(client):
    import database
    from sqlalchemy import text

    with database.engine.connect() as conn:
        offer_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(offers)"))}
        watchlist_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(watchlist_items)"))}
        source_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(offer_source_configs)"))}
        settings_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(settings)"))}

    assert {"retailer", "source", "product_name", "valid_from", "valid_until"} <= offer_cols
    assert {"name", "unit"} <= watchlist_cols
    assert {"source", "enabled", "schedule_weekday", "schedule_hour"} <= source_cols
    assert {"plz", "kaufland_store_url", "edeka_store_url"} <= settings_cols
