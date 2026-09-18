# StratusScanCLI-Azure

[![Version: 0.1.0](https://img.shields.io/badge/version-0.1.0--alpha-red.svg)](#project-status)
[![Status: Pre-Alpha](https://img.shields.io/badge/status-pre--alpha-red.svg)](#project-status)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Azure Public](https://img.shields.io/badge/Azure-Public%20Cloud-0078D4.svg)](https://portal.azure.com)
[![Azure Government](https://img.shields.io/badge/Azure-US%20Government-blue.svg)](https://portal.azure.us)

---

> [!WARNING]
> **This project is under heavy, active development and is not ready for general use.**
>
> APIs, output formats, and script interfaces may change without notice between commits.
> No guarantees of stability, correctness, or completeness are made at this stage.
> **Do not use this in production environments until a stable release is cut.**
>
> Track progress toward the first release on the [dev branch](https://github.com/ColonelPanicX/stratusscan-cli-azure/tree/dev).
> All development happens on `dev`. `main` is reserved for release snapshots only.

---

A Python CLI tool for exporting Azure resource inventories to Excel workbooks. 75 exporters across Public and US Government cloud environments, targeting infrastructure audits, FedRAMP evidence collection, and cost analysis.

Sibling project to [StratusScan-CLI (AWS)](https://github.com/ColonelPanicX/StratusScan-CLI). Shares the same philosophy, output format, and architectural patterns — not a fork.

---

## Quick Start

### Azure Cloud Shell (recommended)

The tool is designed to work in a fresh [Azure Cloud Shell](https://shell.azure.com) session with no extra setup. Credentials are injected automatically, and `configure.py` / `stratusscan.py` install their own dependencies on first run.

```bash
git clone https://github.com/ColonelPanicX/stratusscan-cli-azure.git
cd stratusscan-cli-azure
python stratusscan.py
```

On first run with no config, StratusScan auto-detects the Azure cloud (public vs
government) and discovers every accessible subscription — no setup step required.
Run `python configure.py` only if you want to **narrow** to specific subscriptions
or persist a choice.

### Local Machine

Requires [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) installed and authenticated.

```bash
git clone https://github.com/ColonelPanicX/stratusscan-cli-azure.git
cd stratusscan-cli-azure

# Authenticate (StratusScan auto-detects the cloud and subscriptions from this)
az login

# Launch StratusScan — discovers everything on first run
python stratusscan.py

# Optional: narrow to specific subscriptions / persist a choice
python configure.py
```

> **Clone and run.** StratusScan is not installed as a package — there are no
> console commands to install. `python stratusscan.py` bootstraps its own
> dependencies from `pyproject.toml` on first run. Python 3.10 or newer.

---

## Authentication

StratusScanCLI-Azure uses `DefaultAzureCredential` from `azure-identity`, which tries credential sources in this order:

| Environment | How to authenticate |
|---|---|
| Azure Cloud Shell | Automatic — no action needed |
| Local machine | `az login` |
| Service Principal | Set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET` env vars |
| Managed Identity | Automatic when running on an Azure VM or App Service |

No profile management or custom credential handling is needed — one call covers all environments.

---

## Configuration

`configure.py` is **optional** — `stratusscan.py` auto-detects the cloud and
discovers every accessible subscription on first run. Run the wizard only to
narrow the scope or persist a choice:

```bash
python configure.py
```

The wizard:
1. Selects Azure cloud environment (Public or US Government)
2. Discovers all subscriptions accessible to your credentials
3. Prompts for subscription selection (single, all, or manual ID entry)
4. Writes `config.json`

`config.json` is local to your clone and untracked (it holds your subscription and
tenant IDs). The repo ships `config-template.json` instead; with no `config.json`
present the defaults apply and the cloud is auto-detected.

### Manual configuration

Copy `config-template.json` to `config.json` and edit it:

```json
{
  "environment": "public",
  "subscriptions": [
    {
      "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "name": "MY-SUBSCRIPTION",
      "state": "Enabled",
      "tenant_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    }
  ],
  "default_subscription_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

`"environment"` accepts `"auto"` (default — detect from the active Azure CLI cloud),
`"public"` or `"government"`. Detection order: `AZURE_ENVIRONMENT` env var →
explicit `config.json` value → Azure CLI cloud → public. An unrecognized
`AZURE_ENVIRONMENT` value is an error, not a silent fallback to public.

For Azure US Government, set `"environment": "government"` or the environment variable:

```bash
export AZURE_ENVIRONMENT=AzureUSGovernment
```

### CI / Unattended execution

```bash
STRATUSSCAN_AUTO_RUN=1 STRATUSSCAN_SUBSCRIPTIONS=sub-id-1,sub-id-2 python stratusscan.py
```

Individual exporters also support CI mode:

```bash
STRATUSSCAN_AUTO_RUN=1 python scripts/virtual_machines_export.py
```

`STRATUSSCAN_APPSERVICE_CONFIG=1` makes `app_service_export.py` and `function_apps_export.py` read each app's site configuration (runtime stack, TLS, FTPS) with one extra `get_configuration` call per app; off by default because it is N+1 against the ARM request budget.
`STRATUSSCAN_STORAGE_LIST_PACE_S=<seconds>` spaces the per-account list calls in `blob_containers_export.py` and `file_shares_export.py` (default 0) for subscriptions that hit the Storage resource provider's 100 list operations per 5 minutes per region.

---

## Usage

### Main menu

```bash
python stratusscan.py
```

Pick a tier — **Tier 1** (core infrastructure), **Tier 2** (workloads), **Governance** or **Monitoring** — then an individual exporter, or run every exporter in that tier. Exports are saved to `output/` as `.xlsx` files.

When multiple subscriptions are accessible, **Run All** scans a single subscription by default (the configured default, otherwise the first) to stay within the Cloud Shell session timeout. Choosing Run All prompts for scope, where scanning every subscription is an explicit opt-in. Running an individual exporter still fans out across all accessible subscriptions.

### Command-line flags

`python stratusscan.py` with no flags opens the menu. Flags run the same code path
non-interactively — same run id, manifest, run report, zip and exit codes.

| Flag | Meaning |
|---|---|
| `--list` | Print the tiers and exporter names, then exit (no Azure calls) |
| `--dry-run` | Validate credentials and print the targets, then exit without exporting |
| `--run-all` | Every exporter |
| `--tier {tier1,tier2,governance,monitoring}` | One tier; repeatable |
| `--exporter NAME` | One exporter by script name (`storage_accounts`) or menu label; repeatable |
| `--subscriptions ID[,ID…]｜all` | Target subscriptions (default: the default subscription) |
| `--no-zip` | Skip packaging this run |
| `--timeout SECONDS` | Per-exporter timeout (default 1800) |
| `--verbose` | Log at INFO on the console |
| `--version` | Print the version and exit |

```bash
python stratusscan.py --tier governance --subscriptions all
python stratusscan.py --exporter storage_accounts --exporter key_vault --no-zip
python stratusscan.py --dry-run
```

Every exporter takes `--subscription-id`, `--subscription-name`, `--output-dir`,
`--verbose` and `--help`:

```bash
python scripts/virtual_machines_export.py --subscription-id <guid> --output-dir /tmp/audit
```

`configure.py` is scriptable too: `--environment`, `--subscriptions`, `--default`,
`--validate` (list what the credential can see), `--show` (print the current config).

Precedence everywhere is **flags → environment variables → `config.json`**.

### Menu navigation

`b` goes back one level, `x` returns to the main menu, `q` quits. Ctrl-C quits cleanly.

### Direct script execution

Every exporter can run standalone:

```bash
python scripts/virtual_machines_export.py
python scripts/virtual_networks_export.py
python scripts/role_assignments_export.py
```

---

## Supported Azure Resources

### Tier 1 — Core Infrastructure (13 exporters)

| Script | Azure Service |
|---|---|
| `subscriptions_export.py` | Subscriptions |
| `resource_groups_export.py` | Resource Groups |
| `virtual_machines_export.py` | Virtual Machines |
| `vmss_export.py` | VM Scale Sets |
| `managed_disks_export.py` | Managed Disks |
| `virtual_networks_export.py` | Virtual Networks |
| `subnets_export.py` | Subnets |
| `network_security_groups_export.py` | Network Security Groups |
| `public_ips_export.py` | Public IP Addresses |
| `storage_accounts_export.py` | Storage Accounts |
| `key_vault_export.py` | Key Vaults |
| `key_vault_objects_export.py` | Key Vault Objects (Keys/Secrets/Certs) |
| `role_assignments_export.py` | RBAC Role Assignments |

### Tier 2 — Workloads (41 exporters)

| Script | Azure Service |
|---|---|
| `aks_clusters_export.py` | AKS Clusters |
| `container_registry_export.py` | Container Registries (ACR) |
| `container_apps_export.py` | Container Apps |
| `container_instances_export.py` | Container Instances (ACI) |
| `app_service_export.py` | App Service / Web Apps |
| `function_apps_export.py` | Function Apps |
| `azure_sql_export.py` | Azure SQL Databases |
| `sql_managed_instance_export.py` | SQL Managed Instances |
| `cosmos_db_export.py` | Cosmos DB Accounts |
| `postgresql_flexible_export.py` | PostgreSQL Flexible Servers |
| `mysql_flexible_export.py` | MySQL Flexible Servers |
| `redis_cache_export.py` | Redis Caches |
| `load_balancers_export.py` | Load Balancers |
| `dns_zones_export.py` | DNS Zones (public + private) |
| `front_door_export.py` | Front Door & CDN Profiles |
| `traffic_manager_export.py` | Traffic Manager Profiles |
| `event_hubs_export.py` | Event Hubs Namespaces |
| `service_bus_export.py` | Service Bus Namespaces |
| `api_management_export.py` | API Management Services |
| `logic_apps_export.py` | Logic Apps (Workflows) |
| `application_gateway_export.py` | Application Gateways |
| `azure_firewall_export.py` | Azure Firewalls |
| `firewall_policy_rules_export.py` | Firewall Policy Rules |
| `route_tables_export.py` | Route Tables |
| `vnet_peerings_export.py` | VNet Peerings |
| `snapshots_export.py` | Snapshots |
| `availability_sets_export.py` | Availability Sets |
| `private_endpoints_export.py` | Private Endpoints |
| `nat_gateways_export.py` | NAT Gateways |
| `bastion_hosts_export.py` | Bastion Hosts |
| `vpn_gateways_export.py` | VPN Gateways |
| `expressroute_export.py` | ExpressRoute Circuits |
| `virtual_wan_export.py` | Virtual WAN & Hubs |
| `ddos_protection_export.py` | DDoS Protection Plans |
| `network_watchers_export.py` | Network Watchers |
| `service_endpoints_export.py` | Service Endpoints |
| `blob_containers_export.py` | Blob Containers |
| `file_shares_export.py` | File Shares |
| `automation_accounts_export.py` | Automation Accounts |
| `batch_accounts_export.py` | Batch Accounts |
| `recovery_services_vaults_export.py` | Recovery Services Vaults |

### Governance (14 exporters)

| Script | Azure Service |
|---|---|
| `policy_assignments_export.py` | Azure Policy Assignments |
| `management_groups_export.py` | Management Groups |
| `defender_scores_export.py` | Defender Secure Scores & Plans |
| `defender_assessments_export.py` | Defender Assessments |
| `defender_alerts_export.py` | Defender Security Alerts |
| `regulatory_compliance_export.py` | Regulatory Compliance |
| `advisor_export.py` | Advisor Recommendations |
| `resource_locks_export.py` | Resource Locks |
| `resource_tags_export.py` | Resource Tags Inventory |
| `policy_definitions_export.py` | Custom Policy Definitions |
| `policy_compliance_export.py` | Policy Compliance State |
| `role_definitions_export.py` | RBAC Role Definitions |
| `managed_identities_export.py` | Managed Identities |
| `cost_management_export.py` | Cost Management (Month-to-Date) |

### Monitoring (7 exporters)

| Script | Azure Service |
|---|---|
| `metric_alerts_export.py` | Metric & Activity Log Alerts |
| `action_groups_export.py` | Action Groups |
| `log_analytics_export.py` | Log Analytics Workspaces |
| `diagnostic_settings_export.py` | Diagnostic Settings (audit) |
| `activity_log_settings_export.py` | Activity Log Export Settings |
| `flow_logs_export.py` | Network Watcher Flow Logs |
| `application_insights_export.py` | Application Insights |

---

## Output Files

All exports use a consistent naming convention:

```
{SUBSCRIPTION-NAME}-{resource-type}-{suffix}-export-{MM.DD.YYYY}.xlsx
```

Examples:
```
MY-SUBSCRIPTION-virtual-machines-all-export-05.06.2026.xlsx
MY-SUBSCRIPTION-role-assignments-all-export-05.06.2026.xlsx
```

All files land in `output/`.

### Exit codes / run report

Every exporter exits with a documented code, so an empty inventory is never mistaken for a failure:

| Exit code | Status | Meaning |
|---|---|---|
| 0 | OK | Workbook written |
| 1 | FAILED | The export raised — one console line names the Azure error code, the traceback is in `logs/` |
| 2 | CONFIG | No subscription targeted, unrecognized `AZURE_ENVIRONMENT`, or a missing package |
| 3 | EMPTY | Zero resources — no workbook written |
| 4 | PARTIAL | Workbook written, but at least one scope (storage account, SQL server, vault, …) failed — see its `Errors` sheet |

Run All prints one line per exporter (`OK (23 rows, 4.1s)`, `EMPTY`, `PARTIAL (3 errors)`, `FAILED (exit 1)`, `TIMEOUT`), writes `output/run-report-{scope}-{run_id}.xlsx`, and zips only that run's workbooks plus the report. Each exporter is killed after `STRATUSSCAN_EXPORTER_TIMEOUT` seconds (default 1800). In CI mode `stratusscan.py` exits 1 if any exporter was FAILED, TIMEOUT, PARTIAL or CONFIG; EMPTY results do not fail the run.

---

## Azure Permissions

StratusScanCLI-Azure requires read-only access. The minimum RBAC role assignment needed is **Reader** at the subscription scope.

```bash
az role assignment create \
  --role "Reader" \
  --assignee <your-principal-id> \
  --scope /subscriptions/<subscription-id>
```

`policies/azure-readonly-role.json` defines a purpose-built least-privilege
alternative — control-plane reads for exactly the resource providers the
exporters touch. See `policies/README.md`, which also covers the extra
permission the Key Vault Objects exporter needs (data-plane **list** on keys,
secrets and certificates; Key Vault Reader is enough, and secret *values* are
never read).

---

## Troubleshooting

**Missing dependencies**

`stratusscan.py` and `configure.py` install everything from `pyproject.toml` on
first run. To do it yourself, or after the pinned versions change:

```bash
pip install -r <(python -c "import tomllib;print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")
```

Every `azure-*` dependency is pinned to a validated major version. An SDK outside
that range reports which package and version it found rather than failing on an
attribute error.

**Authentication errors**
```bash
# Local machine
az login
az account show   # verify active subscription

# Verify DefaultAzureCredential can resolve
python -c "from azure.identity import DefaultAzureCredential; DefaultAzureCredential().get_token('https://management.azure.com/.default')"
```

**No subscriptions found**
- Confirm your credential has at least Reader access on one or more subscriptions
- In Cloud Shell, run `az account list` to verify what's accessible

**Azure Government connection issues**
- Set `AZURE_ENVIRONMENT=AzureUSGovernment` before running
- Or run `python configure.py` and select AzureUSGovernment

**Getting help**
1. Check `logs/` for detailed error messages
2. Verify subscription access: `az account list --output table`
3. Open an issue on GitHub with the relevant log excerpt

---

## Project Status

**Current version: 0.1.0-alpha** — pre-alpha, not production-ready.

All 75 exporters are written and the architecture is in place. Tier 1 has been
validated against live Azure Government subscriptions; Tier 2, Governance and
Monitoring have not. The first release will be cut once end-to-end validation is
complete.

### Roadmap

| Version | Target |
|---|---|
| `0.1.0` | First stable release — 75 exporters validated, Public + Government environments |
| `0.2.0` | Resource Graph Smart Scan, Entra ID exporters (Microsoft Graph SDK), pricing data |
| `0.3.0+` | Multi-tenant scanning, Textual TUI |

---

## Branch Workflow

| Branch | Purpose |
|---|---|
| `dev` | Primary development — all PRs target `dev` first |
| `main` | Release snapshots only — no direct commits |
| `feature/*`, `fix/*` | Short-lived topic branches targeting `dev` |

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

---

## Acknowledgments

Built with assistance from [Claude Code](https://claude.ai/code). Azure SDK for Python via [azure-sdk-for-python](https://github.com/Azure/azure-sdk-for-python). Excel export via [pandas](https://pandas.pydata.org/) and [openpyxl](https://openpyxl.readthedocs.io/).
