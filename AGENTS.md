# StratusScan-Azure Agent Guide

This repo follows the cross-provider StratusScan product contract in
`stratusscan-philosophy.md`. Read that file before proposing or making product
changes. `CLAUDE.md` contains the Azure-specific implementation guide and should
be treated as authoritative for local architecture.

## Product Boundaries

- StratusScan is a terminal-based, menu-driven inventory exporter.
- It is not a monitoring system, cost-management platform, security scanner,
  web app, API server, daemon, or background service.
- It must remain read-only against cloud accounts. Never add resource creation,
  modification, or deletion.
- Output is Excel workbooks (`.xlsx`) for human review, filtering, sharing, and
  audit evidence.
- Cloud Shell compatibility is a primary requirement. Keep runtime dependencies
  minimal and pip-installable in a fresh Azure Cloud Shell session.
- Public and US Government cloud support are first-class. Detect cloud context
  from the active Azure environment and skip unavailable services gracefully.

## Azure Architecture Rules

- `stratusscan_azure.py` is a thin terminal menu and subprocess launcher.
  It must not call Azure APIs directly.
- Each exporter in `scripts/` must run independently via
  `python scripts/<name>.py`.
- Shared code lives in `sslib/` and must not print to the console. Use
  module-scoped `logging` and return structured data.
- Only CLI entry points, `configure.py`, and exporter scripts may print user
  messages.
- Always get credentials through `sslib.auth.get_credential()`.
- Call `quiet_azure_loggers()` near the start of exporter `main()` functions.
- Use `detect_cloud()`, `graph_scope_for_cloud()`, and `arm_client_kwargs()` for
  cloud-aware Azure SDK and Microsoft Graph access.
- Load scan scope from `config.json` via `load_config()` and
  `filter_subscription_ids()`.
- Export files through `make_filename()` and `save_dataframes()` only. Do not
  hardcode output paths or filenames.
- Each workbook should put a `Summary` sheet first, with row counts and
  per-scope errors recorded as rows instead of crashing the whole export.
- Put `Tags` last in row schemas.

## Naming And Style

- Script filenames use `lowercase_underscored.py`; never hyphens.
- Output filenames follow the repo helper convention:
  `{SCOPE}-{exporter}-{suffix}-export-{MM.DD.YYYY}.xlsx`.
- Tenant and subscription labels come from config mappings, never hardcoded.
- Keep comments sparse. Prefer clear names; add comments only for non-obvious
  constraints or SDK behavior.
- Follow the existing `ruff` and `black` configuration.

## Scope Guardrails

Do not introduce:

- Web UIs, local web servers, API servers, or persistent services.
- Live pricing API calls during export runs. Use committed static reference data
  only when pricing estimates are supported.
- Proprietary or compiled runtime dependencies.
- Credentials in code, templates, docs, or committed config.
- Multi-CSP dispatch logic inside this Azure repo. Shared philosophy is fine;
  shared runtime code is not.
