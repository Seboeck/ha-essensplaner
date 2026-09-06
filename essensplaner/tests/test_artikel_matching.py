from models import Artikel, PendingArtikelMatch
from artikel_matching import resolve_artikel, match_score


def _db(client):
    import database
    return database.SessionLocal()


def _mk_artikel(db, name):
    from datetime import datetime
    a = Artikel(name=name, created_at=datetime.utcnow().isoformat())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_high_confidence_exact_and_fuzzy_match(client):
    db = _db(client)
    gouda = _mk_artikel(db, "Gouda")
    result = resolve_artikel("Gouda Scheiben 250g", db)
    assert result.confidence == "high"
    assert result.artikel.id == gouda.id


def test_high_confidence_compound_word_substring(client):
    db = _db(client)
    mehl = _mk_artikel(db, "Mehl")
    result = resolve_artikel("Weizenmehl Type 405", db)
    assert result.confidence == "high"
    assert result.artikel.id == mehl.id


def test_medium_confidence_returns_candidates(client):
    db = _db(client)
    _mk_artikel(db, "Paprika rot")
    result = resolve_artikel("Paprikapulver edelsüß", db)
    assert result.confidence in ("medium", "low")
    if result.confidence == "medium":
        assert len(result.candidates) >= 1


def test_low_confidence_no_match(client):
    db = _db(client)
    _mk_artikel(db, "Kaffee")
    result = resolve_artikel("Käse", db)
    assert result.confidence == "low"
    assert result.artikel is None


def test_rejected_pairing_is_excluded(client):
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    from datetime import date, datetime
    db.add(PendingArtikelMatch(
        product_name="paprikapulver edelsüß", artikel_id=a.id, score=65, status="rejected",
        retailer="kaufland", source="kaufland_scraper",
        valid_from=date.today(), valid_until=date.today(), created_at=datetime.utcnow().isoformat(),
    ))
    db.commit()
    result = resolve_artikel("Paprikapulver edelsüß", db)
    assert result.confidence != "high" or result.artikel.id != a.id
    assert all(c.id != a.id for c, _ in result.candidates)


def test_confirmed_pairing_returns_high_confidence(client):
    db = _db(client)
    a = _mk_artikel(db, "Paprika rot")
    from datetime import date, datetime
    db.add(PendingArtikelMatch(
        product_name="paprikapulver edelsüß", artikel_id=a.id, score=65, status="confirmed",
        retailer="kaufland", source="kaufland_scraper",
        valid_from=date.today(), valid_until=date.today(), created_at=datetime.utcnow().isoformat(),
    ))
    db.commit()
    result = resolve_artikel("Paprikapulver edelsüß", db)
    assert result.confidence == "high"
    assert result.artikel.id == a.id


def test_resolve_artikel_percent_sign_in_name_does_not_wildcard_match(client):
    """`%` und `_` sind SQL-LIKE-Wildcards. Ein confirmed PendingArtikelMatch
    mit einem laengeren product_name, der zufaellig den (normalisierten)
    Suchbegriff als Teilstring enthaelt, darf NICHT ueber ilike() als
    exakter Treffer durchgehen, nur weil "%" als Wildcard interpretiert
    wurde statt als Literalzeichen."""
    db = _db(client)
    from datetime import date, datetime
    unrelated = Artikel(name="Ganz was anderes", created_at=datetime.utcnow().isoformat())
    db.add(unrelated)
    db.commit()
    db.refresh(unrelated)
    db.add(PendingArtikelMatch(
        product_name="Milch 3,5% Fett haltbar", artikel_id=unrelated.id, score=65.0, status="confirmed",
        retailer="kaufland", source="kaufland_scraper", valid_from=date.today(), valid_until=date.today(),
        created_at=datetime.utcnow().isoformat(),
    ))
    db.commit()

    match = resolve_artikel("Milch 3,5%", db)
    # Ein literales "%" im Suchbegriff darf nicht als Wildcard auf die
    # confirmed-Paarung mit einem anderen (laengeren) product_name matchen —
    # dies darf NICHT ueber den confirmed-Fastpath auf "unrelated" aufloesen.
    assert not (match.confidence == "high" and match.artikel and match.artikel.id == unrelated.id)
