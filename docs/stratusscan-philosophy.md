# StratusScan — Product Philosophy & Boundaries

**Audience:** All agents and contributors working on any StratusScan implementation
**Scope:** CSP-agnostic. Applies to `stratusscancli-aws`, `stratusscancli-azure`, and any future provider port.

---

## What StratusScan Is

A terminal-based, menu-driven CLI that exports cloud resource inventories to Excel workbooks. Built for infrastructure auditors, compliance teams, and cloud admins who need a complete, human-readable snapshot of what is deployed — no scripting knowledge required.

It is not a monitoring system, cost management platform, or security scanner. It is an inventory exporter.

---

## Core Principles

### 1. Terminal Only

No web UI, no daemon, no background service, no API server. Runs in a terminal, does its work, exits. Must work in the most constrained environments: cloud shell sessions, locked-down contractor workstations, CI/CD pipelines.

### 2. Menu Driven

Primary interaction is a numbered, hierarchical terminal menu. Every user action reachable within two or three keystrokes.

- Top-level: categories (compute, network, storage, etc.) and meta-actions (run all, smart scan, configure)
- Sub-menus: individual exporters within a category
- Navigation: `[B]` back, `[Q]` quit, `[X]` return to main
- Status panels: box-drawing characters (`+--+` / `|` / `+--+`)
- Indicators: checkmark ok, x error, warning, unknown

### 3. Cloud Shell First

A user who has never run StratusScan should authenticate, run the tool, and have a populated workbook in five minutes — without reading documentation.

The install path is `pip install` in a fresh cloud shell session with zero extra setup. If a dependency is not available in the CSP's built-in shell, reconsider it. Complexity lives inside the implementation, not the interface.

### 4. Read-Only, Minimal Permissions

StratusScan never writes, modifies, deletes, or provisions cloud resources. Every exporter must fail gracefully on permission denied — skip and log, never crash. IAM/RBAC policies live in `policies/`.

Runtime dependencies: CSP SDK, `pandas`, `openpyxl`, `python-dateutil`, `questionary`. No build tools, no compiled extensions, no running services.

Dev dependencies (`pytest`, `ruff`, `black`, `mypy`, mocking libraries) install only via `[dev]` extras.

### 5. One Exporter Per Resource Type, One Workbook Per Exporter

The goal is completeness. Every service the CSP offers that a typical enterprise uses should have an exporter. Coverage gaps are bugs.

Output is always `.xlsx`:
- Universally readable, filterable, sortable
- Shareable with non-technical stakeholders
- Printable for evidence packages (FedRAMP, SOC 2, etc.)

Each exporter script is independently runnable. Each produces one workbook. Related data can occupy multiple sheets within that workbook, but resources are **grouped by type, not piled into one massive spreadsheet**. A subscription/account column identifies source scope.

---

## Package Structure

```
stratusscancli-{csp}/
  stratusscan.py            # Main entry — menu, navigation, subprocess launcher
  configure.py              # Interactive configuration wizard
  utils.py                  # Shared library: client factory, logging, Excel helpers, config
  pyproject.toml            # Package metadata and dependencies
  config.json               # Runtime config (gitignored, auto-created from template)
  config-template.json      # Committed template; never contains real credentials
  scripts/                  # One .py per exporter, organized by category
    smart_scan/             # Service discovery — detect what's in use, run relevant exporters
  output/                   # All .xlsx exports land here (gitignored)
  logs/                     # Runtime logs with auto-cleanup (gitignored)
  policies/                 # Read-only IAM/RBAC policy documents
  reference/                # Static pricing data and lookup tables
  tests/                    # pytest suite; mirrors scripts/ structure
```

`stratusscan.py` is the only orchestrator. It presents the menu, collects input, and launches exporters as subprocesses. It never calls cloud APIs directly. Every exporter runs independently from the command line.

`utils.py` is the shared library. It must not print to the console. It provides the client factory, logging setup, Excel output functions, config I/O, and environment detection.

---

## Smart Scan

Smart Scan is a service discovery engine. It queries the environment to determine which services are actually in use, then runs only the relevant exporters. In AWS this uses a services-in-use export; Azure may use Resource Graph or similar. The pattern is the same: discover, confirm with user, execute.

Lives at `scripts/smart_scan/` as a package.

---

## Pricing Data

Exporters may include estimated cost columns where pricing data is available.

- Pricing data lives in `reference/` as committed files
- AWS: static JSON lookup tables, refreshed quarterly, no live API calls at runtime
- Azure: approach TBD — may use Azure CLI commands or Retail Prices API to populate reference data
- If pricing data is unavailable for a resource type, omit the column — never show zeros or errors
- Label clearly: `Estimated Monthly Cost (USD)`, note figures are on-demand rates
- Best-effort. Absence never blocks an export.

---

## Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Script filenames | `lowercase_underscored.py` | `virtual_machines_export.py` |
| Output filenames | `{SCOPE-NAME}-{resource-type}-{suffix}-export-{MM.DD.YYYY}.xlsx` | `PROD-SUB-virtual-machines-all-export-05.19.2026.xlsx` |
| Config keys | `lowercase_underscored` | `default_subscription_id` |
| Date format | `MM.DD.YYYY` | `05.19.2026` |
| Commit messages | Conventional Commits | `feat(network): add NSG rule export` |

Script filenames use underscores, never hyphens. Hyphens break Python imports.

Scope name (account name / subscription name) in filenames comes from config mappings, never hardcoded. Fall back to the raw ID if no mapping exists.

---

## Headless / CI Mode

Environment variables suppress interactive prompts for CI/CD:
- `{CSP}SCAN_AUTO_RUN=1` — bypass all interactive prompts
- AWS: `STRATUSSCAN_REGIONS=us-east-1,us-west-2`
- Azure: `AZURESCAN_SUBSCRIPTIONS=sub-id-1,sub-id-2`

CLI flags (v0.2.0+): `--version`, `--dry-run`, `--verbose`, `--help`. When no flags are passed, fall through to the interactive menu.

---

## Government Cloud

Government cloud support is first-class, not an afterthought. Gov accounts are primary customers for inventory and compliance tooling.

- Detect partition/environment from the authenticated session — not from user config
- Inject compliance endpoints (FIPS, gov ARM URLs) automatically
- Guard exporters for unavailable services: skip gracefully, log reason, exit 0
- Maintain separate policy documents for commercial and government permission sets

---

## What Does Not Belong

- **Resource modification.** Read-only, always. PRs that write to cloud accounts are rejected.
- **Real-time monitoring.** Point-in-time snapshots only.
- **Web UI or API server.** Terminal only.
- **Proprietary dependencies.** Open source and pip-installable only.
- **Credentials in code or config templates.** Credentials come from the CSP's standard chain.
- **Cross-CSP runtime logic.** Each CSP gets its own repo and `utils.py`. Shared philosophy, not shared code.
