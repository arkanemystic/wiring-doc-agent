"""Dual-model pipeline experiment: Mistral OCR + annotation, gpt-6-luna extracting from Mistral's text.

Usage (from the repo root, .env pointing at the Mistral OCR endpoint):
  python "evals/mistral-ocr+gpt-6-luna/experiment.py" [reads_per_doc]
A value is flagged when Mistral and luna disagree, when it does not appear verbatim in the OCR text,
or (routing number) when it fails the ABA checksum.
"""
import base64, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from app.config import Settings
from app.models import ModelExtraction
from app.service import SYSTEM_PROMPT, is_valid_aba, strict_json_schema
from evals.harness import DOCS, FIELDS, image_only, make_doc, norm
from openai import OpenAI

SCHEMA = strict_json_schema(ModelExtraction.model_json_schema())
settings = Settings()
KEY = settings.azure_ai_foundry_api_key.get_secret_value()
OCR_URL = settings.azure_ai_foundry_base_url.rstrip("/")
host = re.match(r"https://[^/]+", OCR_URL).group(0)
luna = OpenAI(api_key=KEY, base_url=f"{host}/openai/v1/", timeout=90)


def mistral(pdf: bytes) -> tuple[dict, str]:
    body = {"model": "mistral-document-ai-2512", "include_image_base64": False,
            "document": {"type": "document_url", "document_url": "data:application/pdf;base64," + base64.b64encode(pdf).decode()},
            "document_annotation_format": {"type": "json_schema", "json_schema": {"name": "wire", "strict": True, "schema": SCHEMA}},
            "document_annotation_prompt": SYSTEM_PROMPT}
    for _ in range(5):
        r = httpx.post(OCR_URL, headers={"Authorization": f"Bearer {KEY}"}, json=body, timeout=180)
        if r.status_code != 429:
            break
        time.sleep(int(r.headers.get("retry-after", 10)) + 1)
    r.raise_for_status()
    j = r.json()
    text = "\n\n".join(f"--- Page {p['index'] + 1} ---\n{p['markdown']}" for p in j["pages"])
    return ModelExtraction.model_validate_json(j["document_annotation"]).model_dump(), text


def luna_from_text(text: str) -> dict:
    r = luna.responses.create(
        model="gpt-6-luna",
        input=[{"role": "system", "content": SYSTEM_PROMPT},
               {"role": "user", "content": f"OCR text of the document, page by page:\n\n{text}\n\nExtract the wire-instruction fields."}],
        text={"format": {"type": "json_schema", "name": "wire", "strict": True, "schema": SCHEMA}})
    return ModelExtraction.model_validate_json(r.output_text).model_dump()


def compact(v: str | None) -> str:
    return re.sub(r"\s+", " ", (v or "")).casefold()


def run(name: str, pdf: bytes, i: int) -> dict:
    t = time.monotonic()
    try:
        m, text = mistral(pdf)
        l = luna_from_text(text)
    except Exception as e:
        return {"doc": name, "run": i, "error": f"{type(e).__name__}: {e}"[:300]}
    fields = {}
    for f in FIELDS:
        value = m[f]["value"]
        reasons = []
        if norm(value) != norm(l[f]["value"]):
            reasons.append(f"models disagree ({l[f]['value']!r})")
        if value and compact(value) not in compact(text):
            reasons.append("not verbatim in OCR text")
        if f == "routing_number_aba" and value and not is_valid_aba(value.replace("-", "").replace(" ", "")):
            reasons.append("ABA checksum")
        fields[f] = {"value": value, "confidence": m[f]["confidence"], "luna_value": l[f]["value"],
                     "luna_confidence": l[f]["confidence"], "correct": norm(value) == norm(DOCS[name][f]),
                     "luna_correct": norm(l[f]["value"]) == norm(DOCS[name][f]), "flags": reasons}
    return {"doc": name, "run": i, "seconds": round(time.monotonic() - t, 2), "fields": fields}


if __name__ == "__main__":
    reads = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    docs = {n: image_only(make_doc(n, t)) for n, t in DOCS.items()}
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda j: run(*j), [(n, docs[n], i) for n in docs for i in range(reads)]))
    out = Path(__file__).with_name("results.json")
    out.write_text(json.dumps({"pipeline": "mistral-ocr+gpt-6-luna (image-only docs)", "reads": reads, "results": results}, indent=1))
    ok = [r for r in results if "error" not in r]
    cells = [(r["doc"], f, c) for r in ok for f, c in r["fields"].items()]
    print("errors:", len(results) - len(ok), "| reads:", len(ok))
    for label, sel in [("all fields", lambda f: True), ("ABA+account", lambda f: f in ("routing_number_aba", "account_number")),
                       ("excluding beneficiary_name", lambda f: f != "beneficiary_name")]:
        cs = [c for d, f, c in cells if sel(f)]
        wrong = [c for c in cs if not c["correct"]]
        print(f"{label:28s} mistral right {len(cs) - len(wrong)}/{len(cs)}, luna-on-text right {sum(c['luna_correct'] for c in cs)}/{len(cs)}, "
              f"wrong {len(wrong)} -> flagged {sum(bool(c['flags']) for c in wrong)}, silent {sum(not c['flags'] for c in wrong)}, "
              f"false alarms {sum(bool(c['flags']) for c in cs if c['correct'])}")
    print("median seconds:", sorted(r["seconds"] for r in ok)[len(ok) // 2])
    for d, f, c in cells:
        if c["flags"] or not c["correct"]:
            print(f"  {d:16s} {f:20s} {'WRONG' if not c['correct'] else 'ok   '} {c['value']!r} flags={c['flags']}")
