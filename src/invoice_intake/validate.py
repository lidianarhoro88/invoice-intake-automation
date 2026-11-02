"""Business rules applied before an invoice may be booked.

Each rule returns findings with a code and a severity. ``error`` blocks the
invoice (it goes to the exceptions queue), ``warning`` lets it through but
flags it for review.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .extract import Invoice

TOL = 0.05  # TRY tolerance for rounding


def _tl(x: float) -> str:
    """Format money the Turkish way: 1.234,56"""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class Finding:
    code: str
    severity: str  # error | warning
    message: str


@dataclass
class MasterData:
    vendors_by_tax_id: dict[str, dict]
    purchase_orders: dict[str, dict]

    @classmethod
    def load(cls, folder: str | Path) -> "MasterData":
        folder = Path(folder)
        with open(folder / "vendors.csv", encoding="utf-8") as f:
            vendors = {r["tax_id"]: r for r in csv.DictReader(f)}
        with open(folder / "purchase_orders.csv", encoding="utf-8") as f:
            pos = {r["po_number"]: {**r, "approved_amount_try": float(r["approved_amount_try"])} for r in csv.DictReader(f)}
        return cls(vendors, pos)


def validate(inv: Invoice, md: MasterData, already_booked: set[tuple[str, str]],
             billed_per_po: dict[str, float]) -> list[Finding]:
    out: list[Finding] = []
    required = {"invoice_no": "invoice number", "invoice_date": "invoice date", "tax_id": "tax ID",
                "subtotal": "subtotal", "vat": "VAT", "total": "total"}
    for attr, label in required.items():
        if getattr(inv, attr) in (None, ""):
            out.append(Finding("missing_field", "error", f"Could not read the {label}."))
    if any(f.code == "missing_field" for f in out):
        return out

    vendor = md.vendors_by_tax_id.get(inv.tax_id)
    if not vendor:
        out.append(Finding("unknown_vendor", "error", f"Tax ID {inv.tax_id} is not in the vendor master."))

    if inv.lines:
        line_sum = round(sum(l.amount for l in inv.lines), 2)
        if abs(line_sum - inv.subtotal) > TOL:
            out.append(Finding("lines_mismatch", "error", f"Lines add up to {_tl(line_sum)}, subtotal says {_tl(inv.subtotal)}."))
        for l in inv.lines:
            if abs(l.quantity * l.unit_price - l.amount) > TOL:
                out.append(Finding("line_math", "error", f"'{l.description}': {l.quantity:g} × {_tl(l.unit_price)} ≠ {_tl(l.amount)}."))
    if abs(inv.subtotal + inv.vat - inv.total) > TOL:
        out.append(Finding("total_mismatch", "error",
                           f"Subtotal {_tl(inv.subtotal)} + VAT {_tl(inv.vat)} = {_tl(inv.subtotal + inv.vat)}, invoice total says {_tl(inv.total)}."))
    if inv.vat_rate is not None and abs(inv.subtotal * inv.vat_rate / 100 - inv.vat) > TOL:
        out.append(Finding("vat_mismatch", "error", f"VAT at {inv.vat_rate:g}% should be {_tl(inv.subtotal * inv.vat_rate / 100)}."))
    if inv.vat_rate not in (None, 1, 10, 20):
        out.append(Finding("unusual_vat_rate", "warning", f"VAT rate {inv.vat_rate:g}% is not a standard Turkish rate."))

    if inv.due_date and inv.invoice_date and inv.due_date < inv.invoice_date:
        out.append(Finding("due_before_invoice", "error", "Due date is before the invoice date."))

    if vendor and (vendor["vendor_id"], inv.invoice_no) in already_booked:
        out.append(Finding("duplicate_invoice", "error", f"Invoice {inv.invoice_no} from this vendor is already booked."))

    if not inv.po_number:
        out.append(Finding("missing_po", "error", "No purchase order reference."))
    else:
        po = md.purchase_orders.get(inv.po_number)
        if not po:
            out.append(Finding("unknown_po", "error", f"PO {inv.po_number} does not exist."))
        else:
            if vendor and po["vendor_id"] != vendor["vendor_id"]:
                out.append(Finding("po_vendor_mismatch", "error", f"PO {inv.po_number} belongs to another vendor."))
            billed = billed_per_po.get(inv.po_number, 0.0) + inv.subtotal
            if billed > po["approved_amount_try"] + TOL:
                out.append(Finding("po_overbilled", "error",
                                   f"Billing on {inv.po_number} would reach {_tl(billed)} against {_tl(po['approved_amount_try'])} approved."))
            elif billed > po["approved_amount_try"] * 0.9:
                out.append(Finding("po_nearly_used", "warning", f"More than 90% of {inv.po_number} is now billed."))
    return out
