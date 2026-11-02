"""HTML run report: what was booked, what needs a human, and why."""
from __future__ import annotations

import html
from datetime import datetime


def _m(x) -> str:
    return "—" if x is None else f"{x:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def render_report(res) -> str:
    e = html.escape
    exc_rows = "".join(
        f"<tr><td><code>{e(r['file'])}</code></td><td>{e(r['vendor'] or '?')}</td><td>{e(str(r['invoice_no'] or '?'))}</td>"
        f"<td class='n'>{_m(r['total'])}</td><td>{'<br>'.join(f'<b>{e(f['code'].replace('_', ' '))}</b>: {e(f['message'])}' for f in r['findings'] if f['severity'] == 'error')}</td></tr>"
        for r in res.exceptions) or "<tr><td colspan=5>Nothing needs review.</td></tr>"
    ok_rows = "".join(
        f"<tr><td><code>{e(r['file'])}</code></td><td>{e(r['vendor'] or '')}</td><td>{e(str(r['invoice_no']))}</td><td>{e(r['po'] or '')}</td>"
        f"<td class='n'>{_m(r['total'])}</td><td>{'⚠ ' + e('; '.join(f['message'] for f in r['findings'])) if r['findings'] else ''}</td></tr>"
        for r in res.booked)
    counts = "".join(f"<li><b>{n}</b> {e(c.replace('_', ' '))}</li>" for c, n in res.finding_counts.most_common())
    booked_total = sum(r["total"] or 0 for r in res.booked)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Invoice intake run</title><style>
:root{{--bg:#F6F1EA;--card:#FFFCF7;--ink:#2A1A20;--muted:#6E5A61;--wine:#5C2E3E;--gold:#9A7633;--line:rgba(92,46,62,.15);--bad:#A3333D;--ok:#2F7D5B}}
@media(prefers-color-scheme:dark){{:root{{--bg:#171013;--card:#221820;--ink:#F4EAE3;--muted:#B5A3A9;--wine:#D49AAE;--gold:#D9B977;--line:rgba(244,234,227,.12);--bad:#F2A1A8;--ok:#7CCBA2}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}.w{{max-width:1150px;margin:0 auto;padding:32px 20px}}
h1{{font:500 2rem Georgia,serif;margin:0}}h2{{font:500 1.3rem Georgia,serif;margin:34px 0 12px}}.m{{color:var(--muted)}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:22px 0}}.k div{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}
.k b{{display:block;font:500 1.8rem Georgia,serif}}table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;font-size:.88rem}}
th,td{{padding:9px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}.n{{text-align:right;white-space:nowrap}}
code{{font-size:.82rem;color:var(--gold)}}ul{{columns:2;padding-left:18px}}
</style></head><body><div class="w"><div class="m">Run at {datetime.now():%Y-%m-%d %H:%M}</div><h1>Invoice intake run</h1>
<div class="k"><div><span class="m">Booked</span><b style="color:var(--ok)">{len(res.booked)}</b></div>
<div><span class="m">Need review</span><b style="color:var(--bad)">{len(res.exceptions)}</b></div>
<div><span class="m">Already processed</span><b>{res.skipped}</b></div>
<div><span class="m">Booked value</span><b>{_m(booked_total)}</b></div></div>
<h2>Why invoices were stopped</h2><ul>{counts or '<li>None</li>'}</ul>
<h2>Exceptions queue</h2><table><tr><th>File</th><th>Vendor</th><th>Invoice</th><th class=n>Total</th><th>Blocking findings</th></tr>{exc_rows}</table>
<h2>Booked</h2><table><tr><th>File</th><th>Vendor</th><th>Invoice</th><th>PO</th><th class=n>Total</th><th>Warnings</th></tr>{ok_rows}</table>
</div></body></html>"""
