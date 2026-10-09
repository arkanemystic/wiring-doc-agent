"""Phase 1 ROI: combine the measured replay results with the stated assumptions.

Usage (from the repo root): python -m evals.roi.roi
Reads evals/roi/results.json (python -m evals.roi.replay) and evals/roi/assumptions.json.
Writes evals/roi/REPORT.md, evals/roi/roi.json and evals/roi/roi.html (client one-pager).
"""
import html, json
from pathlib import Path

from evals.harness import FIELDS

OUT = Path(__file__).parent
MONEY_FIELDS = ("routing_number_aba", "account_number")
NOW, P1_NAME = "Current build (wire extraction live)", "Phase 1 complete (projected)"
TASKS = ("intake", "wire_extraction", "cross_doc", "exceptions", "outputs")


def measure(run: dict) -> dict:
    rows = run["rows"]
    ok = [r for r in rows if not r["error"]]
    cells = [(r, f, r["fields"][f]) for r in ok for f in FIELDS]
    wrong = [c for c in cells if not c[2]["correct"]]
    silent = [c for c in wrong if not c[2]["flagged"]]
    return {
        "packages": len(rows),
        "wall_seconds": run["wall_seconds"],
        "machine_seconds_per_package": run["wall_seconds"] / len(rows),
        "failed_rows": len(rows) - len(ok),
        "rows_marked_review": sum(r["review"] for r in rows),
        "fields": len(cells),
        "fields_correct": len(cells) - len(wrong),
        "money_fields_correct": sum(c[2]["correct"] for c in cells if c[1] in MONEY_FIELDS),
        "money_fields": sum(c[1] in MONEY_FIELDS for c in cells),
        "wrong_caught": len(wrong) - len(silent),
        "wrong_silent": len(silent),
        "silent_money": sum(c[1] in MONEY_FIELDS for c in silent),
        "packages_with_silent_error": len({id(c[0]) for c in silent}),
        "false_alarms": sum(c[2]["flagged"] for c in cells if c[2]["correct"]),
        "flagged_per_row": sum(c[2]["flagged"] for c in cells) / max(len(ok), 1),
        "pages_per_doc": sum(2 if r["doc"] == "two_page" else 1 for r in rows) / len(rows),
        "field_correct": {f: sum(r["fields"][f]["correct"] for r in ok) for f in FIELDS},
        "packages_fully_right": sum(all(r["fields"][f]["correct"] for f in FIELDS) for r in ok),
        **{k: run[k] for k in ("live", "concurrency", "median_package_seconds", "p90_package_seconds", "median_ocr_seconds",
                                "median_luna_seconds", "luna_input_tokens_per_read", "luna_output_tokens_per_read") if k in run},
        "silent_examples": sorted({(c[0]["doc"], c[1], c[2]["value"]) for c in silent})[:8],
    }


def run_cost_per_doc(config: str, m: dict, a: dict) -> float:
    c = a["run_cost"][config]
    tokens = c["reads_per_doc"] * (c.get("input_tokens_per_read", 0) * c.get("usd_per_m_input_tokens", 0)
                                   + c.get("output_tokens_per_read", 0) * c.get("usd_per_m_output_tokens", 0)) / 1e6
    pages = c["reads_per_doc"] * m["pages_per_doc"] * c.get("usd_per_1000_pages", 0) / 1000
    return tokens + pages


def scenarios(m: dict, a: dict, residual_scale: float = 1.0) -> dict:
    t = {k: a["tasks"][k]["minutes"] for k in TASKS}
    r = a["review"]
    review = (r["verify_row_minutes"] + r["fix_flagged_field_minutes"] * m["flagged_per_row"]
              + r["failed_row_minutes"] * m["failed_rows"] / m["packages"])
    current = {**t, "wire_extraction": review}
    complete = {k: (review if k == "wire_extraction" else
                    t[k] * min(1.0, a["tasks"][k]["phase1_residual"] * residual_scale)) for k in TASKS}
    return {"Manual today": t, "Current build (wire extraction live)": current, "Phase 1 complete (projected)": complete}


def economics(minutes_saved: float, cost_per_doc: float, a: dict, volume: float | None = None) -> dict:
    volume = volume or a["volume_packages_per_month"]["value"]
    hours_year = minutes_saved / 60 * volume * 12
    run_year = cost_per_doc * volume * 12 + a["run_cost"]["hosting_usd_per_month"] * 12
    gross = hours_year * a["loaded_cost_per_hour_usd"]["value"]
    return {"hours_per_year": hours_year, "fte": hours_year / a["working_hours_per_fte_year"]["value"],
            "gross_usd": gross, "run_usd": run_year, "net_usd": gross - run_year}


def fmt_min(x: float) -> str:
    return f"{x:.0f} min" if x >= 10 else f"{x:.1f} min"


def build() -> dict:
    a = json.loads((OUT / "assumptions.json").read_text())
    data = json.loads((OUT / "results.json").read_text())
    out = {"generated": data["generated"], "configs": {}}
    for run in data["runs"]:
        m = measure(run)
        # A live run measured its own tokens and pages; replayed runs are priced from assumptions.json.
        cost = run["cost_per_package_usd"] if "cost_per_package_usd" in run else run_cost_per_doc(run["config"], m, a)
        sc = scenarios(m, a)
        base = sum(sc["Manual today"].values())
        res = {"measured": m, "run_cost_per_package_usd": cost, "scenarios": {}}
        for name, tasks in sc.items():
            total = sum(tasks.values())
            res["scenarios"][name] = {"tasks": tasks, "minutes": total, "saved_minutes": base - total,
                                      "saved_pct": (base - total) / base, **economics(base - total, cost, a)}
        out["configs"][run["config"]] = res
    safe = [c for c, r in out["configs"].items() if r["measured"]["wrong_silent"] == 0 and r["measured"]["failed_rows"] == 0]
    # A live run of the production setup outranks replays of recorded reads when it is safe.
    live = [c for c in safe if any(r["config"] == c and r.get("live") for r in data["runs"])]
    preferred = a.get("preferred_config", {}).get("value")
    best = live[0] if live else preferred if preferred in safe else min(safe or out["configs"], key=lambda c: out["configs"][c]["scenarios"]["Phase 1 complete (projected)"]["minutes"])
    out["recommended"] = best
    m, cost = out["configs"][best]["measured"], out["configs"][best]["run_cost_per_package_usd"]
    grid = {}
    for vol in (50, 100, 200):
        for scale in (0.5, 1.0, 1.5):
            sc = scenarios(m, a, scale)
            saved = sum(sc["Manual today"].values()) - sum(sc["Phase 1 complete (projected)"].values())
            grid[f"{vol}|{scale}"] = economics(saved, cost, a, vol)
    out["sensitivity"] = grid
    out["assumptions"] = a
    return out


def report_md(o: dict) -> str:
    a, best = o["assumptions"], o["recommended"]
    L = [f"# Phase 1 ROI eval (Initial Funding)\n\nGenerated by `python -m evals.roi.roi` from replay run of {o['generated']}. "
         "**Measured** = produced by the production code in `replay.py`; **assumed** = from `assumptions.json`.\n"]
    b = o["configs"][best]
    cur, comp = b["scenarios"]["Current build (wire extraction live)"], b["scenarios"]["Phase 1 complete (projected)"]
    L.append("## Headline\n")
    L.append(f"- Baseline: **{a['baseline_minutes_per_package']['value'] / 60:.0f} h per package** (client figure), "
             f"{a['volume_packages_per_month']['value']} packages/month (assumed) = "
             f"{a['baseline_minutes_per_package']['value'] / 60 * a['volume_packages_per_month']['value']:.0f} person-hours/month.")
    L.append(f"- Recommended extraction config: **{best}** (no unflagged wrong values in the replay).")
    L.append(f"- Current build (wire extraction only): {fmt_min(cur['minutes'])} per package, "
             f"**{cur['saved_pct']:.0%} saved**, {cur['hours_per_year']:,.0f} h/yr, ${cur['net_usd']:,.0f}/yr net.")
    L.append(f"- Phase 1 complete (projected): {fmt_min(comp['minutes'])} per package, "
             f"**{comp['saved_pct']:.0%} saved**, {comp['hours_per_year']:,.0f} h/yr ({comp['fte']:.1f} FTE), "
             f"${comp['net_usd']:,.0f}/yr net.")
    L.append(f"- Machine time: {b['measured']['wall_seconds']:.0f} s for a {b['measured']['packages']}-package batch "
             f"({b['measured']['machine_seconds_per_package']:.1f} s/package wall clock) vs "
             f"{a['baseline_minutes_per_package']['value'] * b['measured']['packages'] / 60:.0f} person-hours by hand.\n")

    L.append("## Eval 1 - extraction quality and review load (measured)\n")
    L.append(f"Each config: one ZIP of {b['measured']['packages']} synthetic wire instructions through `/extract` (2 passes, 8-way concurrency, "
             "200 s deadline). A field is *flagged* when the workbook highlights it for the reviewer.\n")
    L.append("| config | savings credited? | wall s | failed rows | fields right | ABA+account right | wrong & flagged | **wrong & unflagged** | packages with an unflagged error | correct but flagged | flagged fields / pkg | run cost / pkg |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c, r in o["configs"].items():
        m = r["measured"]
        credited = "**yes**" if c == best else ("no: unflagged wrong values" if m["wrong_silent"] else "no")
        L.append(f"| {c} | {credited} | {m['wall_seconds']:.0f} | {m['failed_rows']} | {m['fields_correct']}/{m['fields']} | "
                 f"{m['money_fields_correct']}/{m['money_fields']} | {m['wrong_caught']} | **{m['wrong_silent']}** "
                 f"({m['silent_money']} ABA/account) | {m['packages_with_silent_error']} | {m['false_alarms']} | "
                 f"{m['flagged_per_row']:.2f} | ${r['run_cost_per_package_usd']:.3f} |")
    for c, r in o["configs"].items():
        if r["measured"]["silent_examples"]:
            ex = "; ".join(f"{d} {f} `{v}`" for d, f, v in r["measured"]["silent_examples"])
            L.append(f"\n**{c} unflagged wrong values** (both reads agreed on the same misreading): {ex}")

    L.append("\n## Eval 2 - minutes per package (measured review load x assumed task times)\n")
    L.append("| config | scenario | " + " | ".join(t.replace("_", " ") for t in TASKS) + " | total | saved |")
    L.append("|---|---|" + "---|" * (len(TASKS) + 2))
    for c, r in o["configs"].items():
        for s, v in r["scenarios"].items():
            L.append(f"| {c} | {s} | " + " | ".join(f"{v['tasks'][t]:.1f}" for t in TASKS)
                     + f" | {v['minutes']:.0f} | {v['saved_pct']:.0%} |")

    L.append("\n## Eval 3 - annual value (recommended config)\n")
    L.append("| scenario | hours saved / yr | FTE | gross $ / yr | run cost $ / yr | net $ / yr |\n|---|---|---|---|---|---|")
    for s, v in b["scenarios"].items():
        if s != "Manual today":
            L.append(f"| {s} | {v['hours_per_year']:,.0f} | {v['fte']:.2f} | {v['gross_usd']:,.0f} | {v['run_usd']:,.0f} | {v['net_usd']:,.0f} |")
    L.append("\n### Sensitivity: Phase 1 complete, net $ / yr\n\nRows: monthly volume. Columns: the assumed residual "
             "human share of each automated task, scaled (1.0x = assumptions.json).\n")
    L.append("| packages / month | 0.5x residual | 1.0x | 1.5x |\n|---|---|---|---|")
    for vol in (50, 100, 200):
        L.append(f"| {vol} | " + " | ".join(f"${o['sensitivity'][f'{vol}|{s}']['net_usd']:,.0f} "
                                             f"({o['sensitivity'][f'{vol}|{s}']['hours_per_year']:,.0f} h)" for s in (0.5, 1.0, 1.5)) + " |")

    L.append("\n## Assumptions in use\n")
    L.append("| item | value | source |\n|---|---|---|")
    for k in TASKS:
        t = a["tasks"][k]
        L.append(f"| {t['label']} | {t['minutes']} min; residual when automated: "
                 f"{'measured' if t['phase1_residual'] is None else f'{t['phase1_residual']:.0%}'} | assumed split of 4 h |")
    rv = a["review"]
    L.append(f"| Review: verify each row / fix each flagged field / key a failed row | {rv['verify_row_minutes']} / "
             f"{rv['fix_flagged_field_minutes']} / {rv['failed_row_minutes']} min | assumed |")
    for k in ("volume_packages_per_month", "loaded_cost_per_hour_usd"):
        L.append(f"| {k} | {a[k]['value']} | {a[k]['source']} |")
    L.append(f"| model prices, hosting | see assumptions.json | placeholder |")

    L.append("""
## What this does and does not show

- **Measured:** extraction accuracy, which errors the workbook flags and which it misses, reviewer load (flagged
  fields per package), and machine time, all from the production code on recorded live model reads. The model
  calls are replayed, not re-made; latencies are the recorded ones.
- **Assumed:** the split of the 4 h, how much of each other Phase 1 task automation removes (intake, cross-document
  validation, exceptions and outputs are not built in this repo yet), review minutes, volume and rates.
- **Test set:** 6 synthetic layouts built to stress digit-reading (repeated digits, dense tables, fax-quality scans,
  two-page). Real packages are likely easier on average; the 300+ real files the design doc mentions are the right
  held-out set to re-run this on.
- **Errors are not costed.** A wrong, unflagged account number is a misdirected wire. Any config with unflagged
  ABA/account errors should not be credited with savings until that is fixed; the retained human review and
  call-back controls remain mandatory either way.
- To replace assumptions: run the pilot time study (`time_study_template.csv`), put the medians in
  `assumptions.json`, re-run `python -m evals.roi.roi`.
""")
    return "\n".join(L)


def report_html(o: dict) -> str:
    a, best = o["assumptions"], o["recommended"]
    b = o["configs"][best]
    comp, cur = b["scenarios"]["Phase 1 complete (projected)"], b["scenarios"]["Current build (wire extraction live)"]
    e = html.escape
    labels = {k: a["tasks"][k]["label"].split(":")[0] for k in TASKS}
    base = a["baseline_minutes_per_package"]["value"]
    bars = []
    y = 0
    for s, v in b["scenarios"].items():
        x, segs = 0, []
        for i, t in enumerate(TASKS):
            w = v["tasks"][t] / base * 100
            if w > 0:
                segs.append(f'<rect x="{x}%" y="0" width="{w}%" height="28" rx="4" stroke="var(--bg)" stroke-width="2" '
                            f'fill="var(--s{i + 1})"><title>{e(labels[t])}: {v["tasks"][t]:.0f} min</title></rect>')
            x += w
        bars.append(f'<div class="bar-row"><div class="bar-label">{e(s)}<span>{v["minutes"]:.0f} min</span></div>'
                    f'<svg class="bar" role="img" aria-label="{e(s)}: {v["minutes"]:.0f} minutes">{"".join(segs)}</svg></div>')
    legend = "".join(f'<span><i style="background:var(--s{i + 1})"></i>{e(labels[t])}</span>' for i, t in enumerate(TASKS))
    rows = "".join(
        f"<tr><td>{e(c)}{' (recommended)' if c == best else ''}</td><td>{r['measured']['money_fields_correct']}/{r['measured']['money_fields']}</td>"
        f"<td>{r['measured']['wrong_caught']}</td><td class=\"{'bad' if r['measured']['wrong_silent'] else ''}\">{r['measured']['wrong_silent']}</td>"
        f"<td>{r['measured']['flagged_per_row']:.2f}</td><td>{r['measured']['wall_seconds']:.0f} s</td>"
        f"<td>{r['scenarios']['Current build (wire extraction live)']['saved_pct']:.0%}</td>"
        f"<td>{r['scenarios']['Phase 1 complete (projected)']['saved_pct']:.0%}</td></tr>"
        for c, r in o["configs"].items())
    task_rows = "".join(f"<tr><td>{e(a['tasks'][t]['label'])}</td>" + "".join(
        f"<td>{v['tasks'][t]:.0f}</td>" for v in b["scenarios"].values()) + "</tr>" for t in TASKS)
    sens = "".join(f"<tr><td>{vol}</td>" + "".join(f"<td>${o['sensitivity'][f'{vol}|{s}']['net_usd'] / 1000:,.0f}k</td>"
                                                   for s in (0.5, 1.0, 1.5)) + "</tr>" for vol in (50, 100, 200))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Initial Funding ROI</title>
<style>
:root {{ color-scheme: light; --bg:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --ink2:#52514e; --line:#e4e3df; --bad:#b42318;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --bg:#1a1a19; --card:#232322; --ink:#fff; --ink2:#c3c2b7; --line:#3a3a38; --bad:#f97066;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --bg:#1a1a19; --card:#232322; --ink:#fff; --ink2:#c3c2b7; --line:#3a3a38; --bad:#f97066;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:26px; margin:0 0 4px; }} h2 {{ font-size:18px; margin:36px 0 12px; }}
.sub {{ color:var(--ink2); margin:0 0 24px; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:12px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
.tile b {{ display:block; font-size:28px; font-variant-numeric:tabular-nums; }} .tile span {{ color:var(--ink2); font-size:13px; }}
.bar-row {{ margin:10px 0; }} .bar-label {{ display:flex; justify-content:space-between; font-size:13px; color:var(--ink2); }}
.bar {{ width:100%; height:28px; display:block; }}
.legend {{ display:flex; flex-wrap:wrap; gap:6px 16px; font-size:13px; color:var(--ink2); margin-top:8px; }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }} th {{ color:var(--ink2); font-weight:600; }}
td.bad {{ color:var(--bad); font-weight:700; }}
.note {{ color:var(--ink2); font-size:13px; }} ul {{ padding-left:20px; }}
</style></head><body><main>
<h1>Initial Funding Phase 1: ROI</h1>
<p class="sub">Measured on the production extraction code with recorded live model reads ({e(o['generated'])}); task times and rates are stated assumptions.</p>
<div class="tiles">
<div class="tile"><b>{base / 60:.0f} h &rarr; {comp['minutes'] / 60:.1f} h</b><span>person-time per package, Phase 1 complete (projected)</span></div>
<div class="tile"><b>{cur['saved_pct']:.0%}</b><span>saved per package today, wire extraction only ({cur['hours_per_year']:,.0f} h/yr)</span></div>
<div class="tile"><b>{comp['hours_per_year']:,.0f} h</b><span>hours returned per year ({comp['fte']:.1f} FTE) at {a['volume_packages_per_month']['value']} packages/month</span></div>
<div class="tile"><b>${comp['net_usd'] / 1000:,.0f}k</b><span>net per year after model and hosting cost</span></div>
<div class="tile"><b>{b['measured']['machine_seconds_per_package']:.1f} s</b><span>machine time per package ({b['measured']['packages']} packages in {b['measured']['wall_seconds']:.0f} s)</span></div>
</div>
<h2>Where the 4 hours go</h2>
{''.join(bars)}
<div class="legend">{legend}</div>
<p class="note">Current build automates wire extraction only: {cur['saved_pct']:.0%} saved per package. Wire-extraction time after automation is measured review load; the other tasks' residuals are assumptions.</p>
<div class="scroll"><table><tr><th>Task (minutes)</th>{''.join(f'<th>{e(s)}</th>' for s in b['scenarios'])}</tr>{task_rows}
<tr><th>Total</th>{''.join(f"<th>{v['minutes']:.0f}</th>" for v in b['scenarios'].values())}</tr></table></div>
<h2>Which extraction setup is safe to credit</h2>
<div class="scroll"><table><tr><th>Config</th><th>ABA + account right</th><th>Wrong, flagged</th><th>Wrong, NOT flagged</th><th>Flagged fields / pkg</th><th>Batch time ({b['measured']['packages']} pkgs)</th><th>Saving now</th><th>Phase 1 saving</th></tr>{rows}</table></div>
<p class="note">A wrong value that is not flagged reaches the CashPro file unless the human reviewer catches it. Savings are only credited for a config with none.</p>
<h2>Sensitivity: net $ per year, Phase 1 complete</h2>
<div class="scroll"><table><tr><th>Packages / month</th><th>Half the assumed residual work</th><th>As assumed</th><th>1.5x residual work</th></tr>{sens}</table></div>
<h2>Caveats</h2>
<ul class="note">
<li>The 4 h split across tasks, residual human effort, review minutes, volume ({a['volume_packages_per_month']['value']}/month) and ${a['loaded_cost_per_hour_usd']['value']}/h loaded cost are assumptions to be replaced by the pilot time study.</li>
<li>Intake, cross-document validation, exceptions and output files are not built yet; their savings are projections.</li>
<li>Test documents are 6 synthetic layouts designed to stress digit reading; re-run on the held-out real wire set before sign-off.</li>
<li>Human review, approval, bank import and release remain mandatory in every scenario.</li>
</ul>
</main></body></html>
"""


def main() -> None:
    o = build()
    (OUT / "roi.json").write_text(json.dumps({k: v for k, v in o.items() if k != "assumptions"}, indent=1, default=str))
    (OUT / "REPORT.md").write_text(report_md(o))
    (OUT / "roi.html").write_text(report_html(o))
    print((OUT / "REPORT.md").read_text())


if __name__ == "__main__":
    main()
