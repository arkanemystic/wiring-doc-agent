"""Client-facing ROI reports as PDFs, one per phase.

Usage (from the repo root): python -m evals.roi.client_report
Reads evals/roi/phases.json (python -m evals.roi.roi, then python -m evals.roi.phases) and writes
  evals/roi/UseCase1_ROI.pdf   Use Case 1, wire instruction extraction, on the client's documents-per-day figures
  evals/roi/UseCase2_ROI.pdf   Use Case 2 title; intake, cross-document checks, exceptions and outputs, on top of Use Case 1
Needs Playwright with Chromium.
"""
import html, json, statistics as st
from pathlib import Path

from playwright.sync_api import sync_playwright

from evals.roi.replay import CONFIGS

OUT = Path(__file__).parent
EVALS = OUT.parent
TASK_NAMES = {"intake": "Intake and package set-up", "wire_extraction": "Wire instruction data entry",
              "cross_doc": "Cross-document checks", "exceptions": "Exceptions and call-backs",
              "outputs": "Workbook, CashPro and BCMP files"}
FIELD_NAMES = {"routing_number_aba": "Routing number (ABA)", "account_number": "Account number",
               "bank_name": "Bank name", "bank_address": "Bank address", "beneficiary_name": "Beneficiary name",
               "beneficiary_address": "Beneficiary address"}
INK, INK2, MUTED, RULE = "#1d1d1b", "#55534e", "#8a877f", "#d9d7cf"
TODAY, NAVY = "#b9b6ad", "#1f4e8c"
SANS = "Inter, 'Liberation Sans', sans-serif"
e = html.escape


def k(x: float) -> str:
    return f"${x / 1000:,.0f}k" if abs(x) >= 1000 else f"${x:,.0f}"


def usd(x: float) -> str:
    return f"${round(x, -2):,.0f}"


# ---------- figures ----------

def fig_bars(rows: list[tuple[str, float, str]], top: float, ticks: list[tuple[float, str]]) -> str:
    W, L, bar, gap = 620, 160, 22, 12
    H = len(rows) * (bar + gap) + 26
    x = lambda v: L + v / top * (W - L - 70)
    g = [f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="0" y2="{H - 22}" stroke="{RULE}"/>'
         f'<text x="{x(t):.1f}" y="{H - 6}" font-size="10" fill="{MUTED}" text-anchor="middle">{e(label)}</text>' for t, label in ticks]
    for i, (name, v, color) in enumerate(rows):
        y = i * (bar + gap) + 4
        g.append(f'<text x="0" y="{y + bar / 2 + 4}" font-size="11.5" fill="{INK}">{e(name)}</text>'
                 f'<rect x="{L}" y="{y}" width="{max(x(v) - L, 1):.1f}" height="{bar}" fill="{color}"/>'
                 f'<text x="{x(v) + 8:.1f}" y="{y + bar / 2 + 4}" font-size="11.5" fill="{INK}" font-weight="600">{v:.0f} min</text>')
    return f'<svg width="{W}" height="{H}" font-family="{SANS}">{"".join(g)}</svg>'


def fig_tasks(tasks: dict, before_label: str, after_label: str) -> str:
    W, L, row = 620, 200, 30
    H = len(tasks) * row + 40
    x = lambda m: L + m / 80 * (W - L - 40)
    g = [f'<line x1="{x(t)}" x2="{x(t)}" y1="16" y2="{H - 22}" stroke="{RULE}"/>'
         f'<text x="{x(t)}" y="{H - 6}" font-size="10" fill="{MUTED}" text-anchor="middle">{t} min</text>' for t in (0, 20, 40, 60, 80)]
    g.append(f'<circle cx="{L + 4}" cy="6" r="4.5" fill="{TODAY}"/><text x="{L + 14}" y="10" font-size="10.5" fill="{INK2}">{e(before_label)}</text>'
             f'<circle cx="{L + 120}" cy="6" r="4.5" fill="{NAVY}"/><text x="{L + 130}" y="10" font-size="10.5" fill="{INK2}">{e(after_label)}</text>')
    for i, (t, v) in enumerate(tasks.items()):
        y = 34 + i * row
        a, b = v["before"], v["after"]
        g.append(f'<text x="0" y="{y + 4}" font-size="11.5" fill="{INK}">{e(TASK_NAMES[t])}</text>'
                 f'<line x1="{x(b):.1f}" x2="{x(a):.1f}" y1="{y}" y2="{y}" stroke="{RULE}" stroke-width="3"/>'
                 f'<circle cx="{x(a):.1f}" cy="{y}" r="5.5" fill="{TODAY}"/><circle cx="{x(b):.1f}" cy="{y}" r="5.5" fill="{NAVY}"/>'
                 f'<text x="{x(b) - 10:.1f}" y="{y + 4}" font-size="10.5" fill="{NAVY}" text-anchor="end" font-weight="600">{b:.0f}</text>'
                 f'<text x="{x(a) + 10:.1f}" y="{y + 4}" font-size="10.5" fill="{INK2}">{a:.0f}</text>')
    return f'<svg width="{W}" height="{H}" font-family="{SANS}">{"".join(g)}</svg>'


def fig_accuracy(m: dict) -> str:
    n = m["packages"] - m["failed_rows"]
    rows = [(FIELD_NAMES[f], m["field_correct"][f], n) for f in FIELD_NAMES]
    rows.append(("Wrong values flagged for the reviewer", m["wrong_caught"], m["wrong_caught"] + m["wrong_silent"]))
    W, L, bar, gap = 620, 230, 14, 9
    H = len(rows) * (bar + gap) + 8
    x = lambda p: L + p * (W - L - 110)
    g = []
    for i, (name, hit, total) in enumerate(rows):
        y = i * (bar + gap) + 2 + (10 if i == len(rows) - 1 else 0)
        share = hit / total if total else 1
        if i == len(rows) - 1:
            g.append(f'<line x1="0" x2="{W}" y1="{y - 9}" y2="{y - 9}" stroke="{RULE}"/>')
        g.append(f'<text x="0" y="{y + 12}" font-size="11.5" fill="{INK}">{e(name)}</text>'
                 f'<rect x="{L}" y="{y}" width="{x(1) - L}" height="{bar}" fill="#ecebe6"/>'
                 f'<rect x="{L}" y="{y}" width="{x(share) - L:.1f}" height="{bar}" fill="{NAVY}"/>'
                 f'<text x="{x(1) + 10}" y="{y + 12}" font-size="11.5" fill="{INK}"><tspan font-weight="600">{share:.0%}</tspan>'
                 f'<tspan fill="{MUTED}">  {hit} of {total}</tspan></text>')
    return f'<svg width="{W}" height="{H}" font-family="{SANS}">{"".join(g)}</svg>'


def fig_cumulative(ys: list[float], label: str) -> str:
    W, H, L, R, T, B = 620, 160, 56, 110, 10, 26
    step = next(s for s in (10_000, 25_000, 50_000, 100_000, 150_000, 250_000) if ys[-1] / s <= 5)
    top = step * -(-ys[-1] // step)
    X = lambda i: L + i / 23 * (W - L - R)
    Y = lambda v: T + (1 - v / top) * (H - T - B)
    g = []
    v = 0
    while v <= top:
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{RULE if v else MUTED}"/>'
                 f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" font-size="10" fill="{MUTED}" text-anchor="end">{k(v) if v else "$0"}</text>')
        v += step
    for i in (0, 5, 11, 17, 23):
        g.append(f'<text x="{X(i):.1f}" y="{H - 10}" font-size="10" fill="{MUTED}" text-anchor="middle">Month {i + 1}</text>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    g.append(f'<polyline points="{pts}" fill="none" stroke="{NAVY}" stroke-width="2.2"/>'
             f'<circle cx="{X(23):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="{NAVY}"/>'
             f'<text x="{X(23) + 8:.1f}" y="{Y(ys[-1]) - 2:.1f}" font-size="11" fill="{INK}" font-weight="600">{k(ys[-1])}</text>'
             f'<text x="{X(23) + 8:.1f}" y="{Y(ys[-1]) + 11:.1f}" font-size="9.5" fill="{INK2}">{e(label)}</text>')
    return f'<svg width="{W}" height="{H}" font-family="{SANS}">{"".join(g)}</svg>'


# ---------- shared sections ----------

def value_table(p: dict, rate: float) -> str:
    return f"""<table>
<tr><td>Staff hours freed per year</td><td class="num">{p['hours_per_year']:,.0f}</td></tr>
<tr><td>Full-time equivalents</td><td class="num">{p['fte']:.1f}</td></tr>
<tr><td>Value of staff time at ${rate}/hour</td><td class="num">{usd(p['gross_usd'])}</td></tr>
<tr><td>Running cost (AI processing and hosting)</td><td class="num">{usd(p['run_usd'])}</td></tr>
<tr class="total"><td>Net value per year</td><td class="num">{usd(p['net_usd'])}</td></tr>
</table>"""


def breakeven_table(p: dict) -> str:
    b = p["breakeven_build_usd"]
    return f"""<table>
<tr><th>To pay for itself within</th><th class="num">6 months</th><th class="num">12 months</th><th class="num">24 months</th></tr>
<tr><td>The build can cost up to</td><td class="num">{k(b['6'])}</td><td class="num">{k(b['12'])}</td><td class="num">{k(b['24'])}</td></tr>
</table>"""


def sensitivity_table(p: dict, column_names: list[str]) -> str:
    rows = "".join(f"<tr><td>{v} a month</td>" + "".join(
        f'<td class="num{" hl" if (v, s) == (100, 1.0) else ""}">{k(p["sensitivity"][f"{v}|{s}"])}</td>' for s in (0.5, 1.0, 1.5)) + "</tr>"
        for v in (50, 100, 200))
    return ("<table><tr><th>Packages</th>" + "".join(f'<th class="num">{e(c)}</th>' for c in column_names) + f"</tr>{rows}</table>")


def test_basis(d: dict) -> dict:
    """How the wire step was tested, in words that match what was actually run."""
    m = d["measured"]
    if m.get("live"):
        return {"short": f"tested live on {m['packages']} different wire instructions",
                "detail": (f"The wire step was tested live on {m['packages']} synthetic wire instructions, each with its own beneficiary, "
                           "addresses, bank, routing number and account number, in six layouts chosen to be hard to read: repeated digits, "
                           "small type in dense tables, fax-quality scans and details on a second page. Every page was scanned to an image "
                           "first, so nothing could be read from a text layer."),
                "method": ("Mistral Document AI turns each page into text and gpt-6-luna reads that text twice. A field is flagged for "
                           "the reviewer when the two readings differ, when the value does not appear in the page text, when its "
                           "confidence is low, or, for routing numbers, when the ABA check digit fails."),
                "seconds": m["median_package_seconds"], "label": f"{m['packages']} live test packages"}
    recorded = [r for r in json.loads((EVALS / CONFIGS[d["config"]][0]).read_text())["results"] if "error" not in r]
    return {"short": f"tested on {len(recorded)} live readings of six deliberately difficult wire instruction layouts",
            "detail": (f"The wire step was tested on six synthetic wire instruction layouts chosen to be hard to read: repeated digits, "
                       f"small type in dense tables, fax-quality scans and details on a second page, all scanned to images. "
                       f"{len(recorded)} live readings of those layouts were run {m['packages']} times through the production software, "
                       "which scores every value and decides what to flag."),
            "method": (("Mistral Document AI turns each page into text and gpt-6-luna extracts the fields from that text. Mistral's own "
                        "reading of the page serves as a check: a field is flagged when the two disagree, when its confidence is low, or, "
                        "for routing numbers, when the ABA check digit fails.")
                       if d["config"].endswith("-extract") else
                       ("Mistral Document AI and gpt-6-luna each read the page text, and a field is flagged when they disagree, when its "
                        "confidence is low, or, for routing numbers, when the ABA check digit fails.")),
            "seconds": st.median(r["seconds"] for r in recorded), "label": f"{m['packages']} test packages"}


# ---------- reports ----------

def usecase1(d: dict) -> str:
    u, m, rate = d["uc1"], d["measured"], d["rate"]
    t = test_basis(d)
    n = m["packages"] - m["failed_rows"]
    imperfect = [f for f in FIELD_NAMES if m["field_correct"][f] < n]
    flag_clause = ("and flagged every value it got wrong for a person to check"
                   if m["wrong_silent"] == 0 else
                   f"but left {m['wrong_silent']} wrong values unflagged ({m['silent_money']} of them routing or account numbers)")
    caption = ("Every field was read correctly in every document." if not imperfect else
               "Below 100%: " + "; ".join(f"{FIELD_NAMES[f]}, {m['field_correct'][f]} of {n}" for f in imperfect) + ".")
    if "beneficiary_name" in imperfect and d["config"].endswith("-extract"):
        caption += (" Every beneficiary name miss came from one layout whose page text spelled “&” as “&amp;”, which was copied "
                    "into the name. The software now converts it back before extraction; not yet re-tested.")
    per_doc = u["manual_minutes_per_day"] / u["documents_per_day"]
    docs = u["documents_per_day"]
    scale_rows = "".join(
        f"<tr><td>{r['documents_per_day']:.0f} a day</td><td class=\"num\">{r['manual_minutes_per_day']:.0f} min</td>"
        f"<td class=\"num\">{r['system_minutes_per_day']:g} min</td><td class=\"num\">{r['hours_per_year']:,.0f} h</td>"
        f"<td class=\"num{' hl' if r['documents_per_day'] == docs else ''}\">{k(r['net_usd'])}</td></tr>" for r in u["scaling"])
    return f"""
<h1>Use Case 1</h1>
<p class="dek">Wire Instruction Extraction &nbsp;·&nbsp; Return on investment &nbsp;·&nbsp; October 2026</p>

<h2 style="margin-top:0">Summary</h2>
<p>Each wire transaction comes with a wire instruction document. Today a person reads each document and keys the beneficiary, bank, routing number and account number, which takes about {per_doc:.0f} minute per document: {u['manual_minutes_per_day']:.0f} minutes for the {docs} documents that arrive on a typical day. Our system processes the same {docs} documents in {u['system_minutes_per_day']:g} minute, {u['speedup']:.0f} times faster.</p>
<p>That returns about {u['saved_minutes_per_day']:.0f} minutes a day, or {u['hours_per_year']:,.0f} staff hours a year, worth about {k(u['gross_usd'])} a year before running costs and {k(u['net_usd'])} after them. The value grows in step with volume: at {u['scaling'][-1]['documents_per_day']:.0f} documents a day the system needs {u['scaling'][-1]['system_minutes_per_day']:g} minutes where a person would need {u['scaling'][-1]['manual_minutes_per_day'] / 60:.1f} hours. In testing it read {m['money_fields_correct']} of {m['money_fields']} routing and account numbers correctly {flag_clause}.</p>

<div class="figures">
<div><b>{u['manual_minutes_per_day']:.0f} → {u['system_minutes_per_day']:g} min</b><span>to process {docs} wire documents</span></div>
<div><b>{u['speedup']:.0f}×</b><span>faster than processing by hand</span></div>
<div><b>{u['hours_per_year']:,.0f} h</b><span>staff hours returned per year at {docs} documents a day</span></div>
<div><b>{m['money_fields_correct'] / m['money_fields']:.0%}</b><span>routing and account numbers read correctly in testing</span></div>
</div>

<h2>Time per day</h2>
<p>A person finds each detail in the wire instruction, types it into the workbook and checks it back. The system reads the document, fills in the details and highlights any field that needs a closer look.</p>
<figure><div class="fighead">Time to process {docs} wire documents</div>
{fig_bars([("By hand", u['manual_minutes_per_day'], TODAY), ("Our system", u['system_minutes_per_day'], NAVY)], 20, [(0, "0"), (5, "5 min"), (10, "10 min"), (15, "15 min"), (20, "20 min")])}
<figcaption><b>Figure 1.</b> {docs} documents at about {per_doc:.0f} minute each by hand, against {docs} documents a minute for the system.</figcaption></figure>

<h2>Accuracy</h2>
<p>{t['detail'].replace('packages', 'documents')}</p>
<figure><div class="fighead">Fields read correctly, {e(t['label'].replace('packages', 'documents'))}</div>{fig_accuracy(m)}
<figcaption><b>Figure 2.</b> {e(caption)} {m['packages_fully_right']} of {n} documents had all six fields right.</figcaption></figure>
<p>{t['method']} On average {m['flagged_per_row']:.1f} of the six fields are flagged per document. A character misread when the page is turned into text would pass the other checks; the check digit catches that for routing numbers, and for the other fields the reviewer's comparison with the document remains the control.</p>

<h2>Annual value</h2>
<table>
<tr><td>Documents per year ({docs} a day, {u['working_days_per_year']} working days)</td><td class="num">{docs * u['working_days_per_year']:,}</td></tr>
<tr><td>Staff hours returned per year</td><td class="num">{u['hours_per_year']:,.0f}</td></tr>
<tr><td>Value of staff time at ${rate}/hour</td><td class="num">{usd(u['gross_usd'])}</td></tr>
<tr><td>Running cost (AI processing and hosting)</td><td class="num">{usd(u['run_usd'])}</td></tr>
<tr class="total"><td>Net value per year</td><td class="num">{usd(u['net_usd'])}</td></tr>
</table>
<div class="keep"><p>Most of the running cost is hosting, which stays the same as volume rises, so the net value grows faster than volume. Per day and per year at different volumes:</p>
<table><tr><th>Documents</th><th class="num">By hand</th><th class="num">Our system</th><th class="num">Hours returned / year</th><th class="num">Net value / year</th></tr>{scale_rows}</table></div>
<div class="keep"><p>The build cost is not set yet. The table shows how much this use case could cost to build and still pay for itself at {docs} documents a day.</p>
{breakeven_table(u)}</div>

<h2>Running cost</h2>
<table class="speed">
<tr><td>AI processing per document</td><td class="num">${u['ai_per_document_usd']:.4f}</td></tr>
<tr><td>AI processing per year at {docs} documents a day</td><td class="num">about ${max(u['ai_per_document_usd'] * docs * u['working_days_per_year'], 1):,.0f}</td></tr>
<tr><td>Azure hosting, storage and monitoring per year</td><td class="num">about ${u['hosting_usd_per_month'] * 12:,.0f}</td></tr>
</table>
<p class="note">Azure list prices: Mistral Document AI $3.00 per 1,000 pages; gpt-6-luna $0.10 and $0.50 per million input and output tokens. Hosting is an estimate.</p>

<h2>Basis of the figures</h2>
<ul class="note">
<li><b>Provided by the business:</b> about {docs} wire documents a day; {u['manual_minutes_per_day']:.0f} minutes for a person to process them; {u['system_minutes_per_day']:g} minute for the system.</li>
<li><b>Measured:</b> accuracy and flagging, as described under Accuracy.</li>
<li><b>Estimated:</b> {u['working_days_per_year']} working days a year, a loaded staff cost of ${rate} an hour, and hosting cost.</li>
<li><b>Not included:</b> time spent checking highlighted fields, the cost of building the system, and the avoided cost of a misdirected wire. Staff hours returned are capacity for other work, not a budget reduction unless roles change.</li>
</ul>"""


def phase1(d: dict) -> str:
    p, rate, vol = d["phase1"], d["rate"], d["volume"]
    tasks = p["tasks"]
    biggest = max(tasks, key=lambda t: tasks[t]["before"] - tasks[t]["after"])
    return f"""
<h1>Use Case 2</h1>
<p class="dek">Treasury Loan Diligence Automation &nbsp;·&nbsp; Return on investment &nbsp;·&nbsp; October 2026</p>

<h2 style="margin-top:0">Summary</h2>
<p>Use Case 2 automates the rest of the package work around the wire instructions: collecting the request and its attachments, checking the settlement statement against the email and the wire, listing exceptions, and preparing the triage workbook, CashPro file and BCMP values. It builds on Use Case 1, which already reads the wire instructions.</p>
<p>Once Use Case 1 is in place a package takes about {p['package_minutes_before']:.0f} minutes of staff time. Use Case 2 is expected to bring that to about {p['package_minutes_after']:.0f} minutes. At roughly {vol} packages a month that frees a further {p['hours_per_year']:,.0f} staff hours a year, the equivalent of {p['fte']:.1f} full-time positions, worth about {k(p['net_usd'])} a year after running costs of about {usd(p['run_usd'])}. Use Case 2 is not built yet, so these figures are estimates to be confirmed in the pilot.</p>

<div class="figures">
<div><b>{p['package_minutes_before']:.0f} → {p['package_minutes_after']:.0f} min</b><span>expected staff time per package, after Use Case 1</span></div>
<div><b>{p['hours_per_year']:,.0f} h</b><span>additional staff hours freed per year</span></div>
<div><b>{k(p['net_usd'])}</b><span>net value per year at {vol} packages a month</span></div>
<div><b>${p['run_per_package_usd']:.3f}</b><span>AI cost per package for the added steps</span></div>
</div>

<h2>What Use Case 2 adds</h2>
<ul>
<li>Request emails and attachments collected into a standard SharePoint package for each loan.</li>
<li>Automatic checks between the internal settlement statement, the request email and the wire instructions: amounts, fees, fund, dates, routing number format and masked accounts.</li>
<li>A list of exceptions for Accounting, each with the reason it was raised.</li>
<li>The triage workbook, the BOA CashPro import file and the BCMP values, ready for review.</li>
</ul>
<p>Accounting keeps the controls it has today: review of the source documents and outputs, resolution of flagged values, CashPro and ProMerit entry, second-person approval and final release. The system prepares payments. It does not send them.</p>

<h2>Where the time goes</h2>
<figure><div class="fighead">Staff time per package</div>
{fig_bars([("With Use Case 1", p['package_minutes_before'], TODAY), ("With Use Cases 1 and 2", p['package_minutes_after'], NAVY)], 240, [(0, "0 h"), (60, "1 h"), (120, "2 h"), (180, "3 h"), (240, "4 h")])}
<figcaption><b>Figure 1.</b> Use Case 2 removes about {p['saved_minutes']:.0f} minutes from each package, {p['saved_pct_of_package']:.0%} of the time left once Use Case 1 is running.</figcaption></figure>
<figure><div class="fighead">Minutes per package, by task</div>{fig_tasks(tasks, 'With Use Case 1', 'With Use Case 2')}
<figcaption><b>Figure 2.</b> The largest reduction is in {TASK_NAMES[biggest].lower()}. Exceptions keep the most manual time, because call-backs to verify masked or changed wire details stay with a person.</figcaption></figure>

<h2>Annual value</h2>
{value_table(p, rate)}
<div class="keep"><p>The build cost is not set yet. The table shows how much Use Case 2 could cost to build and still pay for itself from its net value.</p>
{breakeven_table(p)}</div>
<div class="keep"><p>The saving depends mainly on volume and on how much review work is left once each step is automated. Net value per year:</p>
{sensitivity_table(p, ['Half the estimated review work', 'As estimated', '50% more review work'])}</div>
<figure><div class="fighead">Cumulative net value of Use Case 2 over two years</div>{fig_cumulative(p['cumulative_24m'], 'Use Case 2')}
<figcaption><b>Figure 3.</b> Volume starts at about {vol} packages a month and grows {d['growth']:.0%} a month. With no growth the two-year figure is about {k(p['net_24m_no_growth'])}. Build cost is not included.</figcaption></figure>

<h2>Running cost</h2>
<table class="speed">
<tr><td>AI reading of the settlement statement and email, per package</td><td class="num">${p['run_per_package_usd']:.4f}</td></tr>
<tr><td>AI processing per year at {vol} packages a month</td><td class="num">about ${max(p['run_per_package_usd'] * vol * 12, 1):,.0f}</td></tr>
<tr><td>Additional hosting: mailbox and SharePoint automation, storage</td><td class="num">about ${p['hosting_usd_per_month'] * 12:,.0f} a year</td></tr>
</table>
<p class="note">Priced at the same Azure rates as Use Case 1, assuming about {d['phase1_pages']} pages per package for the settlement statement and email. Use Case 2 runs on the Azure services Use Case 1 already pays for, so only the additional hosting is counted here.</p>

<h2>Basis of the figures</h2>
<ul class="note">
<li><b>Provided by the business:</b> about four hours of staff time per package today, and about {vol} loans a month (from the Treasury loan volume).</li>
<li><b>Estimated:</b> how the four hours divide across tasks; the share of each task that remains with a person once it is automated (intake {d['residuals']['intake']:.0%}, cross-document checks {d['residuals']['cross_doc']:.0%}, exceptions {d['residuals']['exceptions']:.0%}, output files {d['residuals']['outputs']:.0%}); a loaded staff cost of ${rate} an hour; {d['growth']:.0%} monthly growth; AI pages per package and hosting cost.</li>
<li><b>Not yet tested:</b> the cross-document checks and exception rules. Their accuracy, and the time they save, will be measured in the pilot alongside the current process.</li>
<li><b>Not included:</b> the cost of building Use Case 2, and the avoided cost of a misdirected wire. Staff hours freed are capacity for other work, not a budget reduction unless roles change.</li>
</ul>"""


CSS = f"""
@page {{ size: Letter; margin: 0.85in 0.95in 0.9in; }}
body {{ font-family: 'Bitstream Charter', Charter, Georgia, serif; font-size: 10.3pt; line-height: 1.45; color: {INK}; margin: 0; }}
h1 {{ font-family: {SANS}; font-size: 21pt; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 4pt; }}
.dek {{ font-family: {SANS}; color: {INK2}; font-size: 10pt; margin: 0 0 18pt; padding-bottom: 12pt; border-bottom: 1.5pt solid {INK}; }}
h2 {{ font-family: {SANS}; font-size: 12.5pt; font-weight: 600; margin: 16pt 0 5pt; break-after: avoid; }}
p {{ margin: 0 0 8pt; }}
.figures {{ display: flex; border-top: 0.75pt solid {RULE}; border-bottom: 0.75pt solid {RULE}; margin: 12pt 0 4pt; font-family: {SANS}; }}
.figures div {{ flex: 1; padding: 9pt 10pt 9pt 0; }}
.figures div + div {{ padding-left: 12pt; border-left: 0.75pt solid {RULE}; }}
.figures b {{ display: block; font-size: 15pt; font-weight: 600; color: {NAVY}; line-height: 1.25; }}
.figures span {{ font-size: 8.6pt; color: {INK2}; line-height: 1.35; display: block; }}
figure {{ margin: 8pt 0 10pt; break-inside: avoid; }}
figcaption {{ font-family: {SANS}; font-size: 8.8pt; color: {INK2}; margin-top: 6pt; }}
figcaption b {{ color: {INK}; font-weight: 600; }}
.fighead {{ font-family: {SANS}; font-size: 9.8pt; font-weight: 600; margin-bottom: 8pt; }}
table {{ border-collapse: collapse; width: 100%; font-family: {SANS}; font-size: 9.2pt; margin: 6pt 0 12pt; break-inside: avoid; }}
th {{ text-align: left; font-weight: 600; color: {INK2}; border-bottom: 1pt solid {INK}; padding: 4pt 6pt 4pt 0; }}
td {{ border-bottom: 0.5pt solid {RULE}; padding: 4.5pt 6pt 4.5pt 0; vertical-align: top; }}
table.speed td:first-child {{ width: 46%; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.hl {{ font-weight: 600; color: {NAVY}; }}
tr.total td {{ border-top: 1pt solid {INK}; border-bottom: none; font-weight: 600; }}
ul {{ margin: 0 0 8pt; padding-left: 14pt; }} li {{ margin-bottom: 3pt; }}
.note {{ font-size: 9.2pt; color: {INK2}; }}
.keep {{ break-inside: avoid; }}
"""


def render(body: str, title: str, target: Path, browser) -> None:
    page = OUT / "client_report.html"
    page.write_text(f'<!doctype html><html><head><meta charset="utf-8"><title>{e(title)}</title><style>{CSS}</style></head><body>{body}</body></html>')
    footer = (f'<div style="font-family:Inter,sans-serif;font-size:7.5pt;color:{MUTED};width:100%;padding:0 0.95in;'
              f'display:flex;justify-content:space-between"><span>{e(title)}</span>'
              '<span><span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
    tab = browser.new_page()
    tab.goto(page.resolve().as_uri())
    tab.pdf(path=str(target), format="Letter", prefer_css_page_size=True, print_background=True,
            display_header_footer=True, header_template="<span></span>", footer_template=footer)
    tab.close()
    print("wrote", target)


def load() -> dict:
    d = json.loads((OUT / "phases.json").read_text())
    a = json.loads((OUT / "assumptions.json").read_text())
    d["review"] = a["review"]
    d["residuals"] = {t: a["tasks"][t]["phase1_residual"] for t in d["phase1"]["tasks"]}
    d["phase1_pages"] = a["phase1_run_cost"]["extra_pages_per_package"]
    return d


def main() -> None:
    d = load()
    with sync_playwright() as pw:
        bundled = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")  # pre-installed in cloud sessions
        browser = pw.chromium.launch(executable_path=str(bundled) if bundled.exists() else None)
        render(usecase1(d), "Use Case 1 – Wire Instruction Extraction", OUT / "UseCase1_ROI.pdf", browser)
        render(phase1(d), "Use Case 2 – Treasury Loan Diligence Automation", OUT / "UseCase2_ROI.pdf", browser)


if __name__ == "__main__":
    main()
