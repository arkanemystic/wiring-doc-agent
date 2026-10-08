# Cohere-parse-v5

**Not evaluated: the deployment does not accept any request format the service uses.** (2026-10-06)

| Request | Result |
|---|---|
| Responses API, page images (production path) | 400 `Model 'Cohere-parse-v5' does not support image inputs` |
| Responses API, text only or PDF `input_file` | 404 `Requested API is currently not supported` |
| `/openai/v1/chat/completions` | 404 `api_not_supported` |
| `/models/chat/completions` (model inference API) | 404 `api_not_supported` (after the rate limit cleared) |
| `/openai/deployments/Cohere-parse-v5/chat/completions` | 429 only; never reached the model |

- The deployment's quota is **2 requests per 60 s** (`x-ratelimit-limit-requests: 2`). A 30-read eval would take 15+ minutes; production use would need a quota increase.
- As a "parse" model it most likely returns parsed document text through its own endpoint, not the six fields in our JSON schema. It would then be a pre-processing step (parse, then extract with an LLM), not a drop-in replacement.
- To evaluate it, take the endpoint and request format from the deployment's page in Foundry (Target URI and code sample), and add an adapter in `evals/harness.py`.

## Retry with the `services.ai.azure.com` base URL (2026-10-06)

Same results: page images -> 400 `does not support image inputs`; PDF `input_file` and text-only Responses
requests -> 404 `Requested API is currently not supported`.
