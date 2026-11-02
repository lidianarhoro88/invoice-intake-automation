import shutil
from datetime import date
from pathlib import Path

import pytest

from invoice_intake.extract import Invoice, InvoiceLine, parse_text, parse_tr_number
from invoice_intake.pipeline import run
from invoice_intake.validate import MasterData, validate

ROOT = Path(__file__).resolve().parents[1]

TR_TEXT = """FATURA
Marmara Çelik San. A.Ş.
VKN: 6120345871 · Istanbul, Türkiye
Fatura No: 12600001 Bill to: Kuzey Yapı İnşaat A.Ş.
Fatura Tarihi: 02.09.2026
Son Ödeme Tarihi: 17.10.2026
Sipariş No: PO-2026-0001
Description Qty Unit price Amount
S420 rebar Ø16 (ton) 12 26.500,00 318.000,00
Ara Toplam 318.000,00 TL
KDV %20 63.600,00 TL
Genel Toplam 381.600,00 TL"""

COMPACT_TEXT = """E-FATURA
Boğaziçi Beton A.Ş.
Vergi No: 1789034562 · Istanbul, Türkiye
Belge No: 32600002 Bill to: Kuzey Yapı İnşaat A.Ş.
Tarih: 30.09.2026
Vade: 14.11.2026
PO: PO-2026-0006
Description Qty Unit price Amount
Pump service (hour) 2 4.200,00 8.400,00
Mal Hizmet Toplamı 8.400,00 TL
Hesaplanan KDV %10 840,00 TL
Ödenecek Tutar 9.240,00 TL"""


def md():
    return MasterData(
        vendors_by_tax_id={"6120345871": {"vendor_id": "V001", "tax_id": "6120345871"},
                           "1789034562": {"vendor_id": "V003", "tax_id": "1789034562"}},
        purchase_orders={"PO-2026-0001": {"vendor_id": "V001", "approved_amount_try": 400_000.0},
                         "PO-2026-0006": {"vendor_id": "V003", "approved_amount_try": 250_000.0}})


def codes(findings):
    return {f.code for f in findings}


def test_turkish_numbers():
    assert parse_tr_number("1.234.567,89") == 1234567.89
    assert parse_tr_number("840,00") == 840.0


def test_parse_turkish_layout():
    inv = parse_text(TR_TEXT)
    assert inv.vendor_name == "Marmara Çelik San. A.Ş."
    assert (inv.invoice_no, inv.tax_id, inv.po_number) == ("12600001", "6120345871", "PO-2026-0001")
    assert inv.invoice_date == date(2026, 9, 2) and inv.due_date == date(2026, 10, 17)
    assert (inv.subtotal, inv.vat_rate, inv.vat, inv.total) == (318000.0, 20, 63600.0, 381600.0)
    assert inv.lines == [InvoiceLine("S420 rebar Ø16 (ton)", 12, 26500.0, 318000.0)]


def test_parse_compact_layout_uses_longest_label():
    inv = parse_text(COMPACT_TEXT)
    assert inv.vat == 840.0 and inv.vat_rate == 10       # "Hesaplanan KDV", not "KDV"
    assert inv.po_number == "PO-2026-0006" and inv.total == 9240.0


def test_clean_invoice_passes():
    assert validate(parse_text(TR_TEXT), md(), set(), {}) == []


@pytest.mark.parametrize("mutate, expected", [
    (lambda i: setattr(i, "total", i.total + 1000), "total_mismatch"),
    (lambda i: setattr(i, "vat", i.vat + 50) or setattr(i, "total", i.subtotal + i.vat), "vat_mismatch"),
    (lambda i: setattr(i, "tax_id", "0000000000"), "unknown_vendor"),
    (lambda i: setattr(i, "po_number", None), "missing_po"),
    (lambda i: setattr(i, "po_number", "PO-2099-0001"), "unknown_po"),
    (lambda i: setattr(i, "po_number", "PO-2026-0006"), "po_vendor_mismatch"),
    (lambda i: setattr(i, "due_date", date(2026, 8, 1)), "due_before_invoice"),
    (lambda i: setattr(i, "invoice_no", None), "missing_field"),
    (lambda i: i.lines.append(InvoiceLine("x", 2, 10, 25)), "line_math"),
])
def test_rules(mutate, expected):
    inv = parse_text(TR_TEXT)
    mutate(inv)
    assert expected in codes(validate(inv, md(), set(), {}))


def test_duplicate_and_po_budget():
    inv = parse_text(TR_TEXT)
    assert "duplicate_invoice" in codes(validate(inv, md(), {("V001", "12600001")}, {}))
    assert "po_overbilled" in codes(validate(inv, md(), set(), {"PO-2026-0001": 100_000}))
    assert "po_nearly_used" in codes(validate(inv, md(), set(), {"PO-2026-0001": 50_000}))


def test_pipeline_end_to_end_and_idempotent(tmp_path):
    pytest.importorskip("reportlab")
    inbox = ROOT / "inbox"
    if not any(inbox.glob("*.pdf")):
        pytest.skip("run scripts/make_sample_invoices.py first")
    work = tmp_path / "inbox"
    shutil.copytree(inbox, work)
    db, out = tmp_path / "t.db", tmp_path / "out"
    first = run(work, ROOT / "master_data", db, out, move_files=False)
    assert len(first.booked) + len(first.exceptions) == 40
    assert {"total_mismatch", "missing_po", "duplicate_invoice", "unknown_vendor", "vat_mismatch",
            "due_before_invoice", "po_overbilled"} <= set(first.finding_counts)
    second = run(work, ROOT / "master_data", db, out, move_files=False)
    assert second.skipped == 40 and not second.booked and not second.exceptions
