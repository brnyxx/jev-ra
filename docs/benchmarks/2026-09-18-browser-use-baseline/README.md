# browser-use baseline, 2026-09-18

Rows produced by `bench.py` (browser-use 0.13.10, `use_vision=False`, `max_steps=25`, 240 s timeout per task)
against a dedicated Chrome at `http://127.0.0.1:9222` with a 1280x900 window, driver models via OpenRouter.

- `results_google_gemini-3-flash-preview_default.jsonl` - default agent settings
- `results_google_gemini-3-flash-preview_flash.jsonl` - `flash_mode=True` (browser-use's own fast mode)
- `results_openai_gpt-5-mini_default.jsonl`
- `results_anthropic_claude-sonnet-5_default.jsonl` - failed: OpenRouter rejected the structured-output schema ("compiled grammar is too large"); kept for the record, excluded from ratios

One run per cell. Wall time is measured around `agent.run()` and includes the CDP connect. The Olive Young result for
gpt-5-mini is a timeout. The gpt-5-mini Flights row hit the step budget; its final URL is not a verified one-way search.
