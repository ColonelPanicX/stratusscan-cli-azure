# StratusScan-Azure

[![Version: 0.1.0-alpha](https://img.shields.io/badge/version-0.1.0--alpha-blue.svg)](#)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Azure Cloud Shell](https://img.shields.io/badge/runs%20in-Azure%20Cloud%20Shell-0078D4.svg)](https://shell.azure.com)

Azure equivalent of [StratusScan-CLI](https://github.com/ColonelPanicX/StratusScan-CLI). Read-only
Azure resource inventory exporter — multi-subscription, multi-cloud, and designed
to run cleanly in **Azure Cloud Shell**.

[Quick Start](#quick-start) • [What It Captures](#what-it-captures) • [Cloud Shell](#running-in-azure-cloud-shell) • [Output](#output) • [Roadmap](#roadmap)

---

## Quick Start

```bash
# Local (already authenticated via `az login`)
git clone <repo-url> StratusScan-Azure
cd StratusScan-Azure
pip install --user azure-identity azure-mgmt-resource azure-mgmt-resourcegraph \
                   azure-mgmt-authorization azure-mgmt-policyinsights \
                   pandas openpyxl requests
python configure.py        # one-time scope + subscription mapping
python stratusscan_azure.py
```

The main menu offers each exporter individually or "Run all" to produce a full
inventory snapshot.

---

## What It Captures

StratusScan-Azure leans on **Azure Resource Graph** (one KQL endpoint that
indexes every ARM resource), then layers four targeted exporters on top to
cover what Resource Graph doesn't reach:

| Script | Source | What it covers |
|---|---|---|
| `resource_graph_export.py` | Resource Graph | Every ARM resource (VMs, storage, networks, AKS, KVs, App Service, …), Advisor recommendations, Defender for Cloud assessments, Policy compliance state, Service Health, RBAC assignments |
| `entra_id_export.py` | Microsoft Graph | Users, groups, applications, service principals, directory roles, Conditional Access policies |
| `rbac_export.py` | Authorization API | Role assignments + **custom role definitions** with full action lists per subscription |
| `policy_export.py` | Resource Manager + Policy Insights | Policy assignments, custom definitions, current compliance state with non-compliant counts |

**Multi-subscription:** All exporters discover every accessible subscription and
fan out automatically (filtered by `default_scope` in `config.json`).

**Multi-cloud:** Public, US Gov, and China clouds are detected via `az cloud show`
and Microsoft Graph endpoints are routed accordingly.

---

## Running in Azure Cloud Shell

Cloud Shell is the recommended runtime — auth is automatic and the bundled tools
match the StratusScan-AWS philosophy of "no credentials lying on disk."

```bash
# 1. Open https://shell.azure.com (Bash)
# 2. Clone and install
git clone <repo-url> StratusScan-Azure
cd StratusScan-Azure
pip install --user azure-mgmt-resourcegraph azure-mgmt-policyinsights openpyxl

# (azure-identity, azure-mgmt-resource, azure-mgmt-authorization, pandas,
#  and requests are typically preinstalled in Cloud Shell)

# 3. Run
python configure.py
python stratusscan_azure.py
```

**Persistent output:** When run inside Cloud Shell, exports go to
`~/clouddrive/stratusscan-azure/output/` so they survive session timeouts. The
contents are visible in the Storage account backing your Cloud Shell home.

**Download to local:** From Cloud Shell, `download <filename>` pushes a file to
your browser. Or `cp output/*.xlsx ~/clouddrive/` and grab them via the Storage
Explorer.

---

## Authentication

| Environment | What's used |
|---|---|
| Azure Cloud Shell | The signed-in user's token (instant — no setup) |
| Dev box | `az login` → `AzureCliCredential` |
| Azure VM / App Service | System-assigned managed identity (`DefaultAzureCredential`) |
| CI / pipelines | `AZURE_CLIENT_ID` + `AZURE_CLIENT_SECRET` + `AZURE_TENANT_ID` env vars |

Required Azure RBAC: **Reader** at the subscription scope (or higher).
Required Microsoft Graph permissions: **Directory.Read.All** equivalent for
the Entra ID exporter (most users have this via their AAD role).

---

## Output

Files land in `~/clouddrive/stratusscan-azure/output/` (Cloud Shell) or `./output/`
(elsewhere), named:

```
{TENANT}-{exporter}-{suffix}-export-{MM.DD.YYYY}.xlsx
```

Each file is multi-sheet — one sheet per Resource Graph table or Microsoft
Graph endpoint, plus a `Summary` sheet with row counts.

Same-day re-runs append `-v2`, `-v3`, … so you don't lose a previous export.

---

## Configuration

`config.json` (created by `python configure.py`) controls:

```jsonc
{
  "tenant_name": "CONTOSO",
  "subscription_mappings": {
    "00000000-0000-0000-0000-000000000000": "PROD",
    "11111111-1111-1111-1111-111111111111": "DEV"
  },
  "default_scope": {
    "mode": "all",
    "selected_subscription_ids": []
  },
  "azure_cloud": "AzureCloud"
}
```

`mode` may be `all` (every Enabled subscription) or `selected` (only IDs in
`selected_subscription_ids`).

---

## Project Layout

```
StratusScan-Azure/
├── stratusscan_azure.py       # main menu launcher
├── configure.py               # interactive setup
├── sslib/
│   ├── auth.py                # credential chain
│   ├── cloud.py               # Public/USGov/China detection + Graph endpoints
│   ├── config.py              # config.json read/write
│   ├── output.py              # output paths + xlsx writer (Cloud Shell aware)
│   └── subscriptions.py       # subscription enumeration + scope filtering
├── scripts/
│   ├── resource_graph_export.py
│   ├── entra_id_export.py
│   ├── rbac_export.py
│   └── policy_export.py
├── tests/test_smoke.py
├── pyproject.toml
└── config-template.json
```

---

## Roadmap

**v0.2 — Depth**
- Cost Management exporter (subscription + resource-group spend)
- Defender for Cloud — full alerts + recommendations (beyond what Resource Graph exposes)
- Activity Log + Diagnostic Settings audit
- Smart Scan equivalent: discover-then-export auto-orchestration
- NSG flat rule export, Storage encryption deep-dive, Key Vault access policies

**v0.3 — Scale**
- Concurrent subscription scanning (mirrors AWS-side `sslib.concurrency`)
- Management Group scope (vs. flat subscription list)
- Excel pivot-friendly resource-type sheet splits

**v1.0 — Stable**
- Textual TUI matching the AWS-side roadmap
- Per-service IAM/RBAC permission policy bundles for the Reader role

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

---

## Acknowledgments

Built alongside [StratusScan-CLI](https://github.com/ColonelPanicX/StratusScan-CLI)
(AWS). Powered by [Azure SDK for Python](https://github.com/Azure/azure-sdk-for-python),
[Azure Resource Graph](https://learn.microsoft.com/en-us/azure/governance/resource-graph/),
and [Microsoft Graph](https://learn.microsoft.com/en-us/graph/). Excel output
via [pandas](https://pandas.pydata.org/) and [openpyxl](https://openpyxl.readthedocs.io/).
