# Original-content planner: offline first version

Fork of [hireshBrem/X-ai-agent](https://github.com/hireshBrem/X-ai-agent).
This version replaces the automatic-reply demo with a **manual local planner and
simulated publication queue**. It never connects to X. No credentials, cookies,
API keys, Browserbase account, package installation or background service are needed.

## Run on this Mac

Use the existing Python 3.9+ interpreter from the repository root:

```bash
cd /Users/tu/Documents/Codex/2026-10-23/task/X-ai-agent
python3 -m server plan --config planner.example.json
python3 -m server status
python3 -m server dry-run --at 2030-01-02T00:00:00Z
python3 -m server logs
```

The example produces three Chinese drafts about sustainable AI learning habits,
with future scheduling metadata. `--at` advances **only the simulation clock** so
that the example posts are due. Without `--at`, `dry-run` uses the current UTC time
and processes only due posts. Every invocation exits; nothing runs in the background.
The default queue is `.local/planner.sqlite3` (ignored by Git). To keep experiments
separate, put `--db /path/to/queue.sqlite3` **before** the command:

```bash
python3 -m server --db .local/experiment.sqlite3 plan --config planner.example.json
```

`python3 server/main.py ...` is an equivalent entry point. There is no HTTP backend
or FastAPI `app` in this version. Run `python3 -m server --help` for commands.

## Configuration

Copy and edit `planner.example.json`:

| Field | Accepted value |
| --- | --- |
| `topic` | 1–120 characters of your own topic |
| `language` | `en` or `zh` (default `en`) |
| `style` | `concise`, `practical`, `question` (default `practical`) |
| `count` | 1–3 drafts (default 3) |
| `start_at` | ISO 8601 timestamp with offset, e.g. `2030-01-01T09:00:00+08:00`; defaults to now |
| `interval_minutes` | Integer 1–525600 (default 60) |
| `provider` | `mock` only |

The mock provider uses deterministic original templates; it does not retrieve or
copy posts, call an LLM, fact-check claims, or guarantee novel wording. It is meant
for validating the workflow. Changing language and style changes the templates.
Unknown configuration fields are rejected, including credentials or live publishing
settings. All timestamps are stored in UTC. Stored drafts retain their config and
schedule even if you later edit the JSON file.

## Queue behavior and recovery

- `plan` atomically enqueues validated drafts. A SHA-256 fingerprint of NFKC-normalized,
  case-folded text with collapsed whitespace prevents duplicates across restarts,
  schedules and statuses. It does not detect semantic similarity.
- `dry-run` simulates pending, due drafts in schedule order. Successful items become
  `simulated`, with a receipt verified against the expected ID, mode, text and hash.
  The receipt is local test evidence, **not evidence of publication on X**.
- An error or receipt mismatch marks that item `failed`, persists an error and
  pauses the entire queue before the next item. Successful earlier items stay
  simulated; later items remain pending.
- `pause` and `resume` persist the switch without processing items. `retry ID`
  returns only a failed item to pending, preserves attempt history and leaves the
  pause switch unchanged. Inspect `status` and `logs`, then explicitly resume.
- SQLite serializes writers. A run's results and events commit together; an
  unexpected exception rolls the batch back. The simulator has no external effects.

Try the failure path with a fresh queue (already simulated items do not run again):

```bash
python3 -m server --db .local/failure.sqlite3 plan --config planner.example.json
python3 -m server --db .local/failure.sqlite3 dry-run --at 2030-01-02T00:00:00Z --simulate mismatch
python3 -m server --db .local/failure.sqlite3 status
python3 -m server --db .local/failure.sqlite3 retry 1
python3 -m server --db .local/failure.sqlite3 resume
python3 -m server --db .local/failure.sqlite3 dry-run --at 2030-01-02T00:00:00Z
```

`--simulate error` tests a simulated adapter failure. Exit codes: `0` completed
(including no due items), `1` failed simulation or paused queue, `2` invalid input
or local storage error. Output is JSON. Status, attempts, receipts, errors, pause
state and event logs survive process restarts. Logs and drafts are local plaintext;
use your normal file permissions and avoid putting secrets in topics.

## Disabled capabilities

Real posting, login, replies, DMs, likes, cookies, browser context persistence and
external browser services are disabled. `DisabledPublisher` always raises; no
configuration or environment variable can enable real publishing. The CLI only
constructs `Simulator`. The old Python browser helpers fail closed, and all three
Next.js Browserbase endpoints return HTTP 410 without loading an SDK. The old
client homepage is replaced with a retirement notice and CLI instructions. Google
font loading was removed from its layout.

The retained Next.js component tree and lockfiles are upstream reference code;
this prototype does not use or install them. The client has not been built or
validated as a supported app. Do not use the old installation/login instructions.
The historical README is preserved in [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)
for attribution and architecture context only. No scheduler, launch agent, cron
entry, network listener, live deployment or automatic retry is created.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The standard-library suite covers configuration, both languages and all styles,
timezones and due boundaries, persistent deduplication, verified receipts, errors,
pause/resume/retry, rollback, CLI exit codes and retired browser paths. Network
connections are blocked during queue tests. No upstream repository scripts,
package installers or browser automation are run.

## Architecture and limitations

The source combined a Next.js 15 client with a FastAPI backend that used Browser-use,
Browserbase and LangChain to log in and reply. After inspecting that path, this
prototype retains the Python server directory and replaces the execution entry
point with a dependency-free CLI. `server/planner.py` owns validation, mock generation,
SQLite persistence and the simulator; `tests/test_planner.py` verifies the workflow.

This is a small workflow prototype: no graphical queue editor, real LLM provider,
real publishing adapter, X character-weight validation, semantic deduplication,
content review/approval state, migrations or background scheduling. The timestamp
is metadata for manual dry-runs. Receipts verify only local simulation consistency.

## Licenses and attribution

The original [LICENSE](LICENSE) and [client/LICENSE](client/LICENSE) are unchanged.
The root notice names Hiresh Bremanand; the client carries Agno's MIT notice.
The root license heading says “Version 1, 29 March 2025” while its body specifies
GNU GPL version 3 or later. This fork preserves that upstream wording and does not
attempt to resolve the inconsistency. New Python prototype code is marked
GPL-3.0-or-later, following the version stated in the upstream license body.
See [NOTICE.md](NOTICE.md) for the modification record.
