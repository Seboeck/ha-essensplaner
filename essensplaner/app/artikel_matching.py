"""Zentrale Zuordnung von Freitext-Namen (Zutaten, Angebote, Kühlschrank-
Einträge, ...) zu kanonischen Artikel-Datensätzen, in drei
Konfidenz-Stufen. Ersetzt die frühere, verteilte Matching-Logik in
offers/matching.py."""
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from models import Artikel, PendingArtikelMatch

HIGH_THRESHOLD = 80
MEDIUM_THRESHOLD = 60
SUBSTRING_MIN_LENGTH = 4


def match_score(a: str, b: str) -> float:
    return fuzz.token_set_ratio(a.lower().strip(), b.lower().strip())


def _is_substring_match(a: str, b: str) -> bool:
    """Erkennt deutsche Komposita (z.B. "Mehl" in "Weizenmehl"), die
    token_set_ratio allein verpasst. Mindestlänge 4 verhindert
    Fehltreffer bei kurzen Namen (z.B. "Ei" in "Reis")."""
    a_lower, b_lower = a.lower().strip(), b.lower().strip()
    shorter, longer = (a_lower, b_lower) if len(a_lower) <= len(b_lower) else (b_lower, a_lower)
    return len(shorter) >= SUBSTRING_MIN_LENGTH and shorter in longer


@dataclass
class ArtikelMatch:
    confidence: str  # "high" | "medium" | "low"
    artikel: Optional[Artikel] = None
    candidates: list[tuple[Artikel, float]] = field(default_factory=list)


def resolve_artikel(name: str, db: Session) -> ArtikelMatch:
    normalized = name.strip().lower()

    confirmed = (
        db.query(PendingArtikelMatch)
        .filter(PendingArtikelMatch.product_name.ilike(normalized), PendingArtikelMatch.status == "confirmed")
        .first()
    )
    if confirmed:
        return ArtikelMatch(confidence="high", artikel=confirmed.artikel)

    rejected_artikel_ids = {
        p.artikel_id for p in db.query(PendingArtikelMatch)
        .filter(PendingArtikelMatch.product_name.ilike(normalized), PendingArtikelMatch.status == "rejected")
        .all()
    }

    scored: list[tuple[Artikel, float]] = []
    for artikel in db.query(Artikel).all():
        if artikel.id in rejected_artikel_ids:
            continue
        score = match_score(name, artikel.name)
        if _is_substring_match(name, artikel.name):
            score = max(score, HIGH_THRESHOLD)
        scored.append((artikel, score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    if scored and scored[0][1] >= HIGH_THRESHOLD:
        return ArtikelMatch(confidence="high", artikel=scored[0][0])

    medium_candidates = [(a, s) for a, s in scored if s >= MEDIUM_THRESHOLD]
    if medium_candidates:
        return ArtikelMatch(confidence="medium", candidates=medium_candidates)

    return ArtikelMatch(confidence="low")
