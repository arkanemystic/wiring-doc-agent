"""ROI dashboard: charts comparing gpt-6-luna and the Mistral configs on cost, accuracy, safety, speed and value.

Usage (from the repo root): python -m evals.roi.charts
Reads evals/roi/roi.json (python -m evals.roi.roi), evals/roi/results.json, evals/roi/assumptions.json and the
raw live reads in evals/<config>/results.json. Writes evals/roi/dashboard.html (self-contained, no scripts loaded).
"""
import html, json, math, statistics as st
from pathlib import Path

from evals.harness import DOCS, FIELDS

OUT = Path(__file__).parent
EVALS = OUT.parent
CONFIGS = ["gpt-6-luna", "mistral-document-ai-2512-image-only", "mistral-ocr+gpt-6-luna"]
SHORT = {"gpt-6-luna": "gpt-6-luna", "mistral-document-ai-2512-image-only": "Mistral Document AI",
         "mistral-ocr+gpt-6-luna": "Mistral OCR + gpt-6-luna"}
SLOT = {c: i + 1 for i, c in enumerate(CONFIGS)}  # categorical slot follows the config everywhere
MONEY = ("routing_number_aba", "account_number")
P1, NOW = "Phase 1 complete (projected)", "Current build (wire extraction live)"
e = html.escape


def money(x: float, digits: int = 0) -> str:
    if abs(x) >= 1e6:
        return f"${x / 1e6:.2f}M"
    if abs(x) >= 1e4:
        return f"${x / 1e3:,.0f}k"
    return f"${x:,.{digits}f}"


def cost_parts(c: str, a: dict, pages: float) -> dict:
    r = a["run_cost"][c]
    reads = r["reads_per_doc"]
    return {"gpt-6-luna input tokens": reads * r.get("input_tokens_per_read", 0) * r.get("usd_per_m_input_tokens", 0) / 1e6,
            "gpt-6-luna output tokens": reads * r.get("output_tokens_per_read", 0) * r.get("usd_per_m_output_tokens", 0) / 1e6,
            "Mistral pages": reads * pages * r.get("usd_per_1000_pages", 0) / 1000}


def calibration(c: str) -> tuple[float, float]:
    reads = [r for r in json.loads((EVALS / c / "results.json").read_text())["results"] if "error" not in r]
    cells = [v for r in reads for v in r["fields"].values()]
    right = [v["confidence"] for v in cells if v["correct"]]
    wrong = [v["confidence"] for v in cells if not v["correct"]]
    return st.mean(right), (st.mean(wrong) if wrong else float("nan"))


def recorded_seconds(c: str) -> float:
    reads = [r for r in json.loads((EVALS / c / "results.json").read_text())["results"] if "error" not in r]
    per_read = st.median(r["seconds"] for r in reads)
    # Production makes two passes per document; the pipeline's recorded time already covers both of its calls.
    return per_read if c == "mistral-ocr+gpt-6-luna" else 2 * per_read


# ---------- chart builders (HTML bars, SVG lines/heatmaps) ----------

def hbars(rows: list[tuple[str, float, int, str, str]], unit_max: float | None = None, ref: tuple[float, str] | None = None) -> str:
    """rows: (label, value, slot, value text, tooltip). Bars anchored at zero; one optional reference line."""
    top = unit_max or max(v for _, v, *_ in rows) or 1
    out = ['<div class="hbars">']
    for n, (label, v, slot, text, tip) in enumerate(rows):
        w = max(v / top * 100, 0.6 if v > 0 else 0)
        out.append(f'<div class="hrow" data-tip="{e(tip)}"><div class="hl">{e(label)}</div><div class="htrack">'
                   f'<div class="hbar" style="width:{w:.2f}%;background:var(--s{slot})"></div>'
                   + (f'<div class="href" style="left:{ref[0] / top * 100:.2f}%">' + (f'<span>{e(ref[1])}</span>' if n == 0 else "") + '</div>' if ref else "")
                   + f'</div><div class="hv">{e(text)}</div></div>')
    out.append("</div>")
    return "".join(out)


def stacked(rows: list[tuple[str, list[tuple[str, float]], str]], colors: list[str], total_max: float) -> str:
    out = ['<div class="hbars">']
    for label, parts, total_text in rows:
        segs = "".join(
            f'<div class="seg" style="width:{v / total_max * 100:.3f}%;background:{colors[i]}" '
            f'data-tip="{e(label)} - {e(name)}: {v:.0f} min"></div>' for i, (name, v) in enumerate(parts) if v > 0)
        out.append(f'<div class="hrow"><div class="hl">{e(label)}</div><div class="htrack stack">{segs}</div>'
                   f'<div class="hv">{e(total_text)}</div></div>')
    out.append("</div>")
    return "".join(out)


def legend(items: list[tuple[str, str]], dashed: set[str] = frozenset()) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i class="{"dash" if name in dashed else ""}" style="background:{c}"></i>{e(name)}</span>' for name, c in items) + "</div>"


def line_chart(series: list[dict], xs: list[float], x_label, y_fmt, x_fmt=str, height=260, width=480) -> str:
    """series: {name, ys, color, dash}. Single y-axis from zero (or the data minimum when negative)."""
    W, H, L, R, T, B = width, height, 56, 150, 14, 34
    ymax = max(max(s["ys"]) for s in series)
    ymin = min(0, min(min(s["ys"]) for s in series))
    step = nice_step((ymax - ymin) / 4)
    top = step * -(-ymax // step)
    bot = step * (ymin // step)
    X = lambda x: L + (x - xs[0]) / (xs[-1] - xs[0]) * (W - L - R)
    Y = lambda y: T + (top - y) / (top - bot) * (H - T - B)
    g = []
    y = bot
    while y <= top + 1e-9:
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(y):.1f}" y2="{Y(y):.1f}" class="{"axis" if y == 0 else "grid"}"/>'
                 f'<text x="{L - 8}" y="{Y(y) + 4:.1f}" class="tick" text-anchor="end">{e(y_fmt(y))}</text>')
        y += step
    for x in xs[:: max(1, len(xs) // 6)] + ([xs[-1]] if (len(xs) - 1) % max(1, len(xs) // 6) else []):
        g.append(f'<text x="{X(x):.1f}" y="{H - B + 18}" class="tick" text-anchor="middle">{e(x_fmt(x))}</text>')
    g.append(f'<text x="{(L + W - R) / 2}" y="{H - 2}" class="tick" text-anchor="middle">{e(x_label)}</text>')
    labels = []
    for s in series:
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, s["ys"]))
        g.append(f'<polyline points="{pts}" fill="none" style="stroke:{s["color"]}" stroke-width="2" '
                 f'stroke-linejoin="round" stroke-linecap="round" {"stroke-dasharray=\"6 5\"" if s.get("dash") else ""}/>')
        for x, y in zip(xs, s["ys"]):
            g.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="9" class="hit" data-tip="{e(s["name"])} - {e(x_fmt(x))}: {e(y_fmt(y))}"/>')
        labels.append([Y(s["ys"][-1]), s])
    labels.sort(key=lambda t: t[0])
    for i in range(1, len(labels)):  # keep end labels from colliding
        labels[i][0] = max(labels[i][0], labels[i - 1][0] + 14)
    for yy, s in labels:
        g.append(f'<circle cx="{X(xs[-1]):.1f}" cy="{Y(s["ys"][-1]):.1f}" r="4" style="fill:{s["color"]}" class="ring"/>'
                 f'<text x="{X(xs[-1]) + 8:.1f}" y="{yy + 4:.1f}" class="dl">{e(s.get("label", s["name"]))}</text>')
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img">{"".join(g)}</svg>'


def nice_step(raw: float) -> float:
    if raw <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag)


def heatmap(rows: list[str], cols: list[str], val, text, tip) -> str:
    out = ['<div class="heat" style="grid-template-columns:minmax(110px,1.2fr) repeat(' + str(len(cols)) + ',1fr)"><div></div>']
    out += [f'<div class="hh">{e(c)}</div>' for c in cols]
    for r in rows:
        out.append(f'<div class="hr">{e(r)}</div>')
        for c in cols:
            v = val(r, c)  # 0..1
            step = ["100", "200", "300", "400", "500", "600", "700"][min(6, int(v * 6.999))]
            ink = "var(--ink)" if int(step) < 400 else "#fff"
            out.append(f'<div class="hc" style="background:var(--b{step});color:{ink}" data-tip="{e(tip(r, c))}">{e(text(r, c))}</div>')
    out.append("</div>")
    return "".join(out)


def table(headers: list[str], rows: list[list[str]]) -> str:
    return ('<details><summary>Table view</summary><div class="scroll"><table><tr>' + "".join(f"<th>{e(h)}</th>" for h in headers)
            + "</tr>" + "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in rows) + "</table></div></details>")


def card(title: str, sub: str, body: str, wide: bool = False) -> str:
    return f'<section class="card{" wide" if wide else ""}"><h3>{e(title)}</h3><p class="sub">{sub}</p>{body}</section>'


# ---------- page ----------

def build() -> str:
    roi = json.loads((OUT / "roi.json").read_text())
    a = json.loads((OUT / "assumptions.json").read_text())
    replay = {r["config"]: r for r in json.loads((OUT / "results.json").read_text())["runs"]}
    C = roi["configs"]
    best = roi["recommended"]
    rate = a["loaded_cost_per_hour_usd"]["value"]
    vol0 = a["volume_packages_per_month"]["value"]
    growth = a["volume_packages_per_month"].get("growth_per_month", 0)
    hosting = a["run_cost"]["hosting_usd_per_month"]
    base_min = a["baseline_minutes_per_package"]["value"]
    m = {c: C[c]["measured"] for c in CONFIGS}
    api = {c: C[c]["run_cost_per_package_usd"] for c in CONFIGS}
    b1, bnow = C[best]["scenarios"][P1], C[best]["scenarios"][NOW]

    # KPI tiles
    labor_pkg = base_min / 60 * rate
    roi_multiple = b1["gross_usd"] / b1["run_usd"]
    tiles = [
        (f"{base_min / 60:.0f} h → {b1['minutes'] / 60:.1f} h", "person-time per package once Phase 1 is complete (projected)"),
        (f"{bnow['saved_pct']:.0%}", f"saved per package today with wire extraction live (measured review load)"),
        (f"{b1['hours_per_year']:,.0f} h", f"returned per year = {b1['fte']:.1f} FTE at {vol0} packages/month"),
        (money(b1["net_usd"]), "net value per year after API and hosting cost"),
        (f"{roi_multiple:,.0f}×", "labor value saved per $1 of API + hosting spend"),
        (f"${api[best]:.4f}", f"API cost per package ({SHORT[best]}) vs {money(labor_pkg)} of labor today"),
        (f"{money(api[best] * vol0 * 12, 2)}", f"API spend per year at {vol0} packages/month (+{money(hosting * 12)} hosting)"),
        (f"{m[best]['machine_seconds_per_package']:.1f} s", f"machine time per package ({m[best]['packages']} in {m[best]['wall_seconds']:.0f} s)"),
    ]
    tiles_html = '<div class="tiles">' + "".join(f'<div class="tile"><b>{e(v)}</b><span>{e(t)}</span></div>' for v, t in tiles) + "</div>"
    cfg_legend = legend([(SHORT[c] + (" (recommended)" if c == best else ""), f"var(--s{SLOT[c]})") for c in CONFIGS])

    cards = []

    # 1. API cost per package
    parts = {c: cost_parts(c, a, m[c]["pages_per_doc"]) for c in CONFIGS}
    cards.append(card("API cost per package", "Azure list prices (Global Standard, East US 2) × measured tokens and pages. Two reads per document for the single-model configs.",
        hbars([(SHORT[c], api[c], SLOT[c], f"${api[c]:.4f}", f"{SHORT[c]}: " + "; ".join(f"{k} ${v:.5f}" for k, v in parts[c].items() if v)
                + f" — {a['run_cost'][c]['calls']}") for c in CONFIGS])
        + table(["Config", "Calls per package", *next(iter(parts.values())).keys(), "Total"],
                [[SHORT[c], a["run_cost"][c]["calls"], *(f"${v:.5f}" for v in parts[c].values()), f"${api[c]:.5f}"] for c in CONFIGS])))

    # 2. API spend per month vs volume
    vols = [100, 200, 300, 400, 500]
    cards.append(card("API spend per month as volume grows", "API calls only (hosting is a flat " + money(hosting) + "/month). Even at 5× today's volume the model bill stays in single dollars.",
        line_chart([{"name": SHORT[c], "ys": [api[c] * v for v in vols], "color": f"var(--s{SLOT[c]})"} for c in CONFIGS],
                   vols, "packages per month", lambda y: f"${y:,.2f}")
        + cfg_legend + table(["Packages / month", *(SHORT[c] for c in CONFIGS)], [[v, *(f"${api[c] * v:,.2f}" for c in CONFIGS)] for v in vols])))

    # 3. Accuracy (two panels)
    acc = {c: m[c]["fields_correct"] / m[c]["fields"] for c in CONFIGS}
    macc = {c: m[c]["money_fields_correct"] / m[c]["money_fields"] for c in CONFIGS}
    cards.append(card("Extraction accuracy", "Share of values exactly right in the returned workbook, 100 packages per config.",
        '<h4>ABA routing + account number (the fields that move money)</h4>'
        + hbars([(SHORT[c], macc[c] * 100, SLOT[c], f"{macc[c]:.0%}", f"{SHORT[c]}: {m[c]['money_fields_correct']}/{m[c]['money_fields']} ABA+account values right") for c in CONFIGS], 100)
        + '<h4>All six fields</h4>'
        + hbars([(SHORT[c], acc[c] * 100, SLOT[c], f"{acc[c]:.0%}", f"{SHORT[c]}: {m[c]['fields_correct']}/{m[c]['fields']} values right") for c in CONFIGS], 100)))

    # 4. Safety
    cards.append(card("Wrong values that reach the reviewer unflagged", "Per 100 packages. These look correct in the workbook. An unflagged wrong account or ABA is a misdirected wire unless the reviewer catches it.",
        '<h4>Unflagged wrong ABA / account numbers</h4>'
        + hbars([(SHORT[c], m[c]["silent_money"], SLOT[c], str(m[c]["silent_money"]), f"{SHORT[c]}: {m[c]['silent_money']} wrong ABA/account values not highlighted") for c in CONFIGS], max(1, max(m[c]["silent_money"] for c in CONFIGS)))
        + '<h4>Packages with any unflagged wrong value</h4>'
        + hbars([(SHORT[c], m[c]["packages_with_silent_error"], SLOT[c], f"{m[c]['packages_with_silent_error']} / {m[c]['packages']}",
                  f"{SHORT[c]}: {m[c]['packages_with_silent_error']} packages; all fields unflagged-wrong: {m[c]['wrong_silent']}") for c in CONFIGS], 100)
        + '<p class="note">Mistral Document AI\'s 50 are all one ambiguity: it returns the company name where the expected value is the full account name ("… Client Trust Account").</p>'))

    # 5. Reviewer workload
    cards.append(card("Reviewer workload", "What the Accounting reviewer has to touch per package after automation.",
        '<h4>Fields highlighted for review per package</h4>'
        + hbars([(SHORT[c], m[c]["flagged_per_row"], SLOT[c], f"{m[c]['flagged_per_row']:.2f}", f"{SHORT[c]}: {m[c]['flagged_per_row']:.2f} of 6 fields highlighted per package") for c in CONFIGS], 6)
        + '<h4>Wrong values caught by a flag (per 100 packages)</h4>'
        + hbars([(SHORT[c], m[c]["wrong_caught"], SLOT[c], str(m[c]["wrong_caught"]), f"{SHORT[c]}: {m[c]['wrong_caught']} wrong values highlighted; {m[c]['false_alarms']} correct values also highlighted") for c in CONFIGS])
        + '<h4>Minutes of wire-extraction review per package (vs 40 by hand)</h4>'
        + hbars([(SHORT[c], C[c]["scenarios"][NOW]["tasks"]["wire_extraction"], SLOT[c], f"{C[c]['scenarios'][NOW]['tasks']['wire_extraction']:.1f} min",
                  f"{SHORT[c]}: {a['review']['verify_row_minutes']} min verify + {a['review']['fix_flagged_field_minutes']} min × {m[c]['flagged_per_row']:.2f} flagged fields") for c in CONFIGS], 40)))

    # 6. Speed
    cards.append(card("Speed", "Recorded live latencies, replayed through the production app.",
        '<h4>Model time per document (median, both reads)</h4>'
        + hbars([(SHORT[c], recorded_seconds(c), SLOT[c], f"{recorded_seconds(c):.1f} s", f"{SHORT[c]}: median {recorded_seconds(c):.1f} s of model time per document") for c in CONFIGS])
        + '<h4 style="margin-bottom:20px">100-package batch vs the 200 s request limit</h4>'
        + hbars([(SHORT[c], m[c]["wall_seconds"], SLOT[c], f"{m[c]['wall_seconds']:.0f} s", f"{SHORT[c]}: {m[c]['wall_seconds']:.0f} s for 100 packages at 8-way concurrency") for c in CONFIGS], 220, (200, "200 s limit"))
        + f'<p class="note">By hand the same 100 packages are {base_min * 100 / 60:,.0f} person-hours.</p>'))

    # 7. Accuracy by layout heatmap
    def layout_acc(doc, c):
        rows = [r for r in replay[c]["rows"] if r["doc"] == doc and not r["error"]]
        cells = [r["fields"][f]["correct"] for r in rows for f in MONEY]
        return sum(cells) / len(cells), len(rows)
    by_short = {SHORT[c]: c for c in CONFIGS}
    cards.append(card("ABA + account accuracy by document layout", "Six synthetic layouts built to stress digit reading. Darker = more right.",
        heatmap(list(DOCS), list(by_short),
                lambda d, s: layout_acc(d, by_short[s])[0],
                lambda d, s: f"{layout_acc(d, by_short[s])[0]:.0%}",
                lambda d, s: f"{d} / {s}: {layout_acc(d, by_short[s])[0]:.0%} of ABA+account values right ({layout_acc(d, by_short[s])[1]} packages)")))

    # 8. Calibration
    cal = {c: calibration(c) for c in CONFIGS}
    cards.append(card("Can model confidence be trusted?", "Mean self-reported confidence on values that were right vs wrong (raw live reads). Wrong values score as high or higher, so confidence alone cannot route reviews.",
        '<h4>Confidence when right</h4>'
        + hbars([(SHORT[c], cal[c][0] * 100, SLOT[c], f"{cal[c][0]:.2f}", f"{SHORT[c]}: mean confidence {cal[c][0]:.2f} on correct values") for c in CONFIGS], 100)
        + '<h4>Confidence when wrong</h4>'
        + hbars([(SHORT[c], cal[c][1] * 100, SLOT[c], f"{cal[c][1]:.2f}", f"{SHORT[c]}: mean confidence {cal[c][1]:.2f} on wrong values") for c in CONFIGS], 100)))

    # 9. Minutes per package by task
    task_keys = ["intake", "wire_extraction", "cross_doc", "exceptions", "outputs"]
    task_colors = ["var(--t1)", "var(--t2)", "var(--t3)", "var(--t4)", "var(--t5)"]
    task_names = [a["tasks"][k]["label"].split(":")[0] for k in task_keys]
    sc = C[best]["scenarios"]
    cards.append(card("Where the 4 hours go", f"Minutes per package ({SHORT[best]}). Wire extraction after automation is measured review load; other tasks' residuals are assumptions.",
        stacked([(s, [(task_names[i], sc[s]["tasks"][k]) for i, k in enumerate(task_keys)], f"{sc[s]['minutes']:.0f} min") for s in sc], task_colors, base_min)
        + legend(list(zip(task_names, task_colors)))
        + table(["Task", *sc.keys()], [[task_names[i], *(f"{sc[s]['tasks'][k]:.1f}" for s in sc)] for i, k in enumerate(task_keys)]), wide=True))

    # 10. Cumulative net value over 24 months
    months = list(range(1, 25))
    def cumulative(s):
        tot, ys = 0.0, []
        for mo in months:
            v = vol0 * (1 + growth) ** (mo - 1)
            tot += C[best]["scenarios"][s]["saved_minutes"] / 60 * v * rate - (api[best] * v + hosting)
            ys.append(tot)
        return ys
    cum1, cumnow = cumulative(P1), cumulative(NOW)
    cards.append(card("Cumulative net value, 24 months", f"{SHORT[best]}; volume starts at {vol0}/month and grows {growth:.0%}/month; net of API and hosting. Build cost not included.",
        line_chart([{"name": "Phase 1 complete (projected)", "label": money(cum1[-1]), "ys": cum1, "color": f"var(--s{SLOT[best]})"},
                    {"name": "Current build (wire extraction)", "label": money(cumnow[-1]), "ys": cumnow, "color": f"var(--s{SLOT[best]})", "dash": True}],
                   months, "month", lambda y: money(y), lambda x: f"M{x}", height=300, width=900)
        + legend([("Phase 1 complete (projected)", f"var(--s{SLOT[best]})"), ("Current build (wire extraction live)", f"var(--s{SLOT[best]})")], {"Current build (wire extraction live)"})
        + table(["Month", "Packages", "Current build, cumulative", "Phase 1, cumulative"],
                [[mo, f"{vol0 * (1 + growth) ** (mo - 1):.0f}", money(cumnow[i]), money(cum1[i])] for i, mo in enumerate(months) if mo in (1, 3, 6, 12, 18, 24)]), wide=True))

    # 11. Sensitivity heatmap
    grid = roi["sensitivity"]
    scales = {"Half the residual work": 0.5, "As assumed": 1.0, "1.5× residual work": 1.5}
    cell = lambda r, c: grid[f"{r.split()[0]}|{scales[c]}"]
    top = max(cell(r, c)["net_usd"] for r in ("50", "100", "200") for c in scales)
    cards.append(card("Sensitivity: net $ per year, Phase 1 complete", "Rows: packages per month. Columns: how much human work remains in each automated task, relative to the assumption.",
        heatmap(["50 / month", "100 / month", "200 / month"], list(scales),
                lambda r, c: cell(r, c)["net_usd"] / top,
                lambda r, c: money(cell(r, c)["net_usd"]),
                lambda r, c: f"{r}, {c}: {cell(r, c)['hours_per_year']:,.0f} h/yr saved"), wide=True))

    # Full metrics table
    hdr = ["Metric", *(SHORT[c] for c in CONFIGS)]
    rows = [
        ["Savings credited", *("yes" if c == best else "no – unflagged wrong values" for c in CONFIGS)],
        ["API cost / package", *(f"${api[c]:.4f}" for c in CONFIGS)],
        ["API cost / 1,000 packages", *(f"${api[c] * 1000:,.2f}" for c in CONFIGS)],
        ["API + hosting / year", *(money(C[c]["scenarios"][P1]["run_usd"]) for c in CONFIGS)],
        ["All fields right", *(f"{acc[c]:.1%}" for c in CONFIGS)],
        ["ABA + account right", *(f"{macc[c]:.1%}" for c in CONFIGS)],
        ["Wrong values flagged", *(f"{m[c]['wrong_caught']}" for c in CONFIGS)],
        ["Wrong values NOT flagged", *(f"{m[c]['wrong_silent']} ({m[c]['silent_money']} ABA/account)" for c in CONFIGS)],
        ["Packages with an unflagged error", *(f"{m[c]['packages_with_silent_error']}%" for c in CONFIGS)],
        ["Correct values flagged (false alarms)", *(f"{m[c]['false_alarms']}" for c in CONFIGS)],
        ["Packages marked for review", *(f"{m[c]['rows_marked_review']}%" for c in CONFIGS)],
        ["Flagged fields / package", *(f"{m[c]['flagged_per_row']:.2f}" for c in CONFIGS)],
        ["Mean confidence right / wrong", *(f"{cal[c][0]:.2f} / {cal[c][1]:.2f}" for c in CONFIGS)],
        ["Model time / document", *(f"{recorded_seconds(c):.1f} s" for c in CONFIGS)],
        ["100-package batch", *(f"{m[c]['wall_seconds']:.0f} s" for c in CONFIGS)],
        ["Minutes / package now", *(f"{C[c]['scenarios'][NOW]['minutes']:.0f}" for c in CONFIGS)],
        ["Minutes / package, Phase 1", *(f"{C[c]['scenarios'][P1]['minutes']:.0f}" for c in CONFIGS)],
        ["Hours saved / year, Phase 1", *(f"{C[c]['scenarios'][P1]['hours_per_year']:,.0f}" for c in CONFIGS)],
        ["Net $ / year, Phase 1", *(money(C[c]["scenarios"][P1]["net_usd"]) for c in CONFIGS)],
        ["Labor $ saved per $1 run cost", *(f"{C[c]['scenarios'][P1]['gross_usd'] / C[c]['scenarios'][P1]['run_usd']:,.0f}×" for c in CONFIGS)],
        ["Run cost per hour saved", *(f"${C[c]['scenarios'][P1]['run_usd'] / C[c]['scenarios'][P1]['hours_per_year']:.2f}" for c in CONFIGS)],
    ]
    metrics = ('<section class="card wide"><h3>All metrics</h3><p class="sub">100 packages per config. Hours and dollars use the assumptions below.</p>'
               '<div class="scroll"><table><tr>' + "".join(f"<th>{e(h)}</th>" for h in hdr) + "</tr>"
               + "".join("<tr>" + "".join(f"<td>{e(str(x))}</td>" for x in r) + "</tr>" for r in rows) + "</table></div></section>")

    assumptions = f"""<section class="card wide"><h3>Sources and assumptions</h3><ul class="note">
<li><b>Baseline:</b> ~4 h per funding package for one person (client). Labor value {money(labor_pkg)} per package at ${rate}/h loaded (assumed).</li>
<li><b>Volume:</b> {e(a['volume_packages_per_month']['source'])}</li>
<li><b>Prices:</b> {e(a['run_cost']['_source'])} Hosting {money(hosting)}/month is assumed.</li>
<li><b>Measured:</b> accuracy, flags, review load and batch time come from replaying recorded live reads through the production <code>/extract</code> code (no new model calls).</li>
<li><b>Assumed:</b> the split of the 4 h across tasks, residual human work once each task is automated, reviewer minutes (verify {a['review']['verify_row_minutes']} min/row, fix {a['review']['fix_flagged_field_minutes']} min/flag). Intake, cross-document validation, exceptions and output files are not built yet.</li>
<li><b>Not costed:</b> build and run-team cost, and the cost of a misdirected wire. Human review, approval, bank import and release stay mandatory.</li>
<li><b>Test set:</b> 6 synthetic layouts built to stress digit reading; re-run on the held-out real wire set before sign-off.</li></ul></section>"""

    return PAGE.format(tiles=tiles_html, legend=cfg_legend, cards="".join(cards), metrics=metrics, assumptions=assumptions,
                       generated=e(roi["generated"]), best=e(SHORT[best]))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Initial Funding ROI Dashboard</title>
<style>
:root {{ color-scheme: light; --bg:#f9f9f7; --card:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --line:rgba(11,11,11,0.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --t1:#2a78d6; --t2:#eb6834; --t3:#1baf7a; --t4:#eda100; --t5:#e87ba4;
  --b100:#cde2fb; --b200:#9ec5f4; --b300:#6da7ec; --b400:#3987e5; --b500:#256abf; --b600:#184f95; --b700:#0d366b; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --bg:#0d0d0d; --card:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --grid:#2c2c2a; --axis:#383835; --line:rgba(255,255,255,0.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --t1:#3987e5; --t2:#d95926; --t3:#199e70; --t4:#c98500; --t5:#d55181; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --bg:#0d0d0d; --card:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --grid:#2c2c2a; --axis:#383835; --line:rgba(255,255,255,0.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --t1:#3987e5; --t2:#d95926; --t3:#199e70; --t4:#c98500; --t5:#d55181; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:1120px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:26px; margin:0 0 4px; }} h3 {{ font-size:16px; margin:0 0 2px; }} h4 {{ font-size:13px; font-weight:600; color:var(--ink2); margin:14px 0 6px; }}
.lede {{ color:var(--ink2); margin:0 0 20px; max-width:800px; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:12px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
.tile b {{ display:block; font-size:26px; line-height:1.2; }} .tile span {{ color:var(--ink2); font-size:13px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,500px),1fr)); gap:12px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; min-width:0; }}
.card.wide {{ grid-column:1/-1; }}
.sub {{ color:var(--ink2); font-size:13px; margin:0 0 8px; }}
.hbars {{ display:flex; flex-direction:column; gap:6px; }}
.hrow {{ display:grid; grid-template-columns:minmax(90px,170px) 1fr 74px; align-items:center; gap:8px; font-size:13px; }}
.hl {{ color:var(--ink2); overflow-wrap:anywhere; }} .hv {{ font-variant-numeric:tabular-nums; text-align:right; }}
.htrack {{ position:relative; height:18px; }}
.hbar {{ height:100%; border-radius:0 4px 4px 0; }}
.stack {{ display:flex; gap:2px; height:22px; }} .seg {{ height:100%; border-radius:4px; }}
.href {{ position:absolute; top:-3px; bottom:-3px; border-left:2px dashed var(--muted); }}
.href span {{ position:absolute; top:-18px; left:4px; font-size:11px; color:var(--muted); white-space:nowrap; }}
.hrow:hover .hbar, .seg:hover {{ filter:brightness(1.1); }}
.legend {{ display:flex; flex-wrap:wrap; gap:4px 14px; font-size:12px; color:var(--ink2); margin-top:8px; }}
.legend i {{ display:inline-block; width:12px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; }}
.legend i.dash {{ height:3px; vertical-align:3px; background:repeating-linear-gradient(90deg,currentColor 0 4px,transparent 4px 7px) !important; color:var(--s3); }}
svg.chart {{ width:100%; height:auto; display:block; }}
.grid line, line.grid {{ stroke:var(--grid); stroke-width:1; }} line.axis {{ stroke:var(--axis); stroke-width:1; }}
.tick {{ fill:var(--muted); font-size:11px; }} .dl {{ fill:var(--ink); font-size:12px; font-weight:600; }}
.hit {{ fill:transparent; cursor:default; }} .ring {{ stroke:var(--card); stroke-width:2; }}
.heat {{ display:grid; gap:2px; font-size:13px; }}
.hh {{ color:var(--ink2); font-size:12px; text-align:center; padding:2px; }} .hr {{ color:var(--ink2); padding:6px 4px; }}
.hc {{ text-align:center; padding:8px 4px; border-radius:4px; font-variant-numeric:tabular-nums; }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }} th {{ color:var(--ink2); font-weight:600; }}
details {{ margin-top:10px; font-size:13px; }} summary {{ color:var(--ink2); cursor:pointer; }}
.note {{ color:var(--ink2); font-size:13px; }} ul.note {{ padding-left:18px; margin:6px 0 0; }}
#tip {{ position:fixed; pointer-events:none; background:var(--ink); color:var(--bg); font-size:12px; padding:6px 8px; border-radius:6px; max-width:300px; opacity:0; transition:opacity .08s; z-index:10; }}
@media (max-width:560px) {{ .hrow {{ grid-template-columns:96px 1fr 60px; }} }}
</style></head><body><main>
<h1>Initial Funding Phase 1: ROI dashboard</h1>
<p class="lede">gpt-6-luna vs Mistral on 100 funding packages each, replayed through the production extraction code ({generated}). Recommended: <b>{best}</b>, the only setup that left no wrong value unflagged.</p>
{tiles}
{legend}
<div class="grid" style="margin-top:12px">{cards}{metrics}{assumptions}</div>
</main><div id="tip" role="tooltip"></div>
<script>
const tip = document.getElementById('tip');
document.addEventListener('pointermove', ev => {{
  const t = ev.target.closest('[data-tip]');
  if (!t) {{ tip.style.opacity = 0; return; }}
  tip.textContent = t.dataset.tip; tip.style.opacity = 1;
  const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8), y = ev.clientY + 16;
  tip.style.left = x + 'px'; tip.style.top = (y + tip.offsetHeight > innerHeight ? ev.clientY - tip.offsetHeight - 10 : y) + 'px';
}});
</script></body></html>
"""


if __name__ == "__main__":
    (OUT / "dashboard.html").write_text(build())
    print("wrote", OUT / "dashboard.html")
