# Notes: mistral-document-ai-2512 (2026-10-06)

- **All 15 wrong fields are one ambiguity, not misreads.** Mistral returns the company name (`Brightwater Escrow
  Services`) where the ground truth is the labelled account name (`Brightwater Escrow Services Client Trust Account`).
  Every routing number, account number, address and bank name was transcribed exactly, in both the normal and
  image-only runs.
- Removing the text layer (`-image-only`) did not change accuracy, so it reads the page image, not just embedded text.
  Median latency rose from 2.7 s to 6.6 s.
- Confidence is self-reported by the annotation model and is not calibrated either (0.95 on the wrong names).
- Quota on this deployment: 50 requests / 60 s.
- Not a drop-in: it uses its own OCR endpoint, not the Responses API, so the service needs a second client
  path to use it.
