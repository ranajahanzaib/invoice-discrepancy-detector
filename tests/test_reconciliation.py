from decimal import Decimal

from fastapi.testclient import TestClient

from backend.main import Line, Record, Request, app, reconcile

client = TestClient(app)


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


def test_cases_csv_export_route_is_not_captured_as_case_id():
    response = client.get("/api/cases/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.startswith(
        "case_id,invoice_number,supplier,status,review,exception_types,explanation"
    )
