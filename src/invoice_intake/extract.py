"""Turn PDF text into an Invoice.

Vendors use different layouts and label words, in Turkish and English. Instead
of one template per vendor, each field has a list of label synonyms, and values
are parsed with Turkish number and date conventions (1.234,56 and 31.12.2026).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pdfplumber

LABELS = {
    "invoice_no": ["Fatura No", "Invoice No", "Belge No", "Invoice #"],
    "invoice_date": ["Fatura Tarihi", "Invoice Date", "Tarih"],
    "due_date": ["Son Ödeme Tarihi", "Due Date", "Vade"],
    "po_number": ["Sipariş No", "PO Number", "PO"],
    "tax_id": ["VKN", "Tax ID", "Vergi No"],
    "subtotal": ["Ara Toplam", "Subtotal", "Mal Hizmet Toplamı"],
    "vat": ["KDV", "VAT", "Hesaplanan KDV"],
    "total": ["Genel Toplam", "Total Due", "Ödenecek Tutar"],
}
MONEY = r"(-?\d{1,3}(?:\.\d{3})*,\d{2})"
LINE = re.compile(r"^(?P<desc>.+?)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+" + MONEY + r"\s+" + MONEY + r"$")


@dataclass
class InvoiceLine:
    description: str
    quantity: float
    unit_price: float
    amount: float


@dataclass
class Invoice:
    source_file: str
    vendor_name: str | None = None
    tax_id: str | None = None
    invoice_no: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    subtotal: float | None = None
    vat_rate: float | None = None
    vat: float | None = None
    total: float | None = None
    lines: list[InvoiceLine] = field(default_factory=list)


def parse_tr_number(text: str) -> float:
    """'1.234.567,89' → 1234567.89"""
    return float(text.replace(".", "").replace(",", "."))


def parse_tr_date(text: str) -> date:
    return datetime.strptime(text.strip(), "%d.%m.%Y").date()


def _find(text: str, field_name: str, value_pattern: str) -> str | None:
    # longest labels first so "Hesaplanan KDV" wins over "KDV" and "PO Number" over "PO"
    for label in sorted(LABELS[field_name], key=len, reverse=True):
        m = re.search(rf"(?m)^{re.escape(label)}\b[^\S\n]*:?[^\S\n]*{value_pattern}", text)
        if m:
            return m.group(1)
    return None


def parse_text(text: str, source_file: str = "") -> Invoice:
    inv = Invoice(source_file=source_file)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title_words = {"FATURA", "INVOICE", "E-FATURA"}
    inv.vendor_name = next((l for l in lines if l.upper() not in title_words), None)

    inv.tax_id = _find(text, "tax_id", r"(\d{10,11})")
    inv.invoice_no = _find(text, "invoice_no", r"([A-Z0-9-]+)")
    if d := _find(text, "invoice_date", r"(\d{2}\.\d{2}\.\d{4})"):
        inv.invoice_date = parse_tr_date(d)
    if d := _find(text, "due_date", r"(\d{2}\.\d{2}\.\d{4})"):
        inv.due_date = parse_tr_date(d)
    inv.po_number = _find(text, "po_number", r"(PO-\d{4}-\d{4})")
    for name in ("subtotal", "total"):
        if v := _find(text, name, MONEY):
            setattr(inv, name, parse_tr_number(v))
    m = None
    for label in sorted(LABELS["vat"], key=len, reverse=True):
        m = re.search(rf"(?m)^{re.escape(label)}\s*%(\d+(?:[.,]\d+)?)\s+{MONEY}", text)
        if m:
            break
    if m:
        inv.vat_rate = parse_tr_number(m.group(1)) if "," in m.group(1) else float(m.group(1))
        inv.vat = parse_tr_number(m.group(2))

    for l in lines:
        lm = LINE.match(l)
        if lm and not any(l.startswith(lbl) for lbls in LABELS.values() for lbl in lbls):
            inv.lines.append(InvoiceLine(lm["desc"], float(lm["qty"].replace(",", ".")),
                                         parse_tr_number(lm.group(3)), parse_tr_number(lm.group(4))))
    return inv


def extract_pdf(path: str | Path) -> Invoice:
    path = Path(path)
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return parse_text(text, source_file=path.name)
