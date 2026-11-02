"""SQLite persistence. Every processed file is recorded by its SHA-256 hash, so
re-running the pipeline on the same folder never books an invoice twice."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = """
create table if not exists processed_files (
    file_hash text primary key, file_name text not null, processed_at text not null default (datetime('now')),
    outcome text not null check (outcome in ('booked', 'exception'))
);
create table if not exists invoices (
    invoice_id integer primary key, file_hash text not null references processed_files(file_hash),
    vendor_id text not null, invoice_no text not null, invoice_date text, due_date text, po_number text,
    subtotal real, vat_rate real, vat real, total real, has_warnings integer not null default 0,
    unique (vendor_id, invoice_no)
);
create table if not exists invoice_lines (
    invoice_id integer not null references invoices(invoice_id), line_no integer not null,
    description text, quantity real, unit_price real, amount real, primary key (invoice_id, line_no)
);
create table if not exists exceptions (
    file_hash text primary key references processed_files(file_hash), file_name text, vendor_name text,
    invoice_no text, total real, findings_json text not null, status text not null default 'open'
);
"""


def file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Store:
    def __init__(self, path: str | Path):
        self.con = sqlite3.connect(str(path))
        self.con.execute("pragma foreign_keys = on")
        self.con.executescript(SCHEMA)

    def seen(self, h: str) -> bool:
        return self.con.execute("select 1 from processed_files where file_hash = ?", (h,)).fetchone() is not None

    def booked_keys(self) -> set[tuple[str, str]]:
        return set(self.con.execute("select vendor_id, invoice_no from invoices").fetchall())

    def billed_per_po(self) -> dict[str, float]:
        return dict(self.con.execute("select po_number, sum(subtotal) from invoices where po_number is not null group by 1").fetchall())

    def book(self, h: str, inv, vendor_id: str, warnings: bool) -> None:
        with self.con:
            self.con.execute("insert into processed_files(file_hash, file_name, outcome) values (?,?, 'booked')", (h, inv.source_file))
            cur = self.con.execute(
                "insert into invoices(file_hash, vendor_id, invoice_no, invoice_date, due_date, po_number, subtotal, vat_rate, vat, total, has_warnings)"
                " values (?,?,?,?,?,?,?,?,?,?,?)",
                (h, vendor_id, inv.invoice_no, str(inv.invoice_date), str(inv.due_date) if inv.due_date else None, inv.po_number,
                 inv.subtotal, inv.vat_rate, inv.vat, inv.total, int(warnings)))
            self.con.executemany("insert into invoice_lines values (?,?,?,?,?,?)",
                                 [(cur.lastrowid, i + 1, l.description, l.quantity, l.unit_price, l.amount) for i, l in enumerate(inv.lines)])

    def reject(self, h: str, inv, findings) -> None:
        with self.con:
            self.con.execute("insert into processed_files(file_hash, file_name, outcome) values (?,?, 'exception')", (h, inv.source_file))
            self.con.execute("insert into exceptions(file_hash, file_name, vendor_name, invoice_no, total, findings_json) values (?,?,?,?,?,?)",
                             (h, inv.source_file, inv.vendor_name, inv.invoice_no, inv.total,
                              json.dumps([f.__dict__ for f in findings], ensure_ascii=False)))
