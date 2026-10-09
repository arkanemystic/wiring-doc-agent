"""Word report of a real-document test run: accuracy and confidence per run, per extraction setup.

Usage (from the repo root):
  python -m evals.test_report <results.json> <truth.json> [--out evals/real_docs/out/Wire_Test_Results.docx]

results.json is a list of runs ({pipeline, doc, run, seconds, fields: {name: {value, confidence, correct, flags}}}) as
written by the nidhin-tests runner; truth.json maps each document to its expected values. Output defaults to the
git-ignored evals/real_docs/out/ because the documents are real; account numbers are masked in the report.
"""
import html, json, os, statistics as st, subprocess, sys, tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from evals.roi.client_docx import blocks_of, render_svgs, svgs_of
from evals.roi.client_report import FIELD_NAMES, INK, INK2, MUTED, NAVY, RULE, SANS, TODAY

e = html.escape
FIELDS = ["beneficiary_name", "beneficiary_address", "bank_name", "bank_address", "routing_number_aba", "account_number"]
SHORT = {"beneficiary_name": "Ben. name", "beneficiary_address": "Ben. address", "bank_name": "Bank",
         "bank_address": "Bank address", "routing_number_aba": "Routing", "account_number": "Account"}
SETUPS = {"mistral+luna": "Mistral + gpt-6-luna", "mistral": "Mistral Document AI alone", "luna-vision": "gpt-6-luna alone (page images)"}
ORDER = ["mistral+luna", "mistral", "luna-vision"]
RIGHT_FILL, WRONG_FILL, FLAG_FILL = "#dfe9f6", "#f6d2cd", "#fbe3a8"
THRESHOLD = 0.80  # the service highlights any field below this confidence (MANUAL_REVIEW_CONFIDENCE_THRESHOLD)


def label(doc: str, truth: dict) -> str:
    name = truth[doc]["beneficiary_name"].split(",")[0]
    return name if len(name) <= 22 else " ".join(name.split()[:2])  # fits the chart label column


def fig_setup_accuracy(stats: dict) -> str:
    rows: list = []
    for p in ORDER:
        s = stats[p]
        rows.append((SETUPS[p], "All six fields", s["right"], s["cells"]))
        rows.append(("", "Routing and account numbers", s["money_right"], s["money"]))
    W, L, bar, gap = 620, 370, 14, 8
    x = lambda v: L + v * (W - L - 100)
    g, y = [], 0
    for i, (setup, metric, hit, total) in enumerate(rows):
        if setup:
            y += 10 if i else 0
            g.append(f'<text x="0" y="{y + 11}" font-size="11.5" font-weight="600" fill="{INK}">{e(setup)}</text>')
        g.append(f'<text x="195" y="{y + 11}" font-size="11" fill="{INK2}">{e(metric)}</text>'
                 f'<rect x="{L}" y="{y}" width="{x(1) - L}" height="{bar}" fill="#ecebe6"/>'
                 f'<rect x="{L}" y="{y}" width="{x(hit / total) - L:.1f}" height="{bar}" fill="{NAVY if hit == total else TODAY}"/>'
                 f'<text x="{x(1) + 10}" y="{y + 11}" font-size="11.5" fill="{INK}"><tspan font-weight="600">{hit / total:.0%}</tspan>'
                 f'<tspan fill="{MUTED}">  {hit} of {total}</tspan></text>')
        y += bar + gap
    return f'<svg width="{W}" height="{y + 4}" font-family="{SANS}">{"".join(g)}</svg>'


def fig_runs(runs: dict, docs: list[str], truth: dict) -> str:
    """Fields right per run (out of 6), one row per setup, one column per document run."""
    cols = [(d, r) for d in docs for r in range(3)]
    W, L, cw, ch, top = 620, 190, 46, 26, 34
    g = []
    for j, d in enumerate(docs):
        g.append(f'<text x="{L + (j * 3 + 1.5) * cw:.0f}" y="12" font-size="10.5" fill="{INK2}" text-anchor="middle">{e(label(d, truth))}</text>')
    for j, (_, r) in enumerate(cols):
        g.append(f'<text x="{L + j * cw + cw / 2:.0f}" y="28" font-size="9.5" fill="{MUTED}" text-anchor="middle">run {r + 1}</text>')
    for i, p in enumerate(ORDER):
        y = top + i * (ch + 4)
        g.append(f'<text x="0" y="{y + 17}" font-size="11" fill="{INK}">{e(SETUPS[p])}</text>')
        for j, (d, r) in enumerate(cols):
            run = runs[(p, d, r)]
            right = sum(run["fields"][f]["correct"] for f in FIELDS)
            fill = RIGHT_FILL if right == 6 else WRONG_FILL
            g.append(f'<rect x="{L + j * cw + 1}" y="{y}" width="{cw - 2}" height="{ch}" rx="3" fill="{fill}"/>'
                     f'<text x="{L + j * cw + cw / 2:.0f}" y="{y + 17}" font-size="11" font-weight="600" fill="{INK}" text-anchor="middle">{right}/6</text>')
    H = top + len(ORDER) * (ch + 4)
    return f'<svg width="{W}" height="{H}" font-family="{SANS}">{"".join(g)}</svg>'


def fig_confidence(p: str, runs: dict, docs: list[str], truth: dict) -> str:
    """Confidence per field per run; fill shows right, wrong or flagged; a dashed outline marks confidence below 0.80."""
    W, L, cw, ch, top = 620, 190, 70, 18, 22
    g = [f'<text x="{L + i * cw + cw / 2:.0f}" y="14" font-size="9.5" fill="{INK2}" text-anchor="middle">{e(SHORT[f])}</text>'
         for i, f in enumerate(FIELDS)]
    y = top
    for d in docs:
        for r in range(3):
            run = runs[(p, d, r)]
            g.append(f'<text x="0" y="{y + 14}" font-size="10.5" fill="{INK}">{e(label(d, truth)) if r == 0 else ""}</text>'
                     f'<text x="{L - 8}" y="{y + 14}" font-size="9.5" fill="{MUTED}" text-anchor="end">run {r + 1}</text>')
            for i, f in enumerate(FIELDS):
                c = run["fields"][f]
                fill = FLAG_FILL if c["flags"] else RIGHT_FILL if c["correct"] else WRONG_FILL
                mark = " ⚑" if c["flags"] else "" if c["correct"] else " ✗"
                low = c["confidence"] < THRESHOLD
                g.append(f'<rect x="{L + i * cw + 1}" y="{y}" width="{cw - 2}" height="{ch}" rx="3" fill="{fill}"'
                         + (f' stroke="{INK2}" stroke-dasharray="3 2" stroke-width="1"' if low else "") + "/>"
                         f'<text x="{L + i * cw + cw / 2:.0f}" y="{y + 14}" font-size="10.5" fill="{INK}" text-anchor="middle">{c["confidence"]:.2f}{mark}</text>')
            y += ch + 3
        y += 6
    # legend
    lx = 0
    for fill, text, dashed in ((RIGHT_FILL, "Right", False), (WRONG_FILL, "Wrong ✗", False), (FLAG_FILL, "Flagged for review ⚑", False),
                               ("#ffffff", f"Below {THRESHOLD:.2f}: highlighted in the workbook", True)):
        g.append(f'<rect x="{lx}" y="{y + 4}" width="14" height="11" rx="2" fill="{fill}"'
                 + (f' stroke="{INK2}" stroke-dasharray="3 2"' if dashed else "") + "/>"
                 f'<text x="{lx + 20}" y="{y + 14}" font-size="10" fill="{INK2}">{e(text)}</text>')
        lx += 20 + len(text) * 5.6 + 18
    return f'<svg width="{W}" height="{y + 22}" font-family="{SANS}">{"".join(g)}</svg>'


def fig_conf_right_wrong(stats: dict) -> str:
    rows = [(SETUPS["luna-vision"], "Right values", stats["luna-vision"]["conf_right"]),
            ("", "Wrong values", stats["luna-vision"]["conf_wrong"]),
            (SETUPS["mistral+luna"], "Right values", stats["mistral+luna"]["conf_right"])]
    W, L, bar, gap = 620, 330, 14, 8
    x = lambda v: L + v * (W - L - 70)
    g, y = [], 0
    for i, (setup, metric, v) in enumerate(rows):
        if setup:
            y += 10 if i else 0
            g.append(f'<text x="0" y="{y + 11}" font-size="11.5" font-weight="600" fill="{INK}">{e(setup)}</text>')
        g.append(f'<text x="200" y="{y + 11}" font-size="11" fill="{INK2}">{e(metric)}</text>'
                 f'<rect x="{L}" y="{y}" width="{x(1) - L}" height="{bar}" fill="#ecebe6"/>'
                 f'<rect x="{L}" y="{y}" width="{x(v) - L:.1f}" height="{bar}" fill="{NAVY if metric == "Right values" else "#c0504d"}"/>'
                 f'<text x="{x(1) + 10}" y="{y + 11}" font-size="11.5" font-weight="600" fill="{INK}">{v:.2f}</text>')
        y += bar + gap
    return f'<svg width="{W}" height="{y + 4}" font-family="{SANS}">{"".join(g)}</svg>'


def mask(account: str) -> str:
    digits = [c for c in account if c.isdigit()]
    return "•••" + "".join(digits[-4:])


def build(results: list[dict], truth: dict) -> str:
    runs = {(r["pipeline"], r["doc"], r["run"]): r for r in results}
    docs = list(truth)
    stats = {}
    for p in ORDER:
        rs = [r for r in results if r["pipeline"] == p]
        cells = [(f, c) for r in rs for f, c in r["fields"].items()]
        right = [c["confidence"] for _, c in cells if c["correct"]]
        wrong = [c["confidence"] for _, c in cells if not c["correct"]]
        stats[p] = {"runs": len(rs), "cells": len(cells), "right": len(right),
                    "money": sum(f in ("routing_number_aba", "account_number") for f, _ in cells),
                    "money_right": sum(c["correct"] for f, c in cells if f in ("routing_number_aba", "account_number")),
                    "flags": [(r["doc"], f, c) for r in rs for f, c in r["fields"].items() if c["flags"]],
                    "low": sum(c["confidence"] < THRESHOLD for _, c in cells),
                    "conf_right": st.mean(right) if right else 0, "conf_wrong": st.mean(wrong) if wrong else 0,
                    "seconds": st.median(r["seconds"] for r in rs)}
    ml, lv, mi = stats["mistral+luna"], stats["luna-vision"], stats["mistral"]
    flag_doc, flag_field, flag_cell = ml["flags"][0] if ml["flags"] else (None, None, None)
    n_docs = len(docs)
    scanned = "verif fwire instructions.pdf"
    expected = "".join(
        f"<tr><td>{e(label(d, truth))}</td><td>{e(truth[d]['bank_name'])}</td><td class=\"num\">{e(truth[d]['routing_number_aba'])}</td>"
        f"<td class=\"num\">{e(mask(truth[d]['account_number']))}</td></tr>" for d in docs)
    speed = "".join(f"<tr><td>{e(SETUPS[p])}</td><td class=\"num\">{stats[p]['seconds']:.1f} s</td></tr>" for p in ORDER)
    flag_text = (f"The single flag came from the {e(label(flag_doc, truth))} instructions: both models found the bank address, but "
                 f"gpt-6-luna also included the branch line printed above it ({e(flag_cell['flags'][0].split(' read ')[-1])}), so the "
                 "field was marked for a person to confirm. The value in the workbook was correct; the flag shows the cross-check "
                 "working, and costs the reviewer a few seconds." if flag_doc else "No field was flagged.")
    return f"""
<h1>Wire Instruction Extraction: Test Results</h1>
<p class="dek">Phase 1: Use Case 1 &nbsp;·&nbsp; Real wire documents &nbsp;·&nbsp; October 2026</p>

<h2 style="margin-top:0">Summary</h2>
<p>Mistral Document AI working with gpt-6-luna read every field correctly on {n_docs} real wire instruction documents, in each of {ml['runs']} runs: {ml['right']} of {ml['cells']} values, including all {ml['money']} routing and account numbers. Where the two models disagreed, the field was flagged for a person to check rather than passed through. gpt-6-luna reading the page image on its own got {lv['right']} of {lv['cells']} values right, and gave its wrong answers the same high confidence as its right ones, which is why the combined setup checks one model against the other instead of trusting a confidence score.</p>

<div class="figures">
<div><b>{ml['right']} / {ml['cells']}</b><span>fields correct, Mistral + gpt-6-luna</span></div>
<div><b>{ml['money_right']} / {ml['money']}</b><span>routing and account numbers correct</span></div>
<div><b>{len(ml['flags'])}</b><span>field flagged for human review</span></div>
<div><b>{ml['seconds']:.1f} s</b><span>median time per document</span></div>
</div>

<h2>What was tested</h2>
<p>{n_docs} wire instruction documents from real loans, checked against the expected values on the loan data tape. One is a digital PDF with clear labels, one splits the beneficiary name across two lines, and one ({e(label(scanned, truth))}) is a scanned image with no text layer. Each document was run 3 times through each of three setups: Mistral Document AI reading the page and gpt-6-luna extracting the fields from its text (the setup we recommend), Mistral Document AI alone, and gpt-6-luna reading the page image alone.</p>
<figure><div class="fighead">Values read correctly, {n_docs} documents × 3 runs</div>{fig_setup_accuracy(stats)}
<figcaption><b>Figure 1.</b> Both setups that use Mistral to read the page got every value right. gpt-6-luna on its own dropped or misread digits in routing and account numbers in {lv['money'] - lv['money_right']} of {lv['money']} cases.</figcaption></figure>
<figure><div class="fighead">Fields right in each run (out of 6)</div>{fig_runs(runs, docs, truth)}
<figcaption><b>Figure 2.</b> The combined setup was right in all six fields on every run. gpt-6-luna alone varied from run to run on the same document, which makes its output hard to rely on.</figcaption></figure>

<h2>Confidence and flags</h2>
<p>Each value comes with the model's own confidence score. Figure 3 shows those scores for the recommended setup, run by run.</p>
<figure><div class="fighead">Mistral + gpt-6-luna: confidence per field, per run</div>{fig_confidence('mistral+luna', runs, docs, truth)}
<figcaption><b>Figure 3.</b> All values right. {e(SHORT[flag_field]) if flag_field else ''}{' flagged once where the two models disagreed. ' if flag_field else ''}The beneficiary address scores 0.70 in every run because it is taken from the letterhead rather than a labelled field; the workbook highlights anything below {THRESHOLD:.2f}, so a person confirms it.</figcaption></figure>
<p>{flag_text}</p>
<p>A field reaches the reviewer highlighted when the two models disagree, when its confidence is below {THRESHOLD:.2f}, or, for routing numbers, when the ABA check digit fails. Here that meant the letterhead address on each document and the one disagreement; everything else came through ready to use.</p>
<figure><div class="fighead">gpt-6-luna alone: confidence per field, per run</div>{fig_confidence('luna-vision', runs, docs, truth)}
<figcaption><b>Figure 4.</b> For comparison. The wrong values (✗) carry the same 0.95 to 0.99 confidence as the right ones, so nothing would have marked them for review.</figcaption></figure>
<figure><div class="fighead">Average confidence on right and wrong values</div>{fig_conf_right_wrong(stats)}
<figcaption><b>Figure 5.</b> gpt-6-luna alone was as confident when wrong ({lv['conf_wrong']:.2f}) as when right ({lv['conf_right']:.2f}). Confidence by itself cannot separate the two, so the combined setup relies on agreement between models and on check digits.</figcaption></figure>

<h2>Documents and speed</h2>
<table><tr><th>Beneficiary</th><th>Bank</th><th class="num">Routing</th><th class="num">Account</th></tr>{expected}</table>
<table><tr><th>Setup</th><th class="num">Median time per document</th></tr>{speed}</table>
<p class="note">Account numbers are masked. The combined setup takes longer than either model alone because it makes two calls per document; at 20 documents a day that is still under 3 minutes of processing.</p>

<h2>What this shows and what it does not</h2>
<ul class="note">
<li><b>Shows:</b> on real documents, including a scan, the combined setup read every routing number, account number, name and address correctly, and sent disagreements and uncertain fields to a person instead of passing them on.</li>
<li><b>Sample size:</b> {n_docs} documents and {ml['runs']} runs. The next step is the larger set of past wire instructions, run the same way.</li>
<li><b>Errors caught:</b> the combined setup made no errors here, so this test could not show it catching one. In the earlier test on 100 synthetic documents, every wrong value it produced was flagged.</li>
</ul>"""


def main() -> None:
    argv = sys.argv[1:]
    out = Path("evals/real_docs/out/Wire_Test_Results.docx")
    if "--out" in argv:
        i = argv.index("--out"); out = Path(argv[i + 1]); del argv[i:i + 2]
    results, truth = json.loads(Path(argv[0]).read_text()), json.loads(Path(argv[1]).read_text())
    body = build(results, truth)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        bundled = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        browser = pw.chromium.launch(executable_path=str(bundled) if bundled.exists() else None)
        images = render_svgs(svgs_of(body), Path(tmp), "t", browser)
        spec = {"title": "Wire Instruction Extraction: Test Results", "out": str(out.resolve()), "blocks": blocks_of(body, images)}
        (Path(tmp) / "spec.json").write_text(json.dumps(spec))
        npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        subprocess.run(["node", str(Path(__file__).parent / "roi" / "client_docx.js"), str(Path(tmp) / "spec.json")],
                       check=True, env={**os.environ, "NODE_PATH": npm_root})
    print("wrote", out)


if __name__ == "__main__":
    main()
