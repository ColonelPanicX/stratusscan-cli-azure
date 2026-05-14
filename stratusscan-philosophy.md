# StratusScan — Product Philosophy & Boundaries

**Audience:** Claude Code agents working on any StratusScan implementation  
**Scope:** CSP-agnostic. Applies to `stratusscan-cli` (AWS), `stratusscan-cli-azure` (Azure), and any future cloud provider port.

---

## What StratusScan Is

StratusScan is a terminal-based, menu-driven CLI tool that exports cloud resource inventories to spreadsheets. It targets infrastructure auditors, compliance teams, and cloud administrators who need a complete, human-readable snapshot of what is deployed in a cloud account — with no prior scripting knowledge required.

The tool is deliberately not a monitoring system, a cost management platform, or a security scanner. It is an inventory exporter. It captures the current state of cloud resources and hands the user a workbook they can read, filter, and share without touching a terminal again.

---

## Core Principles

### 1. Terminal Only

StratusScan has no web UI, no daemon, no background service, and no API server. It runs in a terminal, does its work, and exits. The user's interaction surface is the interactive menu or CLI flags — nothing else.

This is intentional. The tool must work in the most constrained environments: a cloud provider's own browser-based shell (AWS CloudShell, Azure Cloud Shell), a locked-down contractor workstation, or a CI/CD pipeline with no GUI. If it requires a browser, a local web server, or persistent state beyond a config file, it does not belong here.

### 2. Menu Driven

The primary interaction model is a numbered, hierarchical terminal menu. Users navigate by typing a number or letter — no prior knowledge of the tool's internals required. Every action a human user might want should be reachable from the main menu within two or three keystrokes.

Menu design rules:
- Top-level menu launches categories (compute, networking, storage, etc.) or meta-actions (run all, smart scan, configure)
- Sub-menus list individual exporters within a category
- Navigation keys are consistent: `[B]` back, `[Q]` quit, `[X]` return to main menu
- Status panels use box-drawing characters (`╔═╗ / ║ / ╚═╝`) at the top of each screen
- Section dividers use `═══` with ALL-CAPS labels
- Status indicators: `✅` ok, `❌` error, `⚠️` warning, `❓` unknown
- Numbered options for content items `[1][2][3]`; letter keys for navigation

The menu is the face of the tool. Keep it clean, consistent, and predictable.

### 3. Simplicity and Ease of Use

A user who has never run StratusScan before should be able to authenticate to their cloud account, run the tool, and have a populated spreadsheet in their output directory inside five minutes — without reading documentation.

Complexity lives inside the implementation, not the interface. If a design choice makes the menu harder to navigate, the install longer, or the output less readable, it is the wrong choice.

Corollary: do not add features that require the user to understand StratusScan internals. Configuration should be guided (interactive wizard). Errors should be human-readable. Output filenames should be self-describing.

### 4. Bare Minimum Permissions and Dependencies

**Permissions:** StratusScan requires only read-only access to the cloud account. It never writes, modifies, deletes, or provisions resources. Every exporter must fail gracefully when a permission is denied — skip and log, never crash. IAM/RBAC policies for each permission tier live in `policies/` and are maintained alongside the tool.

**Runtime dependencies:** Keep them minimal. The install path is `pip install` (or the CSP equivalent) in a fresh cloud shell session with no extra setup. As of the AWS implementation:
- Runtime: `boto3` (or CSP SDK equivalent), `pandas`, `openpyxl`, `python-dateutil`, `questionary`
- No build tools, no compiled extensions, no services that must be running

If a proposed dependency is not available in the CSP's built-in shell environment, reconsider it. If it is available but adds significant install size for marginal value, reconsider it.

**Dev dependencies** (pytest, ruff, black, mypy, moto/equivalent) are installed only via the `[dev]` extras group and never bleed into runtime.

### 5. Capture Everything, Export to Spreadsheets

The goal is completeness. Every service the cloud provider offers that a typical enterprise account might use should have an exporter. Coverage gaps are bugs, not missing features.

Output format is always Excel (`.xlsx`). Reasons:
- Universally readable without additional tooling
- Supports multiple sheets per workbook (logical grouping of related resources)
- Filterable, sortable, and shareable by non-technical stakeholders
- Printable for physical evidence packages (FedRAMP, SOC 2, etc.)

One service = one exporter script. One exporter = one or more sheets in one workbook. Related services may share a workbook (e.g., a networking workbook with VPCs, subnets, route tables, and security groups), but individual exporters remain independently executable.

---

## Package Structure

Every StratusScan implementation follows this layout:

```
stratusscan-cli-{csp}/
├── {csp}scan.py              # Main entry point — menu, navigation, subprocess launcher
├── configure.py              # Interactive configuration wizard
├── utils.py                  # Shared library: client factory, logging, Excel helpers, config
├── pyproject.toml            # Package metadata and dependency declarations
├── config.json               # Runtime config (auto-created from template on first run)
├── config-template.json      # Committed template; never contains real credentials
├── scripts/                  # One .py file per exporter (plus smart_scan/ package)
│   ├── ec2_export.py         # Example: individual exporter
│   ├── smart_scan/           # Optional: automated discovery + batch execution package
│   └── ...
├── output/                   # All exported .xlsx files land here (gitignored)
├── logs/                     # Runtime logs (gitignored)
├── policies/                 # Read-only IAM/RBAC policy documents
├── reference/                # Static pricing data and lookup tables (JSON)
└── tests/                    # pytest suite; mirrors scripts/ structure
```

`{csp}scan.py` is the only orchestrator. It presents the menu, collects user input, and launches exporters as subprocesses. It never calls cloud APIs directly — all cloud interaction is delegated to exporter scripts. This means every exporter is independently runnable from the command line for debugging or CI use.

---

## Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Script filenames | `lowercase_underscored.py` | `ec2_export.py` |
| Output filenames | `{ACCOUNT-NAME}-{resource-type}-{suffix}-export-{MM.DD.YYYY}.xlsx` | `acme-ec2-instances-export-05.11.2026.xlsx` |
| Config keys | `lowercase_underscored` | `default_regions` |
| Directory names | `lowercase-hyphenated` | `smart_scan/`, `session-summaries/` |
| Date format | `MM.DD.YYYY` | `05.11.2026` |
| Commit messages | Conventional Commits | `feat(exporters): add lambda export` |

**Script filenames must use underscores, not hyphens.** Hyphens break Python imports. This is non-negotiable.

Account name in output filenames comes from the config's account mapping, never hardcoded. If no mapping exists, fall back to the account/subscription ID.

---

## Pricing Estimates

Where pricing data is available as a static reference (JSON lookup tables keyed by instance type, region, and tier), exporters should include estimated monthly cost columns. This gives the workbook immediate value to cost optimization reviews without requiring any live pricing API calls at runtime.

Rules:
- Pricing data lives in `reference/` as JSON files, committed to the repo
- Refresh pricing data approximately quarterly
- Never call a live pricing API during an export run — static lookups only
- If pricing data is unavailable for a resource type, omit the column entirely rather than showing zeros or errors
- Label cost columns clearly: `Estimated Monthly Cost (USD)` with a note that figures are on-demand rates and may differ from actual billing

Pricing data is best-effort. Its absence never blocks an export.

---

## Headless / CLI Flag Operation

Power users, CI pipelines, and automated compliance runs need to drive StratusScan without a human at the keyboard. The tool must support this without requiring workarounds.

**Environment variable layer (always present):**
- `{CSP}SCAN_AUTO_RUN=1` — suppresses all interactive prompts inside exporters; scripts use defaults or error out cleanly
- `{CSP}SCAN_REGIONS=us-east-1,us-west-2` — sets target regions non-interactively

**CLI flag layer (Layer 2, built on top of menu):**
- `--version` — print version and exit
- `--dry-run` — show what would run without executing
- `--verbose` — increase log verbosity
- `--help` — standard usage output

When no flags are passed, the tool falls through to the interactive menu as normal. CLI flags and interactive mode are not mutually exclusive — they serve different audiences on the same binary.

The CLI flag layer is a prerequisite for TUI work. Do not build the TUI before CLI flags exist.

---

## Government Cloud Support

Every StratusScan implementation must support the CSP's government cloud partition from day one — not as an afterthought. Government accounts are primary customers for inventory and compliance tooling.

Implementation rules:
- Detect the active partition/environment from the authenticated account or region, not from user configuration
- Inject any required compliance endpoints (FIPS, etc.) automatically — do not expose this as a user-facing setting
- Guard exporters for services unavailable in government partitions: skip gracefully, log the reason, exit 0
- Maintain separate `policies/` documents for commercial and government permission sets

---

## What Does Not Belong Here

To keep the scope clear:

- **No resource modification.** StratusScan never writes to the cloud account. PRs that modify, create, or delete cloud resources will be rejected.
- **No real-time monitoring.** StratusScan is a point-in-time snapshot tool. It does not watch for changes, poll APIs, or maintain persistent connections.
- **No web UI or API server.** Terminal only. Always.
- **No proprietary dependencies.** Every dependency must be open source and pip-installable. No vendor SDKs beyond the official CSP SDK.
- **No credentials in code or config templates.** `config-template.json` is committed; `config.json` is gitignored. Credentials come from the CSP's standard credential chain (environment variables, instance profiles, etc.) — never from config files.
- **No cloud-provider-specific logic in shared modules.** `utils.py` is the shared library for one CSP implementation. Do not add multi-CSP dispatch logic to it. Each CSP gets its own repo and its own `utils.py`.
