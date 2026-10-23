# Attribution and modification record

Upstream: https://github.com/hireshBrem/X-ai-agent

- Root copyright notice: Copyright (C) 2025 Hiresh Bremanand.
- Client copyright notice: Copyright (c) 2025 Agno, MIT License.
- Original LICENSE and client/LICENSE are retained verbatim.
- Historical README is retained at docs/UPSTREAM_README.md.

Modified on 2026-10-23 for felix-xqs: replaced the browser automation backend entry
point with an offline original-content planner, local SQLite queue and simulated
publication verification; disabled the browser/login/reply helpers and client
browser endpoints; retired the old client homepage; removed tracked Python bytecode;
added tests, sample configuration and instructions. No real X interactions or
background scheduler are implemented or enabled.

The upstream root license heading and body name inconsistent GPL versions; its
wording is preserved. New Python prototype code follows GPL-3.0-or-later, as stated
in the original license body. The client retains its separate MIT notice.

Additional modification on 2026-10-23: added an opt-in OpenAI-compatible text
Chat Completions provider with validated configuration, bounded requests/responses,
credential-safe errors, strict draft validation, mocked transport tests and a model
configuration example. Mock generation remains the default; X interactions and
background execution remain disabled. No real model calls were made in development.
