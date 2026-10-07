# Implementation Plan — Шаг 6: Telegram-бот отвечает на вопросы по медкарте

## Context (grounded in exploration)

Goal: build a Telegram bot that answers questions about the user's medical card ("медкарта") in Russian, with chart images, following `steps/06-bot-answers/spec.md`.

Key findings from reading the repo:

- The project `app/` directory currently has only `config.py`, `llm.py`, `medcard.py`, `markers.py`, `web.py`. There is NO `app/bot.py`, `app/ask.py`, or `app/charts.py` yet. So this step is a clean CREATE of three files, not a reconcile/merge — there are no existing project versions of these three files to diverge from.
- The reference solution at `steps/06-bot-answers/solution/app/{bot.py,ask.py,charts.py}` is already written against the exact same APIs the current project exposes. Each dependency the solution uses already exists in the project:
  - `config.TELEGRAM_BOT_TOKEN`, `config.OWNER_FILE`, `config.GARMIN`, `config.RECORD` — all present in `app/config.py`. No config change needed.
  - `llm.ask(prompt, system=..., schema=...)` — signature in `app/llm.py` matches exactly what `ask.py` calls.
  - `medcard.load()` — present in `app/medcard.py`, returns the parsed `data/health-record.json`.
  - Data shape: `data/health-record.json` has `biomarkers[]` each with `key`, `name`, `unit`, `ref`, `low`, `high`, and `series[]` of `{date, value, flag, ...}` — exactly what `ask.py` (`by_key = {b["key"]: b ...}`) and `charts.py` (`b["series"]`, `b["low"]`, `b["high"]`, `b["ref"]`, `b["unit"]`, `p["flag"]`, `p["value"]`, `p["date"]`) consume.
  - `data/garmin.json` has top-level `norms` and `days[]` keys — matches `ask.py`'s `_garmin_brief` (`g.get("days") or g.get("daily")`, `g.get("norms")`).
- `run.py` already wires these files up: in default and `bot` modes it does `import bot` (falls back to page-only on ImportError) and calls `bot.run()`; in `ask` mode it does `import ask` / `import charts`. **No change to `run.py` is required** — confirmed by reading `run.py` lines around `import bot`, `args[:1] == ["ask"]`, and `args[:1] == ["bot"]`.

### Design decisions (made here, grounded in the above)

1. **Copy the reference solution verbatim into `app/`.** Rationale: the three solution files are the accumulated-over-iterations intended final state and already target the project's real `config`/`llm`/`medcard` APIs and the real data shape. Rewriting them would only risk drift from the spec. So the implementation is: create each of the three `app/` files with the content of its `steps/06-bot-answers/solution/app/` counterpart.
2. **Do NOT change `run.py` or `config.py`.** Rationale: both already provide everything the three new files need (verified by reading both files). The task says touch `run.py` only if strictly required — it is not.
3. **Keep Pillow (`from PIL import ...`) in `charts.py` as-is.** Rationale: the spec explicitly names Pillow as the one allowed non-stdlib dependency; it is a SYSTEM package (`python3-pil`) on the workshop server, NOT a pip dependency to add. `bot.py` already imports `charts` lazily inside a `try/except ImportError` so a machine without Pillow degrades to text-only. Do not strip PIL out, and do not add it to any requirements file.
4. **Scope.** Only create files under `app/`. Do not touch `.env`, `dashboard/`, `data/`, `medcard/`, or deploy to the server (orchestrator deploys later).

### Rules that must be preserved (already encoded in the solution — verify they survive the copy)

- SI units; never fabricate values (`ask.py` only passes real medcard JSON to the model and maps `charts` keys back to real biomarker objects — it cannot invent series).
- No diagnoses / no treatment prescriptions — enforced by the `SYSTEM` prompt in `ask.py`.
- Answers to the user in Russian, plain language, 2–6 short lines — enforced by the `SYSTEM` prompt.
- Token never printed/committed — `bot.py` reads `config.TELEGRAM_BOT_TOKEN` and never logs it; `.env` is untouched.

## Steps

- [ ] 1. Create `app/charts.py` with the exact content of `steps/06-bot-answers/solution/app/charts.py`.
      Pillow-based PNG renderer: `render(biomarkers)` stacks one ~520px panel per biomarker (max 4, enforced by `ask.py`); each panel draws the marker name, a status line ("сейчас X ед — выше/ниже/в норме · норма …"), green normal-range band, blue line, colored dots by flag (green/red/orange) with value labels, and year ticks on the X axis. Y-axis rules: by values, show a reference bound only if near the data, minimum 20% spread (prevents flat/exploded charts). Keep `from PIL import Image, ImageDraw, ImageFont` and the `FONT_PATHS`/`BOLD_PATHS` fallbacks — do NOT remove Pillow.
      Files: `app/charts.py`
      Verify: `python -c "import sys; sys.path.insert(0,'app'); import charts"` from the project root prints nothing and exits 0. (If Pillow is absent on this machine this import raises `ImportError: No module named PIL` — that is expected and acceptable; the server has `python3-pil`. In that case confirm the file is syntactically valid instead with `python -c "import ast; ast.parse(open('app/charts.py',encoding='utf-8').read())"`.) Use `python3` if `python` is absent.

- [ ] 2. Create `app/ask.py` with the exact content of `steps/06-bot-answers/solution/app/ask.py`.
      `answer(question, chat_id=None)` builds model context = `{today, medcard.load(), garmin brief (norms + last 30 days)}`, prepends up to the last 3 reply-pairs from the in-memory `HISTORY` dict, calls `llm.ask(prompt, system=SYSTEM, schema=SCHEMA)` where `SCHEMA` is `{text, charts}`, records the exchange in `HISTORY`, then maps the returned `charts` keys back to real biomarker objects via `by_key` (capped at 4). `SYSTEM` carries the four question-type rules, the no-diagnosis/no-prescription rule, Russian/plain-language/2–6-lines formatting, human-readable dates, and `**bold**`-only markup. Keep the `prefix` built outside the f-string (Python 3.10 compatibility note in the source).
      Files: `app/ask.py`
      Verify: `python -c "import sys; sys.path.insert(0,'app'); import ask; assert hasattr(ask,'answer')"` exits 0 (imports `config`, `llm`, `medcard`, all present). Use `python3` if `python` is absent.

- [ ] 3. Create `app/bot.py` with the exact content of `steps/06-bot-answers/solution/app/bot.py`.
      Stdlib-only Telegram client over the HTTP API via `urllib`: `run()` long-polls `getUpdates` (`timeout=25`, socket wait 40s) and dispatches messages. Owner handling: the first user to send `/start` is recorded in `config.OWNER_FILE` (`is_owner`); others are ignored. `/start` replies with the welcome text. Each question is answered in a daemon thread (`reply_text`) so the poller never blocks; while the model thinks, a `Working` helper posts "🔎 Смотрю медкарту…", keeps sending the "typing" chat action every 4s, and deletes the status message when done. `to_html` converts `**bold**` to `<b>` and HTML-escapes the rest (so "< 5.2" never breaks markup). If `ask.answer` returns chart keys, `charts.render` builds one PNG sent via multipart `sendPhoto` (text as caption when short, else a separate `sendMessage`); `charts` is imported lazily inside `try/except ImportError` so missing Pillow degrades to text-only. Reads `config.TELEGRAM_BOT_TOKEN`; prints a friendly notice and returns if the token is empty. Never log the token.
      Files: `app/bot.py`
      Verify: `python -c "import sys; sys.path.insert(0,'app'); import bot; assert hasattr(bot,'run')"` exits 0. Use `python3` if `python` is absent.

- [ ] 4. Confirm `run.py` and `config.py` need no changes.
      Re-read `run.py` to confirm it already does `import bot` (default/`bot` modes) and `import ask`/`import charts` (`ask` mode) with the correct fallbacks, and `config.py` already defines `TELEGRAM_BOT_TOKEN`, `OWNER_FILE`, `GARMIN`, `RECORD`. Make NO edits unless a genuine gap is found; if a gap is found, make the smallest possible change in `run.py` only and record why.
      Files: none expected (read-only confirmation).
      Verify: covered by step 5.

- [ ] 5. Run the project's own settings check and the import smoke-check.
      Files: none.
      Verify: from the project root run `python run.py check` (fall back to `python3 run.py check` if `python` is absent). Expected: it prints Python version OK (3.10+), the OpenAI-key line, the Telegram-bot line (bot token from `.env` — `@<username> — работает` if the token/network are valid, otherwise a "НЕ работает"/"не вписан" line, which is acceptable here since we must not depend on live network/token), and the page/port line, without tracebacks. Then run the import smoke-check `python -c "import sys; sys.path.insert(0,'app'); import bot"` (or `python3`): expected exit 0 with no output. If this machine lacks Pillow, `import bot` still succeeds because `bot` imports `charts` lazily; a failure here that mentions `PIL` would indicate an accidental top-level PIL import in `bot.py` and must be fixed. Clean up any `chart.png` or temp files if created.

## Notes / assumptions

- Verification cannot exercise the live Telegram or OpenAI round-trip here (no guarantee of network/valid token on the build machine, and we must not deploy). The real end-to-end check from the spec (`/start` then "как менялся мой холестерин?") happens on the workshop server after the orchestrator deploys. The import smoke-check plus `run.py check` are the strongest offline verifications available and are sufficient to confirm the code loads and wires up correctly.
- Primary interpreter on this machine is `python` (3.14.7); `python3` also resolves. Commands list `python` first with `python3` as the documented fallback, matching the task's "try `python` if `python3` is absent" guidance in reverse for this environment.
- Stop-contract: this plan is implemented by the existing workflow loop, which writes `.agents/tasks/review.json` with jsonPath `verdict` = `APPROVED`. No workflow restructuring was done — the work is a single coherent unit (three drop-in files against already-present APIs) and does not decompose into separable features.
