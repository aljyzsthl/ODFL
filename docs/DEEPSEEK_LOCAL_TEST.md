# DeepSeek local-test branch

This branch replaces the SEA Claude endpoint with DeepSeek's
Anthropic-compatible Messages API. It is for local comparison only.

Official references:

- <https://api-docs.deepseek.com/guides/anthropic_api/>
- <https://api-docs.deepseek.com/guides/vision/>

## Data path

1. PyMuPDF renders each PDF page to an in-memory JPEG.
2. The page images are sent to `deepseek-flash` as Anthropic image blocks.
3. The existing forced tool call returns the same `orders` JSON schema.
4. The existing Material Code gate still decides which lines can reach ERP.

The extraction request explicitly disables DeepSeek Thinking mode because the
API does not allow a forced named `tool_choice` while Thinking is enabled.

DeepSeek does not accept PDF `document` blocks. DRM documents that can only be
recovered as text continue through the existing text route.

## Setup

```bat
py -m pip install -r requirements.txt
set DEEPSEEK_API_KEY=your-key-for-this-console
py src\orderflow.py
```

Alternatively, paste the key under Settings > API. Leave Endpoint blank to use
`https://api.deepseek.com/anthropic`; the application appends `/v1/messages`.

DeepSeek settings are stored in an isolated `deepseek` block inside
`config/settings.json`. Switching between this branch and the production
Claude branch therefore cannot reuse or overwrite the other provider's key.

## Safety and limitations

- A PO leaves the PC and is processed by DeepSeek. Use only documents approved
  for that service.
- Inline image requests are capped below DeepSeek's 48 MiB body limit.
- `deepseek-flash` is the only selectable model because PDF processing needs
  image input.
- API connectivity is not part of the offline regression suite. Use Settings >
  API > Test PO reading, then test a non-sensitive PO in Quick Convert.
