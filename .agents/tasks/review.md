# Telegram bot answering medcard questions (step 6)

Adds three stdlib-only files under `app/` — `bot.py` (Telegram HTTP client over `urllib`), `ask.py` (builds the model context from the medcard and returns `{text, charts}`), and `charts.py` (Pillow PNG renderer). The implementation is a verbatim adoption of the step-6 reference solution, which already targets the project's real `config`/`llm`/`medcard` APIs and the actual `data/health-record.json` shape, so there is no drift from the spec. The commit (`e882924`) touches only those three files and nothing else. **Watch for:** nothing blocking — the files are byte-identical to the reference solution (confirmed), scope is clean (confirmed), and the token is never printed or hardcoded (confirmed).

**Verdict**: APPROVED

## High-level view

The bot long-polls `getUpdates` with `timeout=25` and a 40s socket wait, matching the spec's "network wait 15s longer than the poll timeout." The first chat to send `/start` is written to `config.OWNER_FILE` (`data/.bot-owner`) and all other chats are silently ignored — the owner gate is applied before any question is processed.

Answers run in a daemon thread so the poller never blocks. While the model thinks, a `Working` helper posts "🔎 Смотрю медкарту…", resends the typing action every 4s, and deletes the status message when done. The answer contract is a strict `{text, charts}` JSON schema; chart keys are mapped back to real biomarker objects from the loaded medcard and capped at 4, so the model cannot inject fabricated series.

Rich-text safety is handled by escaping the whole answer with `html.escape` first and only then converting `**bold**` to `<b>`, so a literal "< 5.2" in the text cannot break Telegram's HTML parse. Charts are rendered by Pillow, imported lazily inside `try/except ImportError` so a host without `python3-pil` degrades to text-only rather than crashing.

The Rules hold: SI units and real values come straight from the medcard JSON (the code never invents numbers), the no-diagnosis/no-prescription and Russian plain-language constraints live in the `SYSTEM` prompt, and the Telegram token is read from `config` and never logged. Scope is clean: only `app/bot.py`, `app/ask.py`, `app/charts.py` were added; `run.py`, `config.py`, `dashboard/`, and `.env` are untouched.

<details>
<summary>Issues (0)</summary>

No blocking or non-blocking findings.

</details>

<details>
<summary>Details</summary>

### Faithfulness to the spec

Every spec point maps to code (confirmed by reading all three files against the reference solution and `spec.md`). Owner handling writes the first `/start` sender's id to `config.OWNER_FILE` via `is_owner` and ignores everyone else; the welcome text matches the spec wording. The long-poll uses `getUpdates(_wait=40, timeout=25)` — the 40s socket timeout is exactly the "15s longer" the spec asks for. The placeholder/typing behavior, the `{text, charts}` schema (strict, `additionalProperties: False`), the up-to-last-3 reply-pairs of history, the garmin brief (norms + last 30 days), and the human-readable-date / 2–6-line / `**bold**`-only formatting rules in `SYSTEM` all match.

### `**bold**` → HTML with escaping

`to_html` escapes the full string with `html.escape` and then applies `re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", ...)` (confirmed). Because escaping runs first, any literal `<` or `>` in the model's text (e.g. "< 5.2") is neutralized before the bold substitution, so it cannot corrupt the HTML Telegram parse. The non-greedy capture is correct for paired `**` markers.

### Answer shape and no fabricated values

`ask.answer` passes only `medcard.load()` and the garmin brief to the model, then remaps the returned `charts` keys through `by_key = {b["key"]: b ...}` and caps at 4 (confirmed). The chart data therefore always resolves to real biomarker objects from `data/health-record.json`; the model cannot smuggle invented series into the PNG. SI units are whatever the medcard carries. No-diagnosis/no-prescription and Russian plain language are enforced in `SYSTEM`.

### Pillow and stdlib-only

`charts.py` is the only non-stdlib dependency and uses `from PIL import Image, ImageDraw, ImageFont` — the allowed system-package exception, not a pip dependency, and correctly left in place (confirmed). `bot.py` imports `charts` lazily inside `try/except ImportError`, so a host without Pillow falls back to text-only. Everything else is `urllib`, `json`, `threading`, `html`, `re`, `uuid` — standard library.

### Token handling

The token is read as `config.TELEGRAM_BOT_TOKEN` and interpolated into the API base URL only; the bot prints `@<username>` from `getMe`, never the token, and prints a friendly notice when the token is empty (confirmed). A grep for the real token value across `app/` and `run.py` returns nothing — it is not hardcoded or committed. `.env` was not modified by the commit.

### Scope and wiring

The implementing commit `e882924` adds exactly `app/bot.py`, `app/ask.py`, `app/charts.py` (289 insertions, 0 deletions) and touches no other file (confirmed via `git show --stat`). `run.py` already imports `bot` in default/`bot` modes and `ask`/`charts` in `ask` mode with correct ImportError fallbacks, and `config.py` already defines `TELEGRAM_BOT_TOKEN`, `OWNER_FILE`, `GARMIN`, `RECORD`, so neither needed changes. `dashboard/` and `.env` are untouched. The working-tree modifications to `data/garmin.json` and `data/health-record.json` are from earlier lesson steps and are not part of this commit.

### Verification evidence

The coder's recorded evidence is the commit message ("Verified python run.py check clean and imports OK") plus the plan's step-5 verification procedure. Per instructions I did not re-run the project suites. I ran one narrow, cheap spot-check — `ast.parse` on all three files — which passed, confirming they are syntactically valid even on this host (where Pillow may be absent and a full `import charts` is not a reliable signal).

</details>

<details>
<summary>File map</summary>

- `app/bot.py` — new: stdlib Telegram client (getUpdates long-poll, owner gate, typing placeholder, multipart sendPhoto, `**bold**`→HTML).
- `app/ask.py` — new: builds medcard+garmin context, calls `llm.ask` with strict `{text, charts}` schema, remaps chart keys to real biomarkers.
- `app/charts.py` — new: Pillow PNG renderer, one stacked panel per biomarker (max 4).

Full diff: `git show e882924` (base `e4aba08` / `origin/main`).

</details>
