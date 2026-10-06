# Local testing log

Tested locally on Python 3.14 with: the existing suite, probe scripts, and the real app served over HTTP
against a mock Azure Responses endpoint (429/400/500/HTML/bad-JSON/empty/refusal/slow/extra-field replies).
Every fixed item below has a regression test in `tests/test_regressions.py`.
The suite (53 tests) also passes on Python 3.10.1 and 3.13.12, the Azure Functions runtime range.

## Fixed

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | High | `.docx`/`.xlsx` uploads were detected as ZIP archives (they are ZIP containers) and exploded into their XML parts (`app.xml`, `sheet1.xml`...), each sent to the model. | ZIP sniffing skips Office/PDF suffixes (`main.is_zip_upload`). |
| 2 | High | Spreadsheet formula injection: extracted text such as `=HYPERLINK(...)` was written as a live formula (openpyxl infers `f`). The text comes from untrusted documents. | `workbook.text_cell` forces string type and quote-prefixes `= + - @`. Also applied to `source_url` and filenames. |
| 3 | High | One failing document in a ZIP returned 502 for the whole batch and discarded every other result. | Per-member isolation; failed members become manual-review rows with a new `Processing Error` column (col I). |
| 4 | Medium | Control characters in extracted text raised `IllegalCharacterError` and returned a bare 500. | Illegal characters are stripped before writing. |
| 5 | Medium | PDFs uploaded as `application/octet-stream` (curl, many clients) were sent as `input_file` instead of being rendered to page images, contradicting the documented behaviour. | `service.detect_mime_type` trusts file signatures (`%PDF-`, TIFF) over the declared type. |
| 6 | Medium | `.tif/.tiff` accepted by the demo page but sent as `input_image/tiff`, which the model API does not support. | TIFFs are rendered page-by-page to PNG like PDFs. |
| 7 | Medium | macOS-created ZIPs include `__MACOSX/._x.pdf` and `.DS_Store`; each became a document sent to the model (wasted calls, failed rows). | Junk members are skipped. |
| 8 | Medium | Corrupt/truncated/password-protected PDFs returned 502 (blamed the upstream); an encrypted PDF leaked "document closed or encrypted". | New `InvalidDocumentError` -> HTTP 422 with clear text. |
| 9 | Medium | Unbounded fan-out: a 100-file ZIP fired 100 simultaneous model calls (rate limits, memory). | `MAX_CONCURRENT_EXTRACTIONS` semaphore (default 8). |
| 10 | Medium | No PDF page limit: a 300-page PDF took 6.6s and produced ~4.5 MiB of base64 images in one request. | `MAX_PDF_PAGES` (default 25) -> 422. |
| 11 | Medium | Strict JSON schema sent to Azure contained `minimum`/`maximum`, which strict structured outputs can reject. | Bounds stripped from the outgoing schema; still enforced when validating the reply. **Unverified against the real service** (see below). |
| 12 | Medium | Placeholder `.env` (copied from `.env.example`) was accepted; the first upload failed with "Verify network connectivity". Missing config surfaced as a 500 at request time. | Placeholders rejected, and settings validated at startup (fail fast). |
| 13 | Low | Two ZIP members with the same name in different folders produced identical `document_source` values. | Source now includes the in-archive path (`batch.zip#a/x.pdf`). |
| 14 | Low | Upstream 429 was reported as 502. | Passed through as 429 with `Retry-After`. |
| 15 | Low | Schema-mismatch errors leaked pydantic internals to the client. | Generic message; detail logged server-side. |
| 16 | Low | System prompt referenced `source`/`name_match` fields that are not in the schema. | Prompt aligned with the schema. |
| 17 | Low | Model calls could hang up to the SDK default (10 min). | `REQUEST_TIMEOUT_SECONDS` (default 90). |
| 18 | Low | Deprecated `fitz` import. | `pymupdf`. |
| 19 | High | **Live model drops/merges repeated characters while reporting ~95% confidence** (see below). | Routing numbers are validated (9 digits + ABA checksum); failures are highlighted, set manual-review and explained in the `Notes` column. |
| 20 | High | Confidence is uncalibrated; account numbers and names have no checksum, so wrong high-confidence readings went unflagged. | Opt-in `EXTRACTION_PASSES` (1-3): fields whose independent reads disagree (ignoring case/whitespace) are highlighted, set manual-review and explained in `Notes`. Default is 2 for production. |
| 21 | Medium | `.docx`/`.xlsx` (and any other non-image type) were sent as `input_file` and failed at the provider. | Allowlist (PDF, TIFF, PNG, JPEG, GIF, WebP) checked before any model call -> 422 / row error; removed from the demo page. Image signatures are now sniffed too, so `octet-stream` images work. |
| 22 | Low | `source_url` was not validated. | Must be an absolute http(s) URL of at most 2048 characters, else 400. |
| 23 | Low | Nested ZIPs were sent to the model and failed. | Expanded up to 3 levels deep, sharing the file-count and uncompressed-byte budgets; junk members skipped at every level. |
| 24 | Medium | 100 documents at 90 s / 8-way concurrency could exceed the ~230 s Azure Functions HTTP limit. | `REQUEST_DEADLINE_SECONDS` (default 200): each call gets `timeout=min(REQUEST_TIMEOUT_SECONDS, time left)`; unfinished ZIP members become "Not processed" rows; a single document returns 504. SDK timeouts map to 504 / "did not respond in time". |
| 25 | Low | `HEAD /health` returned 405. | `/health` accepts GET and HEAD. |

## Live Azure results (deployment `gpt-6-luna`, synthetic one-page PDF)

The strict schema and image input are **accepted** by Azure (HTTP 200 in ~3.5 s); Azure error mapping works.
Extraction accuracy is the problem. Ground truth: bank `Meridian Trust Bank`, ABA `021000021`, account `7712-558-203`.

- Transcription varies run to run and is usually wrong: 0/8 fully correct on the original prompt, 1/8 with a
  "read digit by digit" prompt, 0/8 each at 4x render zoom (with and without the prompt). Typical errors:
  `Merian`, `02100021` (dropped 0), `7712-58-203` / `712-58-203` (dropped 5), always with 0.95 confidence.
  The rendered page image was verified crisp and correct, so this is the model's reading, not the input.
- Prompt wording and zoom did not help, so neither was changed (`PAGE_RENDER_SCALE` is now a constant for experiments).
- Mitigation shipped: ABA validation (#19). 5 of 6 bad readings were caught in the final run.
- **Mitigated only when `EXTRACTION_PASSES` >= 2 (#20): account numbers and names have no checksum.** The account number was wrong in 6/6 runs with
  high confidence and is *not* flagged. Do not use these workbooks unreviewed. Recommended next steps: deploy a
  stronger vision model and re-run `experiment.py`-style trials; and/or run two independent passes and flag any
  field where they disagree (doubles cost); and/or read PDFs with a text layer directly (currently deliberately
  not done: "The service does not perform OCR or extract PDF text locally").

## Live re-test with `EXTRACTION_PASSES=2` (2026-10-05, deployment `gpt-6-luna`)

32 trials of the same synthetic PDF (64 model reads), plus one 16-document ZIP through the HTTP app.

| Field | Wrong reads | Wrong final values | Wrong *and unflagged* | Both reads wrong, same value |
|---|---|---|---|---|
| Routing number (ABA) | 53/64 | 28/32 | 0 | 23/32 |
| Account number | 4/64 | 2/32 | 0 | 0/32 |
| Beneficiary name, bank name | 0/64 | 0/32 | 0 | 0/32 |

- **No wrong value went unflagged.** Account-number errors (`772-558-203`, a dropped repeated digit) were caught only
  because the two reads disagreed. Routing errors (`02100021`, a dropped repeated `0`) were caught by the ABA checksum.
- **The two reads are not independent.** In 23/32 trials both reads dropped the same `0` from the routing number.
  Disagreement alone would have missed these, so an account number with a similar repeated-digit pattern could
  still be misread identically twice and pass unflagged. Disagreement checking reduces this risk; it does not remove it.
- **Every row was marked for review (32/32).** The model misreads `021000021` almost every time, so in practice the
  workbook is a review queue, not an automatic result.
- Two reads take 5.3-11.0 s per document (median 7.5 s). The 16-document ZIP returned 200 in 19 s with no errors,
  which projects to about 120 s for 100 documents at 8-way concurrency. That is inside the 200 s deadline only if
  Azure does not rate-limit the 200 calls; any 429s become row errors.

## Open / not fixed

- Correlated misreads (above) remain the main accuracy risk. The fix is a stronger vision model, not more passes of
  the same one. Reading the PDF text layer to cross-check values would also catch them, but that is currently
  excluded by design.
- Thread cleanup at the deadline: when `REQUEST_DEADLINE_SECONDS` expires, the in-flight worker thread is abandoned
  but stops on its own because each SDK call gets the remaining time as its timeout (SDK retries can extend this
  by at most `max_retries` x that timeout).

## Closed without change

- "ZIP size limits trust the declared `file_size`": verified not exploitable. `zipfile` stops inflating at the
  declared size and the CRC check then fails, which is reported as an invalid ZIP (400). Covered by
  `test_archive_member_larger_than_declared_is_rejected`.
