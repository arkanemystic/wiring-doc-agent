# Notes: Mistral OCR + gpt-6-luna pipeline (2026-10-06)

Experiment: `experiment.py`, 6 image-only documents x 3 reads (18 runs, 108 fields). Mistral OCRs the page and fills
the schema; gpt-6-luna fills the same schema from Mistral's OCR text (no image). A value is flagged when the two
disagree, when it is not verbatim in the OCR text, or when the ABA checksum fails.

| | Result |
|---|---|
| Routing + account numbers right | Mistral 36/36, luna-on-text 36/36 |
| All fields right | Mistral 100/108, luna-on-text 105/108 |
| Wrong values left unflagged | **0 of 8** |
| Correct values flagged anyway | 1 (OCR text has `&amp;` for `&`; fix by HTML-unescaping the OCR markdown) |
| Median time per document | 12.0 s (image-only) |

- luna's misreads disappear when it reads text instead of the image (36/36 vs 15/60 on images).
- All 8 wrong values are the beneficiary-name ambiguity (company vs account name) and all were flagged by disagreement.
- **Untested failure mode:** both models depend on the same OCR text, so an OCR misread would be copied by both and pass
  the verbatim check. Mistral OCR made no errors here, so its error rate on real documents is unknown. Only the
  ABA checksum would catch such an error, and only for routing numbers.
