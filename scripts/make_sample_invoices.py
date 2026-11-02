"""Create sample supplier invoices as real PDF files, plus vendor and purchase-order master data.

Three vendors use three different layouts and label styles (Turkish and English),
Turkish number formatting (1.234,56) and two VAT rates. About a quarter of the
invoices carry a problem the pipeline must catch: arithmetic that does not add
up, a duplicate invoice number, an unknown tax ID, a missing or over-billed PO,
or a due date before the invoice date.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "inbox"
rnd = random.Random(11)
# which sample invoices carry which problem (the rest are clean)
PROBLEMS = {5: "math", 9: "nopo", 13: "due", 17: "tax", 21: "dup", 26: "overbill", 30: "math", 34: "vat", 38: "nopo"}
FONTS = Path(__file__).resolve().parent / "fonts"  # DejaVu Sans: covers ç ğ ı İ ö ş ü
pdfmetrics.registerFont(TTFont("Sans", str(FONTS / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONTS / "DejaVuSans-Bold.ttf")))

VENDORS = [
    {"vendor_id": "V001", "name": "Marmara Çelik San. A.Ş.", "tax_id": "6120345871", "layout": "tr"},
    {"vendor_id": "V002", "name": "Anadolu Elektrik Ltd. Şti.", "tax_id": "0450987123", "layout": "en"},
    {"vendor_id": "V003", "name": "Boğaziçi Beton A.Ş.", "tax_id": "1789034562", "layout": "compact"},
]
ITEMS = {
    "V001": [("S420 rebar Ø16 (ton)", 26500), ("HEA 200 steel beam (m)", 1850), ("Welding consumables (box)", 940)],
    "V002": [("NYY 4x16 cable (m)", 310), ("Distribution panel 63A", 18400), ("LED fixture 60x60", 1150)],
    "V003": [("C30/37 ready-mix concrete (m³)", 3250), ("Pump service (hour)", 4200), ("C35/45 concrete (m³)", 3700)],
}


def tr_money(x: float) -> str:
    s = f"{x:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def draw(path: Path, v: dict, inv: dict) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    y = h - 60
    L = {"tr": dict(title="FATURA", no="Fatura No", date="Fatura Tarihi", due="Son Ödeme Tarihi", po="Sipariş No",
                    tax="VKN", sub="Ara Toplam", vat="KDV", total="Genel Toplam"),
         "en": dict(title="INVOICE", no="Invoice No", date="Invoice Date", due="Due Date", po="PO Number",
                    tax="Tax ID", sub="Subtotal", vat="VAT", total="Total Due"),
         "compact": dict(title="E-FATURA", no="Belge No", date="Tarih", due="Vade", po="PO",
                         tax="Vergi No", sub="Mal Hizmet Toplamı", vat="Hesaplanan KDV", total="Ödenecek Tutar")}[v["layout"]]
    c.setFont("Sans-Bold", 16); c.drawString(50, y, v["name"])
    c.setFont("Sans", 9); c.drawString(50, y - 14, f"{L['tax']}: {inv['tax_id']}   ·   Istanbul, Türkiye")
    c.setFont("Sans-Bold", 20); c.drawRightString(w - 50, y, L["title"])
    y -= 60
    c.setFont("Sans", 10)
    meta = [(L["no"], inv["invoice_no"]), (L["date"], inv["date"].strftime("%d.%m.%Y")),
            (L["due"], inv["due"].strftime("%d.%m.%Y"))]
    if inv["po"]:
        meta.append((L["po"], inv["po"]))
    for k, val in meta:
        c.drawString(50, y, f"{k}: {val}"); y -= 15
    c.drawString(330, h - 120, "Bill to: Kuzey Yapı İnşaat A.Ş.")
    y -= 15
    c.setFont("Sans-Bold", 9)
    c.drawString(50, y, "Description"); c.drawRightString(380, y, "Qty"); c.drawRightString(460, y, "Unit price"); c.drawRightString(w - 50, y, "Amount")
    c.setFont("Sans", 9); y -= 16
    for d, q, p in inv["lines"]:
        c.drawString(50, y, d); c.drawRightString(380, y, f"{q:g}"); c.drawRightString(460, y, tr_money(p)); c.drawRightString(w - 50, y, tr_money(q * p)); y -= 14
    y -= 10
    for k, val in [(L["sub"], inv["subtotal"]), (f"{L['vat']} %{inv['vat_rate']}", inv["vat"]), (L["total"], inv["total"])]:
        c.setFont("Sans-Bold" if k == L["total"] else "Sans", 10)
        c.drawString(330, y, k); c.drawRightString(w - 50, y, f"{tr_money(val)} TL"); y -= 15
    c.setFont("Sans", 7); c.drawString(50, 40, "This document is a synthetic sample generated for a portfolio project.")
    c.save()


def main() -> None:
    INBOX.mkdir(exist_ok=True)
    for f in INBOX.glob("*.pdf"):
        f.unlink()
    pos = []
    for i in range(1, 19):
        v = VENDORS[(i - 1) % 3]
        pos.append({"po_number": f"PO-2026-{i:04d}", "vendor_id": v["vendor_id"], "approved_amount_try": rnd.choice([250_000, 400_000, 750_000, 1_200_000])})
    issued = []
    for n in range(1, 41):
        v = rnd.choice(VENDORS)
        po = rnd.choice([p for p in pos if p["vendor_id"] == v["vendor_id"]])
        lines = [(d, float(rnd.choice([1, 2, 5, 8, 12, 20])), float(p)) for d, p in rnd.sample(ITEMS[v["vendor_id"]], rnd.randint(1, 3))]
        d0 = date(2026, 9, 1) + timedelta(days=rnd.randint(0, 55))
        sub = round(sum(q * p for _, q, p in lines), 2)
        rate = 20 if v["vendor_id"] != "V003" else rnd.choice([20, 10])
        vat = round(sub * rate / 100, 2)
        inv = dict(invoice_no=f"{v['vendor_id'][-1]}{d0:%y}{n:05d}", date=d0, due=d0 + timedelta(days=rnd.choice([30, 45, 60])),
                   po=po["po_number"], tax_id=v["tax_id"], lines=lines, subtotal=sub, vat_rate=rate, vat=vat, total=round(sub + vat, 2))
        problem = PROBLEMS.get(n, "none")
        if problem == "math":
            inv["total"] = round(inv["total"] + rnd.choice([1000, 2500, -1500]), 2)
        elif problem == "dup":  # the same clean invoice sent again (copy of an earlier, valid one)
            v, prev = next((x[0], x[2]) for x in issued if x[3] == "none")
            inv = dict(prev)
        elif problem == "tax":
            inv["tax_id"] = "9999999999"
        elif problem == "nopo":
            inv["po"] = ""
        elif problem == "due":
            inv["due"] = d0 - timedelta(days=5)
        elif problem == "vat":
            inv["vat"] = round(inv["vat"] * 1.1, 2)
            inv["total"] = round(inv["subtotal"] + inv["vat"], 2)
        elif problem == "overbill":
            scale = po["approved_amount_try"] * 1.3 / inv["total"]
            inv["lines"] = [(d, round(q * scale), p) for d, q, p in lines]
            inv["subtotal"] = round(sum(q * p for _, q, p in inv["lines"]), 2)
            inv["vat"] = round(inv["subtotal"] * rate / 100, 2)
            inv["total"] = round(inv["subtotal"] + inv["vat"], 2)
        issued.append((v, inv["invoice_no"], inv, problem))
        draw(INBOX / f"scan_{n:03d}_{v['vendor_id']}.pdf", v, inv)
    with open(ROOT / "master_data" / "vendors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["vendor_id", "name", "tax_id"]); w.writeheader()
        w.writerows({k: v[k] for k in ("vendor_id", "name", "tax_id")} for v in VENDORS)
    with open(ROOT / "master_data" / "purchase_orders.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["po_number", "vendor_id", "approved_amount_try"]); w.writeheader(); w.writerows(pos)
    print(f"40 invoices → {INBOX.relative_to(ROOT)}/, master data → master_data/")


if __name__ == "__main__":
    main()
