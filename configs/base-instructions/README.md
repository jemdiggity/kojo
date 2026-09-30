# Base-instruction overrides

Each file is the exact text a Codex session sends as the model's base instructions,
for use with `kojo.factory --base-instructions FILE`. Passing one replaces the model's
own stock base prompt, so the run is **not** a stock-protocol baseline and its manifest
says so.

| File | Contents |
|---|---|
| `gpt-6-luna-stock.md` | `gpt-6-luna`'s own base instructions (reference copy) |
| `gpt-6.1-sol-stock.md` | `gpt-6.1-sol`'s own base instructions, captured from a stock run |
| `gpt-6-luna-stock-with-sol-testing-lines.md` | Luna's text with its one testing line ("Do not add or run tests unless…") replaced by sol's two testing lines |

Captured from the `session_meta` of saved native transcripts, which match the
developer message in the request byte for byte.
