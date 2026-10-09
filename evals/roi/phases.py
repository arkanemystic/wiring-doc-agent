"""Separate ROI for Phase 0 (wire instruction extraction) and Phase 1 (the rest of package processing).

Usage (from the repo root): python -m evals.roi.phases
Reads roi.json (python -m evals.roi.roi) and assumptions.json; writes phases.json and prints a summary.

Phase 0 is valued against today's manual process. Phase 1 is valued as what it adds on top of Phase 0, so the
two never count the same minute twice and their sum equals the combined "Phase 1 complete" scenario in roi.py.
"""
import json
from pathlib import Path

from evals.roi.roi import NOW, P1_NAME, scenarios

OUT = Path(__file__).parent
PHASE0_TASKS = ["wire_extraction"]
PHASE1_TASKS = ["intake", "cross_doc", "exceptions", "outputs"]


def economics(saved_min: float, run_per_pkg: float, hosting_month: float, a: dict, volume: float, growth: float = 0.0) -> dict:
    rate, fte_hours = a["loaded_cost_per_hour_usd"]["value"], a["working_hours_per_fte_year"]["value"]
    hours = saved_min / 60 * volume * 12
    gross = hours * rate
    run = run_per_pkg * volume * 12 + hosting_month * 12
    cumulative, total = [], 0.0
    for month in range(24):
        v = volume * (1 + growth) ** month
        total += saved_min / 60 * v * rate - (run_per_pkg * v + hosting_month)
        cumulative.append(total)
    return {"hours_per_year": hours, "fte": hours / fte_hours, "gross_usd": gross, "run_usd": run, "net_usd": gross - run,
            "cumulative_24m": cumulative, "net_24m_no_growth": (gross - run) * 2,
            # The most a build could cost and still pay for itself within each horizon.
            "breakeven_build_usd": {months: (gross - run) * months / 12 for months in (6, 12, 24)}}


def phase1_run_per_package(a: dict) -> float:
    c = a["phase1_run_cost"]
    return (c["extra_pages_per_package"] * c["usd_per_1000_pages"] / 1000
            + c["luna_reads_per_package"] * (c["input_tokens_per_read"] * c["usd_per_m_input_tokens"]
                                             + c["output_tokens_per_read"] * c["usd_per_m_output_tokens"]) / 1e6)


def build() -> dict:
    roi = json.loads((OUT / "roi.json").read_text())
    a = json.loads((OUT / "assumptions.json").read_text())
    config = roi["recommended"]
    c = roi["configs"][config]
    m = c["measured"]
    vol, growth = a["volume_packages_per_month"]["value"], a["volume_packages_per_month"]["growth_per_month"]
    sc = scenarios(m, a)
    today, after0, after1 = sc["Manual today"], sc[NOW], sc[P1_NAME]

    def phase(tasks, before, after, run_pkg, hosting, sens):
        saved = sum(before[t] - after[t] for t in tasks)
        return {"tasks": {t: {"before": before[t], "after": after[t]} for t in tasks},
                "package_minutes_before": sum(before.values()), "package_minutes_after": sum(after.values()),
                "saved_minutes": saved, "saved_pct_of_package": saved / sum(before.values()),
                "run_per_package_usd": run_pkg, "hosting_usd_per_month": hosting,
                **economics(saved, run_pkg, hosting, a, vol, growth), "sensitivity": sens}

    # scenarios() gives minutes per task for: today, wire step automated (Phase 0), everything automated (Phase 1).
    # Phase 0 depends most on the reviewer minutes per package and per flag (assumed); Phase 1 on the residual work.
    r = a["review"]
    sens0 = {}
    for v in (50, 100, 200):
        for scale in (0.5, 1.0, 1.5):
            review = (r["verify_row_minutes"] + r["fix_flagged_field_minutes"] * m["flagged_per_row"]) * scale \
                + r["failed_row_minutes"] * m["failed_rows"] / m["packages"]
            sens0[f"{v}|{scale}"] = economics(a["tasks"]["wire_extraction"]["minutes"] - review, c["run_cost_per_package_usd"],
                                              a["run_cost"]["hosting_usd_per_month"], a, v)["net_usd"]
    p1_run = phase1_run_per_package(a)
    sens1 = {}
    for v in (50, 100, 200):
        for scale in (0.5, 1.0, 1.5):
            scaled = scenarios(m, a, scale)
            saved = sum(scaled[NOW][t] - scaled[P1_NAME][t] for t in PHASE1_TASKS)
            sens1[f"{v}|{scale}"] = economics(saved, p1_run, a["phase1_run_cost"]["hosting_usd_per_month"], a, v)["net_usd"]

    out = {
        "config": config, "generated": roi["generated"], "volume": vol, "growth": growth,
        "rate": a["loaded_cost_per_hour_usd"]["value"], "measured": m,
        "phase0": phase(PHASE0_TASKS, today, after0, c["run_cost_per_package_usd"], a["run_cost"]["hosting_usd_per_month"], sens0),
        "phase1": phase(PHASE1_TASKS, after0, after1, p1_run, a["phase1_run_cost"]["hosting_usd_per_month"], sens1),
    }
    combined = c["scenarios"][P1_NAME]["saved_minutes"]
    assert abs(out["phase0"]["saved_minutes"] + out["phase1"]["saved_minutes"] - combined) < 1e-6, "phases must add up"
    return out


def main() -> None:
    out = build()
    (OUT / "phases.json").write_text(json.dumps(out, indent=1))
    for key, label in (("phase0", "Phase 0 - wire instruction extraction"), ("phase1", "Phase 1 - package processing, on top of Phase 0")):
        p = out[key]
        print(f"{label}: {p['package_minutes_before']:.0f} -> {p['package_minutes_after']:.0f} min/package "
              f"(saves {p['saved_minutes']:.0f}), {p['hours_per_year']:,.0f} h/yr, {p['fte']:.2f} FTE, "
              f"net ${p['net_usd']:,.0f}/yr, run ${p['run_usd']:,.0f}/yr, 12-month break-even build ${p['breakeven_build_usd'][12]:,.0f}")


if __name__ == "__main__":
    main()
