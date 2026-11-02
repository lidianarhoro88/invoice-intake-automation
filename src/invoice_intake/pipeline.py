"""Process every PDF in the inbox.

    python -m invoice_intake.pipeline --inbox inbox --master master_data --db intake.db

For each file: hash → skip if already processed → extract → validate →
book it (processed/) or send it to the exceptions queue (exceptions/).
Finishes with an HTML run report and an optional chat notification.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .extract import extract_pdf
from .report import render_report
from .store import Store, file_hash
from .validate import MasterData, validate


@dataclass
class RunResult:
    booked: list[dict] = field(default_factory=list)
    exceptions: list[dict] = field(default_factory=list)
    skipped: int = 0

    @property
    def finding_counts(self) -> Counter:
        return Counter(f["code"] for e in self.exceptions for f in e["findings"] if f["severity"] == "error")


def run(inbox: Path, master: Path, db: Path, out: Path, move_files: bool = True) -> RunResult:
    md = MasterData.load(master)
    store = Store(db)
    res = RunResult()
    for sub in ("processed", "exceptions"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    for pdf in sorted(inbox.glob("*.pdf")):
        h = file_hash(pdf)
        if store.seen(h):
            res.skipped += 1
            continue
        inv = extract_pdf(pdf)
        findings = validate(inv, md, store.booked_keys(), store.billed_per_po())
        errors = [f for f in findings if f.severity == "error"]
        row = {"file": pdf.name, "vendor": inv.vendor_name, "invoice_no": inv.invoice_no, "total": inv.total,
               "po": inv.po_number, "findings": [f.__dict__ for f in findings]}
        if errors:
            store.reject(h, inv, findings)
            res.exceptions.append(row)
            dest = out / "exceptions"
        else:
            store.book(h, inv, md.vendors_by_tax_id[inv.tax_id]["vendor_id"], warnings=bool(findings))
            res.booked.append(row)
            dest = out / "processed"
        if move_files:
            shutil.move(str(pdf), dest / pdf.name)
    return res


def notify(res: RunResult) -> None:
    """Post a one-line summary to a Slack/Teams/Discord-style incoming webhook if INTAKE_WEBHOOK_URL is set."""
    url = os.getenv("INTAKE_WEBHOOK_URL")
    if not url:
        return
    text = f"Invoice intake: {len(res.booked)} booked, {len(res.exceptions)} need review."
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Supplier invoice intake pipeline")
    ap.add_argument("--inbox", default="inbox", type=Path)
    ap.add_argument("--master", default="master_data", type=Path)
    ap.add_argument("--db", default="intake.db", type=Path)
    ap.add_argument("--out", default="output", type=Path)
    ap.add_argument("--report", default="output/run_report.html", type=Path)
    ap.add_argument("--keep-files", action="store_true", help="Do not move PDFs out of the inbox")
    a = ap.parse_args(argv)

    res = run(a.inbox, a.master, a.db, a.out, move_files=not a.keep_files)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(render_report(res), encoding="utf-8")
    print(f"Booked {len(res.booked)} · exceptions {len(res.exceptions)} · already processed {res.skipped}")
    for code, n in res.finding_counts.most_common():
        print(f"  {code:22} {n}")
    print(f"Report → {a.report}")
    notify(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
