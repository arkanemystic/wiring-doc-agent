"""Run a VLM deployment over synthetic wire instructions through the real service code path.

Usage (from the repo root):
  python -m evals.harness <deployment> [reads_per_doc] [--backend responses|mistral-ocr] [--image-only]
Writes evals/<deployment>[-image-only]/results.json; summarize with python -m evals.report.

Backends:
  responses    (default) the production path: WireExtractionService and the OpenAI Responses API.
  mistral-ocr  Mistral Document AI on Azure: POSTs the PDF to AZURE_AI_FOUNDRY_BASE_URL (the
               .../providers/mistral/azure/ocr endpoint) with our JSON schema as document_annotation_format
               and the production system prompt as document_annotation_prompt.
--image-only re-renders every document as an image-only PDF (no text layer), like a scan.
"""
import base64, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx
import pymupdf
from app.config import Settings
from app.models import ModelExtraction
from app.service import SYSTEM_PROMPT, WireExtractionService, is_valid_aba, strict_json_schema

FIELDS = ["beneficiary_name", "beneficiary_address", "bank_name", "bank_address", "routing_number_aba", "account_number"]

DOCS = {
    # name: (truth, layout)
    "baseline": dict(
        beneficiary_name="Brightwater Escrow Services Client Trust Account",
        beneficiary_address="2250 Lakeview Drive, Suite 300, Columbus, OH 43215",
        bank_name="Meridian Trust Bank", bank_address="400 Commerce Plaza, Dayton, OH 45402",
        routing_number_aba="021000021", account_number="7712-558-203"),
    "repeated_digits": dict(
        beneficiary_name="Hollowell & Gibbs Settlement Account",
        beneficiary_address="88 Mill Street, Floor 11, Hartford, CT 06103",
        bank_name="Connell Harbor Savings Bank", bank_address="1100 Asylum Avenue, Hartford, CT 06105",
        routing_number_aba="011000138", account_number="0001100223"),
    "long_account": dict(
        beneficiary_name="Sorrento Title Agency LLC",
        beneficiary_address="4410 Granite Ridge Road, Unit B, Boise, ID 83706",
        bank_name="Alpine Mutual Federal Credit Union", bank_address="77 Front Street, Boise, ID 83702",
        routing_number_aba="124100064", account_number="55500117788004"),
    "dense_table": dict(
        beneficiary_name="Kittredge Lane Closing Services",
        beneficiary_address="19 Harbor Point, Suite 1200, Baltimore, MD 21231",
        bank_name="Chesapeake Fiduciary Bank", bank_address="300 Pratt Street, Baltimore, MD 21202",
        routing_number_aba="052000113", account_number="3300-0090-1144"),
    "blurry_scan": dict(
        beneficiary_name="Brightwater Escrow Services Client Trust Account",
        beneficiary_address="2250 Lakeview Drive, Suite 300, Columbus, OH 43215",
        bank_name="Meridian Trust Bank", bank_address="400 Commerce Plaza, Dayton, OH 45402",
        routing_number_aba="021000021", account_number="7712-558-203"),
    "two_page": dict(
        beneficiary_name="Pellham Ridge Escrow Trust",
        beneficiary_address="600 Elm Court, Suite 210, Tulsa, OK 74103",
        bank_name="Red Prairie National Bank", bank_address="15 Boulder Avenue, Tulsa, OK 74119",
        routing_number_aba="103000648", account_number="881-00-7766-1"),
}
for t in DOCS.values():
    assert is_valid_aba(t["routing_number_aba"]), t


def write_lines(page, lines, y=60, size=11):
    for line in lines:
        page.insert_text((60, y), line, fontsize=size); y += size + 8
    return y


def body(t):
    company = t["beneficiary_name"].replace(" Client Trust Account", "").replace(" Settlement Account", "")
    return [f"{company}", t["beneficiary_address"], "Phone (555) 010-2234", "",
            "WIRE TRANSFER INSTRUCTIONS", "",
            f"ABA Routing Number: {t['routing_number_aba']}",
            f"Beneficiary Bank Name: {t['bank_name']}",
            f"Beneficiary Bank Address: {t['bank_address']}",
            f"Beneficiary Account Number: {t['account_number']}",
            f"Beneficiary Account Name: {t['beneficiary_name']}"]


def make_doc(name, t) -> bytes:
    doc = pymupdf.open()
    if name == "dense_table":
        page = doc.new_page()
        y = write_lines(page, body(t)[:3], size=9)
        rows = [("Field", "Value")] + [tuple(l.split(": ", 1)) for l in body(t)[6:]] + [
            ("Intermediary Bank", "None"), ("Reference", "File 2026-11-0042 / Buyer: R. Ostrowski"),
            ("Amount", "USD 412,880.00"), ("Contact", "Wire desk (555) 010-9981, ext. 1100")]
        y += 10
        for a, b in rows:
            page.draw_rect(pymupdf.Rect(55, y - 11, 555, y + 5), width=0.5)
            page.insert_text((60, y), a, fontsize=8); page.insert_text((230, y), b, fontsize=8); y += 16
    elif name == "two_page":
        p1 = doc.new_page()
        write_lines(p1, body(t)[:5] + ["", "Please read the fraud warning before wiring funds.",
                                        "Wiring details are on page 2. Always call to verify."])
        p2 = doc.new_page()
        write_lines(p2, ["Page 2 - Wiring details", ""] + body(t)[6:])
    else:
        write_lines(doc.new_page(), body(t))
    pdf = doc.tobytes()
    if name == "blurry_scan":
        # Rasterize at low resolution and re-embed as an image-only PDF (no text layer), like a fax.
        src = pymupdf.open(stream=pdf, filetype="pdf")
        pix = src[0].get_pixmap(matrix=pymupdf.Matrix(0.9, 0.9), colorspace=pymupdf.csGRAY)
        out = pymupdf.open(); page = out.new_page()
        page.insert_image(page.rect, stream=pix.tobytes("jpeg", jpg_quality=35))
        pdf = out.tobytes()
    return pdf


def norm(v):
    return None if v is None else " ".join(v.replace(".", "").split()).casefold()


class Recorder:
    def __init__(self, inner): self.inner = inner; self.calls = []
    def create(self, **kw):
        t = time.monotonic(); r = self.inner.create(**kw)
        u = getattr(r, "usage", None)
        self.calls.append({"seconds": round(time.monotonic() - t, 2), "output": json.loads(r.output_text),
                           "input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None)})
        return r


def image_only(pdf: bytes, scale: float = 2) -> bytes:
    src = pymupdf.open(stream=pdf, filetype="pdf"); out = pymupdf.open()
    for page in src:
        target = out.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=page.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png"))
    return out.tobytes()


def scored(name, i, seconds, output, input_tokens=None, output_tokens=None):
    truth = DOCS[name]
    fields = {f: {"value": output[f]["value"], "confidence": output[f]["confidence"],
                  "correct": norm(output[f]["value"]) == norm(truth[f])} for f in FIELDS}
    return {"doc": name, "run": i, "seconds": seconds, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "fields": fields}


def one_read(deployment, name, pdf, i):
    service = WireExtractionService(Settings(azure_ai_foundry_deployment=deployment, extraction_passes=1))
    rec = Recorder(service._client.responses)
    service._client = type("C", (), {"responses": rec})()
    try:
        service.extract(content=pdf, filename=f"{name}.pdf", content_type=None, document_source=name)
    except Exception as e:
        return {"doc": name, "run": i, "error": f"{type(e).__name__}: {e}"[:300]}
    call = rec.calls[0]
    return scored(name, i, call["seconds"], call["output"], call["input_tokens"], call["output_tokens"])


def one_read_mistral(deployment, name, pdf, i):
    settings = Settings()
    body = {
        "model": deployment,
        "document": {"type": "document_url", "document_url": "data:application/pdf;base64," + base64.b64encode(pdf).decode()},
        "include_image_base64": False,
        "document_annotation_format": {"type": "json_schema", "json_schema": {
            "name": "wire_instruction_extraction", "strict": True,
            "schema": strict_json_schema(ModelExtraction.model_json_schema())}},
        "document_annotation_prompt": SYSTEM_PROMPT,
    }
    headers = {"Authorization": f"Bearer {settings.azure_ai_foundry_api_key.get_secret_value()}"}
    for _ in range(5):
        t = time.monotonic()
        try:
            r = httpx.post(settings.azure_ai_foundry_base_url.rstrip("/"), headers=headers, json=body, timeout=180)
        except httpx.HTTPError as e:
            return {"doc": name, "run": i, "error": f"{type(e).__name__}: {e}"[:300]}
        if r.status_code != 429:
            break
        time.sleep(int(r.headers.get("retry-after", 10)) + 1)
    seconds = round(time.monotonic() - t, 2)
    try:
        r.raise_for_status()
        output = ModelExtraction.model_validate_json(r.json()["document_annotation"]).model_dump()
    except Exception as e:
        return {"doc": name, "run": i, "error": f"{type(e).__name__}: {e} {r.text[:200]}"[:400]}
    return scored(name, i, seconds, output)


if __name__ == "__main__":
    argv = sys.argv[1:]
    backend = "responses"
    if "--backend" in argv:
        index = argv.index("--backend"); backend = argv[index + 1]; del argv[index:index + 2]
    flatten = "--image-only" in argv
    args = [a for a in argv if not a.startswith("--")]
    deployment = args[0]; reads = int(args[1]) if len(args) > 1 else 5
    reader = {"responses": one_read, "mistral-ocr": one_read_mistral}[backend]
    docs = {n: make_doc(n, t) for n, t in DOCS.items()}
    if flatten:
        docs = {n: image_only(d) for n, d in docs.items()}
    jobs = [(n, docs[n], i) for n in DOCS for i in range(reads)]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda j: reader(deployment, *j), jobs))
    label = deployment + ("-image-only" if flatten else "")
    out = Path(__file__).parent / label / "results.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"deployment": label, "backend": backend, "reads": reads, "results": results}, indent=1))
    print("wrote", out, "errors:", sum("error" in r for r in results))
