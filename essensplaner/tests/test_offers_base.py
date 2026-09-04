from datetime import date
from offers.base import OfferData


def test_offer_data_holds_required_and_optional_fields():
    offer = OfferData(
        retailer="kaufland",
        product_name="Gouda 250g",
        valid_from=date(2026, 9, 1),
        valid_until=date(2026, 9, 7),
        price=1.99,
    )
    assert offer.retailer == "kaufland"
    assert offer.description is None
    assert offer.discount_text is None
