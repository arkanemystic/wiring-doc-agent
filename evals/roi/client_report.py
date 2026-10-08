"""Client-facing Phase 1 benefits report as a PDF.

Usage (from the repo root): python -m evals.roi.client_report [out.pdf]
Reads evals/roi/roi.json and assumptions.json (python -m evals.roi.roi first). Default output:
evals/roi/Phase1_Benefits.pdf. Needs Playwright with Chromium.
"""
import html, json, sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
NOW, P1 = "Current build (wire extraction live)", "Phase 1 complete (projected)"
TASKS = ["intake", "wire_extraction", "cross_doc", "exceptions", "outputs"]
TASK_NAMES = {"intake": "Intake and package set-up", "wire_extraction": "Wire instruction data entry",
              "cross_doc": "Cross-document checks", "exceptions": "Exceptions and call-backs",
              "outputs": "Workbook, CashPro and BCMP files"}
INK, INK2, MUTED, RULE = "#1d1d1b", "#55534e", "#8a877f", "#d9d7cf"
TODAY, MID, NAVY = "#b9b6ad", "#6d9bd1", "#1f4e8c"
SANS = "Inter, 'Liberation Sans', sans-serif"
e = html.escape


def k(x: float) -> str:
    return f"${x / 1000:,.0f}k"


def fig_totals(sc) -> str:
    rows = [("Today", sc["Manual today"]["minutes"], TODAY), ("Wire step automated", sc[NOW]["minutes"], MID),
            ("Phase 1 complete", sc[P1]["minutes"], NAVY)]
    W, L, bar, gap = 620, 150, 26, 14
    H = len(rows) * (bar + gap) + 26
    x = lambda m: L + m / 240 * (W - L - 70)
    g = [f'<line x1="{x(t)}" x2="{x(t)}" y1="0" y2="{H - 22}" stroke="{RULE}" stroke-width="1"/>'
         f'<text x="{x(t)}" y="{H - 6}" font-size="10" fill="{MUTED}" text-anchor="middle">{t // 60} h</text>' for t in (0, 60, 120, 180, 240)]
    for i, (name, m, c) in enumerate(rows):
        y = i * (bar + gap) + 4
        g.append(f'<text x="0" y="{y + bar / 2 + 4}" font-size="11.5" fill="{INK}">{e(name)}</text>'
                 f'<rect x="{L}" y="{y}" width="{x(m) - L:.1f}" height="{bar}" fill="{c}"/>'
                 f'<text x="{x(m) + 8:.1f}" y="{y + bar / 2 + 4}" font-size="11.5" fill="{INK}" font-weight="600">{m:.0f} min</text>')
    return f'<svg width="{W}" height="{H}" font-family="{SANS}">{"".join(g)}</svg>'


def fig_tasks(sc) -> str:
    W, L, row = 620, 200, 30
    H = len(TASKS) * row + 40
    x = lambda m: L + m / 80 * (W - L - 40)
    g = [f'<line x1="{x(t)}" x2="{x(t)}" y1="16" y2="{H - 22}" stroke="{RULE}"/>'
         f'<text x="{x(t)}" y="{H - 6}" font-size="10" fill="{MUTED}" text-anchor="middle">{t} min</text>' for t in (0, 20, 40, 60, 80)]
    g.append(f'<circle cx="{L + 4}" cy="6" r="4.5" fill="{TODAY}"/><text x="{L + 14}" y="10" font-size="10.5" fill="{INK2}">Today</text>'
             f'<circle cx="{L + 70}" cy="6" r="4.5" fill="{NAVY}"/><text x="{L + 80}" y="10" font-size="10.5" fill="{INK2}">After Phase 1</text>')
    for i, t in enumerate(TASKS):
        y = 34 + i * row
        a, b = sc["Manual today"]["tasks"][t], sc[P1]["tasks"][t]
        g.append(f'<text x="0" y="{y + 4}" font-size="11.5" fill="{INK}">{e(TASK_NAMES[t])}</text>'
                 f'<line x1="{x(b):.1f}" x2="{x(a):.1f}" y1="{y}" y2="{y}" stroke="{RULE}" stroke-width="3"/>'
                 f'<circle cx="{x(a):.1f}" cy="{y}" r="5.5" fill="{TODAY}"/><circle cx="{x(b):.1f}" cy="{y}" r="5.5" fill="{NAVY}"/>'
                 f'<text x="{x(b) - 10:.1f}" y="{y + 4}" font-size="10.5" fill="{NAVY}" text-anchor="end" font-weight="600">{b:.0f}</text>'
                 f'<text x="{x(a) + 10:.1f}" y="{y + 4}" font-size="10.5" fill="{INK2}">{a:.0f}</text>')
    return f'<svg width="{W}" height="{H}" font-family="{SANS}">{"".join(g)}</svg>'


FIELD_NAMES = {"routing_number_aba": "Routing number (ABA)", "account_number": "Account number",
               "bank_name": "Bank name", "bank_address": "Bank address", "beneficiary_name": "Beneficiary name",
               "beneficiary_address": "Beneficiary address"}


def fig_accuracy(m) -> str:
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


def fig_cumulative(series: dict[str, list[float]]) -> str:
    W, H, L, R, T, B = 620, 160, 56, 110, 10, 26
    top = 600_000
    X = lambda i: L + i / 23 * (W - L - R)
    Y = lambda v: T + (1 - v / top) * (H - T - B)
    g = []
    for v in range(0, top + 1, 150_000):
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{RULE if v else MUTED}"/>'
                 f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" font-size="10" fill="{MUTED}" text-anchor="end">{k(v) if v else "$0"}</text>')
    for i in (0, 5, 11, 17, 23):
        g.append(f'<text x="{X(i):.1f}" y="{H - 10}" font-size="10" fill="{MUTED}" text-anchor="middle">Month {i + 1}</text>')
    for (name, ys), c, dash in zip(series.items(), (NAVY, MID), ("", 'stroke-dasharray="5 4"')):
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
        g.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2.2" {dash}/>'
                 f'<circle cx="{X(23):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5" fill="{c}"/>'
                 f'<text x="{X(23) + 8:.1f}" y="{Y(ys[-1]) - 2:.1f}" font-size="11" fill="{INK}" font-weight="600">{k(ys[-1])}</text>'
                 f'<text x="{X(23) + 8:.1f}" y="{Y(ys[-1]) + 11:.1f}" font-size="9.5" fill="{INK2}">{e(name)}</text>')
    return f'<svg width="{W}" height="{H}" font-family="{SANS}">{"".join(g)}</svg>'


def build() -> str:
    roi = json.loads((OUT / "roi.json").read_text())
    a = json.loads((OUT / "assumptions.json").read_text())
    c = roi["configs"][roi["recommended"]]
    if not c["measured"].get("live"):
        raise SystemExit("No live run of the combined unit in roi.json: run python -m evals.roi.live, then python -m evals.roi.roi.")
    m, sc, api = c["measured"], c["scenarios"], c["run_cost_per_package_usd"]
    p1, now = sc[P1], sc[NOW]
    rate, vol, growth = a["loaded_cost_per_hour_usd"]["value"], a["volume_packages_per_month"]["value"], a["volume_packages_per_month"]["growth_per_month"]
    hosting = a["run_cost"]["hosting_usd_per_month"]

    def cumulative(s):
        tot, ys = 0.0, []
        for mo in range(24):
            v = vol * (1 + growth) ** mo
            tot += sc[s]["saved_minutes"] / 60 * v * rate - (api * v + hosting)
            ys.append(tot)
        return ys
    cum1, cumnow = cumulative(P1), cumulative(NOW)
    flat = sc[P1]["saved_minutes"] / 60 * vol * rate * 24 - (api * vol + hosting) * 24
    grid = roi["sensitivity"]
    batch_min, batch_s = divmod(round(m["wall_seconds"]), 60)
    run_year = p1["run_usd"]
    flag_sentence = (" and flagged every value it got wrong, so nothing incorrect reached the reviewer unmarked."
                     if m["wrong_silent"] == 0 else
                     f". {m['wrong_silent']} wrong values ({m['silent_money']} of them routing or account numbers) were not flagged"
                     " and would rely on the reviewer to catch them.")
    imperfect = [f for f in FIELD_NAMES if m["field_correct"][f] < m["packages"] - m["failed_rows"]]
    accuracy_caption = (
        "Every field was read correctly in every package." if not imperfect else
        "Fields below 100%: " + "; ".join(f"{FIELD_NAMES[f]} {m['field_correct'][f]} of {m['packages'] - m['failed_rows']}" for f in imperfect)
        + (". Every one of those values was flagged for the reviewer." if m["wrong_silent"] == 0 else
           f". {m['wrong_silent']} of the wrong values were not flagged."))

    sens_rows = "".join(
        f"<tr><td>{v} a month</td>" + "".join(
            f'<td class="num{" hl" if (v, s) == (100, 1.0) else ""}">{k(grid[f"{v}|{s}"]["net_usd"])}</td>' for s in (0.5, 1.0, 1.5)) + "</tr>"
        for v in (50, 100, 200))

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Initial Funding Automation: Phase 1</title><style>
@page {{ size: Letter; margin: 0.85in 0.95in 0.9in; }}
body {{ font-family: 'Bitstream Charter', Charter, Georgia, serif; font-size: 10.3pt; line-height: 1.45; color: {INK}; margin: 0; }}
h1 {{ font-family: {SANS}; font-size: 21pt; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 4pt; }}
.dek {{ font-family: {SANS}; color: {INK2}; font-size: 10pt; margin: 0 0 18pt; padding-bottom: 12pt; border-bottom: 1.5pt solid {INK}; }}
h2 {{ font-family: {SANS}; font-size: 12.5pt; font-weight: 600; margin: 16pt 0 5pt; break-after: avoid; }}
p {{ margin: 0 0 8pt; }}
.figures {{ display: flex; border-top: 0.75pt solid {RULE}; border-bottom: 0.75pt solid {RULE}; margin: 12pt 0 4pt; font-family: {SANS}; }}
.figures div {{ flex: 1; padding: 9pt 10pt 9pt 0; }}
.figures div + div {{ padding-left: 12pt; border-left: 0.75pt solid {RULE}; }}
.figures b {{ display: block; font-size: 16pt; font-weight: 600; color: {NAVY}; line-height: 1.25; }}
.figures span {{ font-size: 8.6pt; color: {INK2}; line-height: 1.35; display: block; }}
figure {{ margin: 8pt 0 10pt; break-inside: avoid; }}
figcaption {{ font-family: {SANS}; font-size: 8.8pt; color: {INK2}; margin-top: 6pt; }}
figcaption b {{ color: {INK}; font-weight: 600; }}
.fighead {{ font-family: {SANS}; font-size: 9.8pt; font-weight: 600; margin-bottom: 8pt; }}
table {{ border-collapse: collapse; width: 100%; font-family: {SANS}; font-size: 9.2pt; margin: 6pt 0 12pt; break-inside: avoid; }}
th {{ text-align: left; font-weight: 600; color: {INK2}; border-bottom: 1pt solid {INK}; padding: 4pt 6pt 4pt 0; }}
td {{ border-bottom: 0.5pt solid {RULE}; padding: 4.5pt 6pt 4.5pt 0; vertical-align: top; }}
table.speed td:first-child {{ width: 40%; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.hl {{ font-weight: 600; color: {NAVY}; }}
tr.total td {{ border-top: 1pt solid {INK}; border-bottom: none; font-weight: 600; }}
ul {{ margin: 0 0 8pt; padding-left: 14pt; }} li {{ margin-bottom: 3pt; }}
.note {{ font-size: 9.2pt; color: {INK2}; }}
.keep {{ break-inside: avoid; }}
</style></head><body>

<h1>Initial Funding Automation: Phase 1</h1>
<p class="dek">Expected improvements to the funding package review &nbsp;·&nbsp; October 2026</p>

<h2 style="margin-top:0">Summary</h2>
<p>Phase 1 is expected to reduce the Accounting effort on each initial funding package from about four hours to about one. At the current volume of roughly {vol} loans a month, that would free about {p1['hours_per_year']:,.0f} staff hours a year, the equivalent of {p1['fte']:.0f} full-time positions, worth about {k(p1['net_usd'])} a year after running costs of about ${round(run_year, -2):,.0f}. Every existing review, approval, bank-entry and release step stays with Accounting.</p>
<p>The wire instruction step has been built and tested live on {m['packages']} different wire instructions. Mistral Document AI reads each page and gpt-6-luna extracts the payment details from that text. It read {m['money_fields_correct']} of {m['money_fields']} routing and account numbers correctly{flag_sentence} Intake, cross-document checks, exception handling and the output files are still to be built, so the savings for those steps are estimates.</p>

<div class="figures">
<div><b>4 h → {p1['minutes'] / 60:.0f} h</b><span>expected staff time per funding package</span></div>
<div><b>{p1['hours_per_year']:,.0f} h</b><span>staff hours freed per year, about {p1['fte']:.0f} FTE</span></div>
<div><b>{k(p1['net_usd'])}</b><span>net value per year at {vol} packages a month</span></div>
<div><b>${api:.3f}</b><span>AI cost per wire instruction, against ${4 * rate} of staff time today</span></div>
</div>

<h2>Where the time goes</h2>
<p>Today one person assembles each package, keys the wire details, checks the settlement statement against the email and the wire, chases exceptions and prepares the CashPro and BCMP files. After Phase 1 the package arrives assembled and checked, and the reviewer works from a list of flagged items rather than from the source documents.</p>
<figure><div class="fighead">Staff time per funding package</div>{fig_totals(sc)}
<figcaption><b>Figure 1.</b> Automating the wire step alone saves about {now['saved_minutes']:.0f} minutes a package ({now['saved_pct']:.0%}). With all of Phase 1 in place, the saving is about {p1['saved_minutes'] / 60:.0f} hours ({p1['saved_pct']:.0%}).</figcaption></figure>
<figure><div class="fighead">Minutes per package, by task</div>{fig_tasks(sc)}
<figcaption><b>Figure 2.</b> The largest reductions are in cross-document checks and in preparing output files. Exceptions keep the most manual time, because call-backs to verify masked or changed wire details stay with a person.</figcaption></figure>

<h2>What Phase 1 delivers</h2>
<ul>
<li>Funding request emails and attachments collected into a standard SharePoint package for each loan.</li>
<li>Beneficiary name and address, bank name and address, routing number and account number read from the wire instructions.</li>
<li>Automatic checks between the internal settlement statement, the request email and the wire instructions: amounts, fees, fund, dates, routing number format and masked accounts.</li>
<li>A list of exceptions for Accounting, each with the reason it was raised.</li>
<li>The IF triage workbook, the BOA CashPro import file and the BCMP wet-funding values, ready for review.</li>
</ul>
<p>Accounting keeps the controls it has today: review of the source documents and outputs, resolution of flagged values, CashPro and ProMerit entry, second-person approval and final release. The system prepares payments. It does not send them.</p>

<h2>Accuracy</h2>
<p>The wire step was tested on {m['packages']} synthetic wire instructions, each with its own beneficiary, addresses, bank, routing number and account number. They use six layouts chosen to be hard to read: repeated digits, small type in dense tables, fax-quality scans and details on a second page. Every page was scanned to an image first, so nothing could be read from a text layer.</p>
<figure><div class="fighead">Fields read correctly, {m['packages']} live test packages</div>{fig_accuracy(m)}
<figcaption><b>Figure 3.</b> {e(accuracy_caption)} {m['packages_fully_right']} of {m['packages'] - m['failed_rows']} packages had all six fields right.</figcaption></figure>
<p>Mistral Document AI turns each page into text, and gpt-6-luna reads that text twice. A field is flagged for the reviewer when the two readings differ, when the value does not appear in the page text, when its confidence is low, or, for routing numbers, when the ABA check digit fails. On average {m['flagged_per_row']:.1f} of the six fields are flagged per package. Both readings work from the same page text, so a character the page reader gets wrong would pass the other checks. The check digit catches that for routing numbers; for the other fields, the reviewer's comparison with the source document remains the control.</p>

<h2>Annual value</h2>
<table>
<tr><th></th><th class="num">Wire step automated</th><th class="num">Phase 1 complete</th></tr>
<tr><td>Staff hours freed per year</td><td class="num">{now['hours_per_year']:,.0f}</td><td class="num">{p1['hours_per_year']:,.0f}</td></tr>
<tr><td>Full-time equivalents</td><td class="num">{now['fte']:.1f}</td><td class="num">{p1['fte']:.1f}</td></tr>
<tr><td>Value of staff time at ${rate}/hour</td><td class="num">${round(now['gross_usd'], -2):,.0f}</td><td class="num">${round(p1['gross_usd'], -2):,.0f}</td></tr>
<tr><td>Running cost</td><td class="num">${round(now['run_usd'], -2):,.0f}</td><td class="num">${round(p1['run_usd'], -2):,.0f}</td></tr>
<tr class="total"><td>Net value per year</td><td class="num">${round(now['net_usd'], -2):,.0f}</td><td class="num">${round(p1['net_usd'], -2):,.0f}</td></tr>
</table>
<figure><div class="fighead">Cumulative net value over two years</div>{fig_cumulative({"Phase 1 complete": cum1, "Wire step only": cumnow})}
<figcaption><b>Figure 4.</b> Volume is currently about {vol} loans a month and growing. This assumes {growth:.0%} growth a month, reaching about {vol * (1 + growth) ** 23:.0f} packages in month 24; with no growth the two-year figure is about {k(flat)}. Build costs are not included.</figcaption></figure>
<div class="keep"><p>The result depends mainly on volume and on how much review work is left once each step is automated. The table shows net value per year for Phase 1 under different combinations.</p>
<table>
<tr><th>Packages</th><th class="num">Half the estimated review work</th><th class="num">As estimated</th><th class="num">50% more review work</th></tr>
{sens_rows}
</table></div>

<h2>Speed and running cost</h2>
<table class="speed">
<tr><th></th><th class="num">By hand today</th><th class="num">After Phase 1</th></tr>
<tr><td>Wire instruction processing per package</td><td class="num">about 40 minutes of keying</td><td class="num">{m['median_package_seconds']:.{0 if m['median_package_seconds'] >= 10 else 1}f} seconds (median), then review</td></tr>
<tr><td>Staff time per package</td><td class="num">4 hours</td><td class="num">about {p1['minutes']:.0f} minutes</td></tr>
<tr><td>Cost per package</td><td class="num">${4 * rate} staff time</td><td class="num">${p1['minutes'] / 60 * rate:,.0f} staff time + ${api:.4f} AI</td></tr>
<tr><td>AI processing per year, {vol} packages a month</td><td class="num">–</td><td class="num">about ${max(api * vol * 12, 1):,.0f}</td></tr>
<tr><td>Azure hosting, storage and monitoring per year</td><td class="num">–</td><td class="num">about ${hosting * 12:,.0f}</td></tr>
</table>
<p class="note">AI processing is priced at Microsoft's published Azure rates: Mistral Document AI at $3.00 per 1,000 pages and gpt-6-luna at $0.10 per million input tokens and $0.50 per million output tokens, with token counts measured in the live test. The figure covers the wire instruction only; reading the settlement statement and email in Phase 1 adds a similar amount per page. The hosting figure is an estimate.</p>

<h2>Basis of the figures</h2>
<ul class="note">
<li><b>Measured:</b> accuracy, flagging, number of flagged fields and processing time of the wire step, from live runs on {m['packages']} synthetic wire instructions.</li>
<li><b>Provided by the business:</b> about four hours of staff time per package today, and about {vol} loans a month (from the Treasury loan volume).</li>
<li><b>Estimated:</b> how the four hours divide across tasks, reviewer minutes per package and per flagged field, the review time left after each other step is automated, a loaded staff cost of ${rate} an hour, {growth:.0%} monthly growth and hosting cost.</li>
<li><b>Not included:</b> the cost of building Phase 1, and the avoided cost of a misdirected wire. Staff hours freed are capacity for other work, not a budget reduction unless roles change.</li>
</ul>
</body></html>"""


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "Phase1_Benefits.pdf"
    page = OUT / "client_report.html"
    page.write_text(build())
    footer = (f'<div style="font-family:Inter,sans-serif;font-size:7.5pt;color:{MUTED};width:100%;padding:0 0.95in;'
              'display:flex;justify-content:space-between"><span>Initial Funding Automation: Phase 1</span>'
              '<span><span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
    with sync_playwright() as p:
        bundled = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")  # pre-installed in cloud sessions
        browser = p.chromium.launch(executable_path=str(bundled) if bundled.exists() else None)
        tab = browser.new_page()
        tab.goto(page.resolve().as_uri())
        tab.pdf(path=str(target), format="Letter", prefer_css_page_size=True, print_background=True,
                display_header_footer=True, header_template="<span></span>", footer_template=footer)
    print("wrote", target)


if __name__ == "__main__":
    main()
