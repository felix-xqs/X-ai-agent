# Original-content planner: mock default, optional model generation

Fork of [hireshBrem/X-ai-agent](https://github.com/hireshBrem/X-ai-agent).
This version replaces the automatic-reply demo with a **manual local planner and
simulated publication queue**. It never connects to X. Mock mode is the default
and needs no secrets or network. Optional `openai-compatible` mode sends one request
to a model endpoint you configure. Neither mode enables real publication. No package
installation, Browserbase account, X credentials, cookies or background service are needed.

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
| `provider` | `mock` (default) or `openai-compatible` |
| `model_config` | Required only for `openai-compatible`; fields below |

The mock provider uses deterministic original templates; it does not retrieve or
copy posts, call an LLM, fact-check claims, or guarantee novel wording. It is meant
for validating the workflow. Changing language and style changes the templates.
Unknown configuration fields are rejected, including inline credentials or live publishing
settings. All timestamps are stored in UTC. Stored drafts retain their topic,
language, style and schedule even if you later edit the JSON file; model settings
and the API key are not persisted.

## Custom model integration (optional, no real endpoint tested)

`planner.example.json` remains fully offline. For future model use, copy
`planner.model.example.json` to your own local configuration and change the Base URL
and model name. Its `.invalid` domain is a deliberate placeholder, not a working
service. Configure the named environment variable privately on your own machine;
do not paste a key into chat or put it in the JSON, CLI arguments or repository.
This implementation was validated **only with mocked HTTP and synthetic keys**;
no real credentials were read and no real model requests were made during development.

| `model_config` field | Meaning / bounds |
| --- | --- |
| `base_url` | API base including the version path, e.g. `https://your-host/v1`; appends `/chat/completions` |
| `model` | Your endpoint's chat model name, 1–200 characters |
| `api_key_env` | Environment-variable **name** to read only when generating; its value becomes the Bearer header |
| `timeout_seconds` | Socket/connect/read inactivity timeout, 1–120 seconds, default 30 |
| `max_tokens` | Output-token limit, integer 64–4096, default 1024 |
| `token_parameter` | Sends the limit as `max_tokens` (default) or `max_completion_tokens` |
| `temperature` | 0–2, default 0.7; `null` omits the parameter if the model does not support it |

Once you independently configure a compatible endpoint and its environment variable,
these commands use it (they were **not** run against a real service here):

```bash
python3 -m server --db .local/model.sqlite3 plan --config .local/my-model.json
python3 -m server --db .local/model.sqlite3 status
python3 -m server --db .local/model.sqlite3 dry-run --at 2030-01-02T00:00:00Z
```

Only `plan` in explicit model mode can call the endpoint. Preflight validates without
generation; a valid `plan` makes exactly one request, with no automatic retry or
fallback to mock. Topic, language, style and count are sent; the API key is sent only
as Authorization. Scheduling metadata and existing queued posts are not sent.
`dry-run`, `status`, `logs`, `pause`, `resume` and `retry` never call the model or read
its key. Re-running `plan` in model mode makes another request before checking
content fingerprints, so it can incur provider usage even when drafts are duplicates.

The supported subset is **Bearer-authenticated, non-streaming Chat Completions**:
`POST <base_url>/chat/completions` with system/user text messages, `n: 1`,
`stream: false`, a bounded token field and optional temperature. It requires one
`choices` entry with `finish_reason: "stop"`, `message.role: "assistant"` and a
string `message.content` containing only `{"posts": ["draft", "draft"]}` with exactly
the requested count. JSON mode/structured-output support is not required or sent.
The prompt asks for JSON; the parser enforces the format.

This does **not** imply every vendor or model works. Responses API, native Anthropic
or Gemini APIs, Azure-specific authentication/query parameters, streaming, tools,
multimodal content and reasoning-only output are unsupported. Some models reject
system messages, temperature, `n` or either token field. Choose the documented token
field and omit temperature as needed; other incompatible request formats need an
adapter change. OpenAI's [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat)
also notes model-specific parameter support and the replacement of `max_tokens`
with `max_completion_tokens`. No provider/model compatibility has been verified live.

Safety and failure behavior:

- Only HTTPS is accepted, except HTTP to `localhost`, `127.0.0.1` or `::1` for local
  model servers. Inline URL credentials, query strings, fragments and known X domains
  are rejected. Treat the configured endpoint as trusted: it receives the prompt and
  Bearer key. The key is not copied into the prompt.
- Redirects are refused and proxy environment variables are ignored. TLS verification
  stays enabled. Custom headers, authentication schemes and certificate overrides are
  not supported. The timeout is socket inactivity, **not a guaranteed total wall-clock
  deadline**; a server that keeps sending data can take longer.
- Responses are capped at 64 KiB. Non-200 status, timeouts, connection errors, refusals,
  incomplete output, tool calls, malformed/duplicate-key JSON or invalid drafts reject
  the entire batch before any post is inserted. A draft must be a nonempty single-line
  string of at most 280 Unicode code points, without control/surrogate characters
  or Unicode line separators;
  normalized duplicates within the batch and exact key echoes are rejected. This is
  not X's weighted character validation or semantic content moderation.
- API keys, raw response bodies, request headers, endpoint URLs and exception details
  are omitted from generation errors/events. Provider failures produce a sanitized
  `generation_failed` event and exit code 2; existing posts and pause state are unchanged.
  Inspect the endpoint configuration yourself, then invoke `plan` again if appropriate.
  Generated drafts and queue receipts remain local plaintext. Models may still produce
  inaccurate or inappropriate content; inspect drafts with `status` before simulation.

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
pause/resume/retry, rollback, CLI exit codes and retired browser paths. Provider tests
inspect requests through a mocked HTTP opener, using synthetic environment values;
they cover response validation, size limits, redaction, credential isolation, redirect
refusal, timeouts, HTTP errors and a single request per plan. Real socket connections
are blocked throughout both test suites. No upstream repository scripts,
package installers or browser automation are run.

## Architecture and limitations

The source combined a Next.js 15 client with a FastAPI backend that used Browser-use,
Browserbase and LangChain to log in and reply. After inspecting that path, this
prototype retains the Python server directory and replaces the execution entry
point with a dependency-free CLI. `server/planner.py` owns validation, mock generation,
SQLite persistence and the simulator; `server/providers.py` owns optional HTTP generation
and output validation, and `server/errors.py` shares public errors. The test files verify
both the workflow and the provider contract.

This is a small workflow prototype: optional model integration is unverified against
real services; there is no graphical queue editor, real publishing adapter,
X character-weight validation, semantic deduplication,
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
