from decimal import Decimal

from backend.main import Line, Record, Request, reconcile


def scenario(invoice_price: str = "485") -> Request:
    return Request(
        invoice=Record(
            number="INV-350", po_number="PO-100", currency="USD", subtotal=Decimal("4850"),
            tax=Decimal("0"), total=Decimal("4850"),
            lines=[Line(sku="WID-01", description="Industrial widget", quantity=Decimal("10"), unit_price=Decimal(invoice_price))],
        ),
        po=Record(
            number="PO-100", currency="USD",
            lines=[Line(sku="WID-01", description="Industrial widget", quantity=Decimal("10"), unit_price=Decimal("450"))],
        ),
        receipt=Record(lines=[Line(sku="WID-01", description="Industrial widget", quantity=Decimal("10"))]),
    )


def test_detects_350_price_variance():
    result = reconcile(scenario())
    issue = next(x for x in result["exceptions"] if x["type"] == "price_mismatch")
    assert issue["calculation"] == "10 × (485 − 450) = 350"
    assert result["status"] == "exception"


def test_matching_values_do_not_raise_exception():
    result = reconcile(scenario("450"))
    assert result["exceptions"] == []
    assert result["status"] == "matched"


def test_missing_receipt_is_explicit_exception():
    req = scenario()
    req.receipt = None
    assert any(x["type"] == "receipt_missing" for x in reconcile(req)["exceptions"])
