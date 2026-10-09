"""Phase 1 throughput and review-load eval: replay recorded live model reads through the real app.

Usage (from the repo root; no Azure credentials needed):
  python -m evals.roi.replay [packages] [--seed N]

For each extraction configuration below, builds one ZIP of `packages` synthetic wire instructions
(the six harness layouts, cycled), POSTs it to the real FastAPI `/extract` endpoint with production
settings (2 passes, 8-way concurrency, 200 s deadline) and scores the returned workbook against ground
truth. The only thing replaced is the network call: the fake client returns a read that the model
actually produced in an earlier live eval (`evals/<config>/results.json`) and sleeps for that read's
recorded latency. Page rendering, ABA validation, pass disagreement, flagging and workbook generation
are all the production code.

Writes evals/roi/results.json and evals/roi/<config>/workbook.xlsx; summarize with python -m evals.roi.roi.
"""
import hashlib, json, os, random, sys, threading, time, zipfile
from io import BytesIO
from pathlib import Path

import httpx
import pymupdf
from fastapi.testclient import TestClient
from openai import APITimeoutError
from openpyxl import load_workbook

from app.config import Settings, get_settings
from app.main import app, get_extraction_service
from app.service import WireExtractionService, page_images
from evals.harness import DOCS, FIELDS, make_doc, norm

EVALS = Path(__file__).parent.parent
OUT = Path(__file__).parent
FLAG_COLOR = "FFE699"  # workbook.LOW_CONFIDENCE_FILL: the reviewer's "check this field" highlight

CONFIGS = {
    # name: (recorded reads, how a recorded run becomes the two passes, docs image-only?)
    "gpt-6-luna": ("gpt-6-luna/results.json", "pairs", False),
    "mistral-document-ai-2512-image-only": ("mistral-document-ai-2512-image-only/results.json", "pairs", True),
    "mistral-ocr+gpt-6-luna": ("mistral-ocr+gpt-6-luna/results.json", "pipeline", True),
    # The built combined unit: gpt-6-luna's extraction from Mistral's OCR text is the answer, Mistral's own
    # annotation of the page is the second reading it is checked against.
    "mistral-ocr+gpt-6-luna-extract": ("mistral-ocr+gpt-6-luna/results.json", "pipeline-luna", True),
}


def scan_like(pdf: bytes) -> bytes:
    """Image-only PDF, like a scanned wire instruction: no text layer, one JPEG per page (~100 KB, not
    the harness's 6 MB uncompressed pages, which would hit the 20 MiB upload limit at 3 documents)."""
    src = pymupdf.open(stream=pdf, filetype="pdf"); out = pymupdf.open()
    for page in src:
        target = out.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("jpeg", jpg_quality=85))
    return out.tobytes(garbage=3, deflate=True)


def recorded(path: str, mode: str) -> dict[str, list[tuple[list[dict], list[float]]]]:
    """Per doc type, a list of (two pass outputs, two pass latencies) built from recorded live reads."""
    runs = [r for r in json.loads((EVALS / path).read_text())["results"] if "error" not in r]
    out: dict[str, list] = {}
    for doc in DOCS:
        mine = [r for r in runs if r["doc"] == doc]
        if mode in ("pipeline", "pipeline-luna"):
            # One pass is Mistral OCR+annotation, the other luna on Mistral's text; disagreement is the flag.
            mistral = lambda r: {f: {"value": c["value"], "confidence": c["confidence"], "page": 1} for f, c in r["fields"].items()}
            luna = lambda r: {f: {"value": c["luna_value"], "confidence": c["luna_confidence"], "page": 1} for f, c in r["fields"].items()}
            order = (luna, mistral) if mode == "pipeline-luna" else (mistral, luna)
            out[doc] = [([order[0](r), order[1](r)], [r["seconds"] / 2] * 2) for r in mine]
        else:
            # Two independent reads of the same document = every ordered pair of distinct recorded reads.
            out[doc] = [([{f: {**a["fields"][f], "page": 1} for f in FIELDS}, {f: {**b["fields"][f], "page": 1} for f in FIELDS}],
                         [a["seconds"], b["seconds"]]) for a in mine for b in mine if a is not b]
        for passes, _ in out[doc]:
            for p in passes:
                for c in p.values():
                    c.pop("correct", None)
    return out


class ReplayResponses:
    """Stands in for client.responses: identifies the document by its rendered pages, returns recorded reads."""

    def __init__(self, reads, page_hashes: dict[str, str], rng: random.Random):
        self.reads, self.page_hashes, self.rng = reads, page_hashes, rng
        self.lock, self.state = threading.Lock(), {}
        self.calls = 0

    def create(self, *, input, timeout=None, **_):
        page = input[1]["content"][0]["image_url"]
        doc = self.page_hashes[hashlib.sha256(page.encode()).hexdigest()]
        key = (threading.get_ident(), doc)
        with self.lock:
            self.calls += 1
            if key not in self.state:  # first pass of this document in this worker thread
                self.state[key] = [self.rng.choice(self.reads[doc]), 0]
            (outputs, seconds), i = self.state[key]
            self.state[key][1] += 1
            if self.state[key][1] == len(outputs):
                del self.state[key]
        if timeout is not None and seconds[i] > timeout:
            time.sleep(max(timeout, 0))
            raise APITimeoutError(request=httpx.Request("POST", "https://replay/responses"))
        time.sleep(seconds[i])
        return type("R", (), {"output_text": json.dumps(outputs[i])})()


def score_workbook(content: bytes, truths: dict[str, dict] | None = None) -> list[dict]:
    """Score every row against ground truth: the harness DOCS by layout, or `truths` keyed by document source."""
    sheet = load_workbook(BytesIO(content))["Results"]
    headers = [c.value for c in sheet[5]]
    rows = []
    for row in sheet.iter_rows(min_row=6):
        source = row[0].value
        doc = next(d for d in DOCS if source.endswith(f"_{d}.pdf"))
        truth = truths[source] if truths else DOCS[doc]
        notes = row[headers.index("Notes")].value or ""
        fields = {}
        for f, cell in zip(FIELDS, row[1:1 + len(FIELDS)]):
            fields[f] = {"value": cell.value, "correct": norm(cell.value) == norm(truth[f]),
                         "flagged": cell.fill.fgColor.rgb.endswith(FLAG_COLOR)}
        rows.append({"source": source, "doc": doc, "review": row[headers.index("Manual Review Required")].value == "Yes",
                     # Failed rows (deadline, provider error) come back with every field empty and the reason in Notes.
                     "error": notes if all(c.value is None for c in row[1:1 + len(FIELDS)]) else None,
                     "fields": fields})
    return rows


def run_config(name: str, packages: int, seed: int) -> dict:
    # The app validates settings at startup; replay never reaches the network, so placeholders suffice.
    os.environ.setdefault("AZURE_AI_FOUNDRY_BASE_URL", "https://replay.openai.azure.com/")
    os.environ.setdefault("AZURE_AI_FOUNDRY_API_KEY", "replay")
    path, mode, flat = CONFIGS[name]
    pdfs = {d: make_doc(d, t) for d, t in DOCS.items()}
    if flat:
        pdfs = {d: scan_like(p) for d, p in pdfs.items()}
    hashes = {hashlib.sha256(page_images(p)[0]["image_url"].encode()).hexdigest(): d for d, p in pdfs.items()}
    replay = ReplayResponses(recorded(path, mode), hashes, random.Random(seed))
    settings = Settings(azure_ai_foundry_deployment=name)
    service = WireExtractionService(settings, client=type("C", (), {"responses": replay})())
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_extraction_service] = lambda: service

    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for i in range(packages):
            doc = list(DOCS)[i % len(DOCS)]
            z.writestr(f"IF-{i + 1:04d}_{doc}.pdf", pdfs[doc])
    try:
        with TestClient(app) as client:
            t = time.monotonic()
            r = client.post("/extract", files={"file": ("phase1-batch.zip", archive.getvalue(), "application/zip")})
            wall = time.monotonic() - t
    finally:
        app.dependency_overrides.clear()
    r.raise_for_status()
    (OUT / name).mkdir(exist_ok=True)
    (OUT / name / "workbook.xlsx").write_bytes(r.content)
    return {"config": name, "packages": packages, "seed": seed, "wall_seconds": round(wall, 1),
            "model_calls": replay.calls, "concurrency": settings.max_concurrent_extractions,
            "deadline_seconds": settings.request_deadline_seconds, "rows": score_workbook(r.content)}


if __name__ == "__main__":
    argv = sys.argv[1:]
    seed = 7
    if "--seed" in argv:
        i = argv.index("--seed"); seed = int(argv[i + 1]); del argv[i:i + 2]
    only = None
    if "--only" in argv:
        i = argv.index("--only"); only = argv[i + 1]; del argv[i:i + 2]
    packages = int(argv[0]) if argv else 100
    results = []
    for name in [only] if only else CONFIGS:
        res = run_config(name, packages, seed)
        rows = res["rows"]
        print(f"{name}: {res['wall_seconds']} s for {packages} packages, review {sum(r['review'] for r in rows)}, "
              f"errors {sum(bool(r['error']) for r in rows)}", flush=True)
        results.append(res)
    if only:  # replace just this config's run, keep the others
        existing = json.loads((OUT / "results.json").read_text())
        results = [r for r in existing["runs"] if r["config"] != only] + results
    (OUT / "results.json").write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "runs": results}, indent=1))
    print("wrote", OUT / "results.json")
