"""Live Phase 1 eval of the combined unit: Mistral OCR reads each page, gpt-6-luna extracts the fields from that text.

Usage (from the repo root, with real credentials in .env or the environment):
  AZURE_AI_FOUNDRY_BASE_URL=...  AZURE_AI_FOUNDRY_API_KEY=...       # gpt-6-luna deployment
  MISTRAL_OCR_URL=https://<resource>.services.ai.azure.com/providers/mistral/azure/ocr
  MISTRAL_OCR_API_KEY=...                                             # optional, defaults to the Azure key
  python -m evals.roi.live [packages] [--concurrency N] [--seed N]

Builds `packages` distinct synthetic wire instructions (fresh names, addresses, banks, ABA and account numbers
per package, the six harness layouts cycled, every one rasterised like a scan) and posts each one on its own to
the real `/extract` endpoint with OCR_PROVIDER=mistral, the way intake would send packages as they arrive. Nothing
is replayed: every OCR and model call is live. Scores each returned workbook against ground truth and writes
evals/roi/live/results.json, and adds the run to evals/roi/results.json for python -m evals.roi.roi.
"""
import json, random, statistics as st, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_extraction_service
from app.service import MistralOcr, WireExtractionService, is_valid_aba
from evals.harness import DOCS, FIELDS, make_doc
from evals.roi.replay import score_workbook, scan_like

OUT = Path(__file__).parent
CONFIG = "mistral-ocr+gpt-6-luna-live"

COMPANIES = ["Brightwater", "Hollowell & Gibbs", "Sorrento", "Kittredge Lane", "Pellham Ridge", "Alder Creek",
             "Northgate", "Bayview", "Copper Hill", "Red Maple", "Ashford & Quinn", "Lakeshore", "Stonebridge",
             "Willow Bend", "Harrow & Pike", "Juniper Point", "Oakmont", "Silverline", "Tidewater", "Granite Peak"]
KINDS = ["Escrow Services", "Title Agency LLC", "Settlement Services", "Closing Services", "Title & Escrow, Inc.",
         "Law Group, PLLC", "Abstract Company"]
SUFFIXES = ["", " Client Trust Account", " Settlement Account"]  # harness.body() derives the letterhead from these
STREETS = ["Lakeview Drive", "Mill Street", "Granite Ridge Road", "Harbor Point", "Elm Court", "Commerce Plaza",
           "Asylum Avenue", "Front Street", "Pratt Street", "Boulder Avenue", "Ramsey Street", "Main Street"]
CITIES = [("Columbus", "OH", "43215"), ("Hartford", "CT", "06103"), ("Boise", "ID", "83706"), ("Baltimore", "MD", "21231"),
          ("Tulsa", "OK", "74103"), ("Fayetteville", "NC", "28311"), ("Moultrie", "GA", "31768"), ("Lancaster", "PA", "17602"),
          ("Roseville", "CA", "95661"), ("Hagerstown", "MD", "21740"), ("Akron", "OH", "44333"), ("Tampa", "FL", "33618")]
BANKS = ["Meridian Trust Bank", "Connell Harbor Savings Bank", "Alpine Mutual Federal Credit Union", "Chesapeake Fiduciary Bank",
         "Red Prairie National Bank", "Fulton Ridge Bank", "Middletown Valley Bank", "Burke & Herbert Bank", "First Commerce Bank",
         "Peapack Trust", "Bank of Tampa", "Ameris Bank"]


def aba(rng: random.Random) -> str:
    """Nine digits with a valid check digit; runs of repeated digits are common, as in real routing numbers."""
    digits = [rng.choice("0123456789") for _ in range(8)]
    for _ in range(rng.randint(0, 2)):
        i = rng.randrange(7); digits[i + 1] = digits[i]
    weights = (3, 7, 1, 3, 7, 1, 3, 7)
    check = (10 - sum(w * int(d) for w, d in zip(weights, digits)) % 10) % 10
    value = "".join(digits) + str(check)
    assert is_valid_aba(value)
    return value


def account(rng: random.Random) -> str:
    raw = "".join(rng.choice("0123456789") for _ in range(rng.randint(7, 14)))
    if rng.random() < 0.4:
        raw = "000" + raw[3:]  # leading zeros
    if rng.random() < 0.4:
        i = rng.randrange(len(raw) - 3); raw = raw[:i] + raw[i] * 3 + raw[i + 3:]  # repeated digits
    style = rng.choice(["plain", "plain", "dashed"])
    if style == "dashed":
        cut = sorted(rng.sample(range(2, len(raw) - 1), 2))
        return f"{raw[:cut[0]]}-{raw[cut[0]:cut[1]]}-{raw[cut[1]:]}"
    return raw


def address(rng: random.Random) -> str:
    city, state, zip_code = rng.choice(CITIES)
    unit = rng.choice(["", f", Suite {rng.randint(1, 30) * 100}", f", Unit {rng.choice('ABCD')}", f", Floor {rng.randint(2, 20)}"])
    return f"{rng.randint(1, 9999)} {rng.choice(STREETS)}{unit}, {city}, {state} {zip_code}"


def package(rng: random.Random) -> dict:
    return dict(beneficiary_name=f"{rng.choice(COMPANIES)} {rng.choice(KINDS)}{rng.choice(SUFFIXES)}",
                beneficiary_address=address(rng), bank_name=rng.choice(BANKS), bank_address=address(rng),
                routing_number_aba=aba(rng), account_number=account(rng))


class Recorder:
    """Counts tokens and time of every gpt-6-luna call and every OCR call."""

    def __init__(self, responses, ocr):
        self.responses, self.ocr, self.lock = responses, ocr, threading.Lock()
        self.reads, self.ocr_calls = [], []

    def create(self, **kwargs):
        started = time.monotonic(); r = self.responses.create(**kwargs)
        u = getattr(r, "usage", None)
        with self.lock:
            self.reads.append({"seconds": time.monotonic() - started, "input_tokens": getattr(u, "input_tokens", 0),
                               "output_tokens": getattr(u, "output_tokens", 0)})
        return r

    def pages(self, content, mime_type, timeout=None):
        started = time.monotonic(); pages = self.ocr.pages(content, mime_type, timeout)
        with self.lock:
            self.ocr_calls.append({"seconds": time.monotonic() - started, "pages": len(pages)})
        return pages


def main() -> None:
    argv = sys.argv[1:]
    opts = {"--concurrency": 4, "--seed": 11}
    for flag in list(opts):
        if flag in argv:
            i = argv.index(flag); opts[flag] = int(argv[i + 1]); del argv[i:i + 2]
    count = int(argv[0]) if argv else 100
    rng = random.Random(opts["--seed"])
    layouts = list(DOCS)
    packages = [(f"IF-{i + 1:04d}_{layouts[i % len(layouts)]}.pdf", layouts[i % len(layouts)], package(rng)) for i in range(count)]

    settings = Settings(ocr_provider="mistral")
    real = WireExtractionService(settings)
    recorder = Recorder(real._client.responses, real._ocr)
    service = WireExtractionService(settings, client=type("C", (), {"responses": recorder})(), ocr=recorder)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_extraction_service] = lambda: service
    prices = json.loads((OUT / "assumptions.json").read_text())["run_cost"]["mistral-ocr+gpt-6-luna"]

    def run(item):
        name, layout, truth = item
        pdf = scan_like(make_doc(layout, truth))
        started = time.monotonic()
        response = client.post("/extract", files={"file": (name, pdf, "application/pdf")})
        seconds = time.monotonic() - started
        if response.status_code != 200:
            return {"source": name, "doc": layout, "seconds": seconds, "review": True, "error": f"HTTP {response.status_code}: {response.text[:200]}",
                    "fields": {f: {"value": None, "correct": False, "flagged": True} for f in FIELDS}, "truth": truth}
        row = score_workbook(response.content, {name: truth})[0]
        return {**row, "doc": layout, "seconds": seconds, "truth": truth}

    try:
        with TestClient(app) as client:
            started = time.monotonic()
            with ThreadPoolExecutor(opts["--concurrency"]) as pool:
                rows = list(pool.map(run, packages))
            wall = time.monotonic() - started
    finally:
        app.dependency_overrides.clear()

    reads, ocr_calls = recorder.reads, recorder.ocr_calls
    tokens_in = st.mean(r["input_tokens"] or 0 for r in reads) if reads else 0
    tokens_out = st.mean(r["output_tokens"] or 0 for r in reads) if reads else 0
    pages = sum(c["pages"] for c in ocr_calls) / max(len(ocr_calls), 1)
    reads_per_doc = len(reads) / max(len(ocr_calls), 1)
    cost = (pages * prices["usd_per_1000_pages"] / 1000
            + reads_per_doc * (tokens_in * prices["usd_per_m_input_tokens"] + tokens_out * prices["usd_per_m_output_tokens"]) / 1e6)
    run_record = {
        "config": CONFIG, "live": True, "packages": count, "seed": opts["--seed"], "concurrency": opts["--concurrency"],
        "generated": time.strftime("%Y-%m-%d"), "wall_seconds": round(wall, 1),
        "median_package_seconds": round(st.median(r["seconds"] for r in rows), 2),
        "p90_package_seconds": round(sorted(r["seconds"] for r in rows)[int(0.9 * (len(rows) - 1))], 2),
        "median_ocr_seconds": round(st.median(c["seconds"] for c in ocr_calls), 2) if ocr_calls else None,
        "median_luna_seconds": round(st.median(r["seconds"] for r in reads), 2) if reads else None,
        "luna_input_tokens_per_read": round(tokens_in), "luna_output_tokens_per_read": round(tokens_out),
        "luna_reads_per_doc": round(reads_per_doc, 2), "ocr_pages_per_doc": round(pages, 2),
        "cost_per_package_usd": cost, "rows": rows,
    }
    (OUT / "live").mkdir(exist_ok=True)
    (OUT / "live" / "results.json").write_text(json.dumps(run_record, indent=1))
    combined = json.loads((OUT / "results.json").read_text())
    combined["runs"] = [r for r in combined["runs"] if r["config"] != CONFIG] + [run_record]
    (OUT / "results.json").write_text(json.dumps(combined, indent=1))

    ok = [r for r in rows if not r["error"]]
    cells = [(f, c) for r in ok for f, c in r["fields"].items()]
    wrong = [(f, c) for f, c in cells if not c["correct"]]
    print(f"{count} packages, {len(rows) - len(ok)} errors, wall {wall:.0f} s, median {run_record['median_package_seconds']} s/package")
    print(f"fields right {len(cells) - len(wrong)}/{len(cells)}; wrong flagged {sum(c['flagged'] for _, c in wrong)}, "
          f"wrong NOT flagged {sum(not c['flagged'] for _, c in wrong)}; cost/package ${cost:.4f}")
    for f in FIELDS:
        print(f"  {f:20s} {sum(c['correct'] for g, c in cells if g == f)}/{len(ok)}")


if __name__ == "__main__":
    main()
