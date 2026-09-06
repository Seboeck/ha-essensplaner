from sqlalchemy import text


def test_artikel_tables_exist(client):
    import database
    with database.engine.connect() as conn:
        artikel_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artikel)"))}
        history_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(artikel_price_history)"))}
        pending_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(pending_artikel_matches)"))}

    assert {"name", "image_path", "created_at"} <= artikel_cols
    assert {"artikel_id", "price", "discount_text", "retailer", "source", "valid_from", "valid_until", "recorded_at"} <= history_cols
    assert {"product_name", "artikel_id", "score", "status", "price", "discount_text", "retailer", "source", "valid_from", "valid_until"} <= pending_cols
