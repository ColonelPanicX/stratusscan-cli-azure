# StratusScanCLI-Azure

[![Version: 0.1.0](https://img.shields.io/badge/version-0.1.0--alpha-red.svg)](#project-status)
[![Status: Pre-Alpha](https://img.shields.io/badge/status-pre--alpha-red.svg)](#project-status)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
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

A Python CLI tool for exporting Azure resource inventories to Excel workbooks. Supports 21 Azure services across Public and US Government cloud environments, targeting infrastructure audits, FedRAMP evidence collection, and cost analysis.

Sibling project to [StratusScan-CLI (AWS)](https://github.com/ColonelPanicX/StratusScan-CLI). Shares the same philosophy, output format, and architectural patterns — not a fork.

---

## Quick Start

### Azure Cloud Shell (recommended)

The tool is designed to work in a fresh [Azure Cloud Shell](https://shell.azure.com) session with no extra setup. Credentials are injected automatically.

```bash
git clone https://github.com/ColonelPanicX/stratusscan-cli-azure.git
cd stratusscan-cli-azure
pip install -r <(python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print('\n'.join(d['project']['dependencies']))")
python configure.py
python azurescan.py
```

### Local Machine

Requires [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) installed and authenticated.

```bash
git clone https://github.com/ColonelPanicX/stratusscan-cli-azure.git
cd stratusscan-cli-azure

# Install dependencies
pip install azure-identity azure-mgmt-resource azure-mgmt-compute azure-mgmt-network \
    azure-mgmt-resourcegraph azure-mgmt-storage azure-mgmt-keyvault azure-mgmt-authorization \
    azure-mgmt-containerservice azure-mgmt-web azure-mgmt-sql azure-mgmt-cosmosdb \
    pandas openpyxl python-dateutil questionary

# Authenticate
az login

# Configure subscription and environment
python configure.py

# Launch AzureScan
python azurescan.py
```

### pip install (once published)

```bash
pip install stratusscan-cli-azure
azurescan-configure
azurescan
```

> **Note:** PyPI publishing is pending the first stable release.

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

Run the configuration wizard before first use:

```bash
python configure.py
```

The wizard:
1. Selects Azure cloud environment (Public or US Government)
2. Discovers all subscriptions accessible to your credentials
3. Prompts for subscription selection (single, all, or manual ID entry)
4. Writes `config.json`

### Manual configuration

Edit `config.json` directly:

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

For Azure US Government, set `"environment": "government"` or the environment variable:

```bash
export AZURE_ENVIRONMENT=AzureUSGovernment
```

### CI / Unattended execution

```bash
AZURESCAN_AUTO_RUN=1 AZURESCAN_SUBSCRIPTIONS=sub-id-1,sub-id-2 python azurescan.py
```

Individual exporters also support CI mode:

```bash
AZURESCAN_AUTO_RUN=1 python scripts/compute/virtual_machines_export.py
```

---

## Usage

### Main menu

```bash
python azurescan.py
```

Select **Tier 1** or **Tier 2** from the menu, then pick an individual exporter or run all. Exports are saved to `output/` as `.xlsx` files.

### Direct script execution

Every exporter can run standalone:

```bash
python scripts/compute/virtual_machines_export.py
python scripts/network/virtual_networks_export.py
python scripts/security/role_assignments_export.py
```

---

## Supported Azure Resources

### Tier 1 — Core Infrastructure (11 exporters)

| Script | Azure Service |
|---|---|
| `subscriptions_export.py` | Subscriptions |
| `resource_groups_export.py` | Resource Groups |
| `virtual_machines_export.py` | Virtual Machines |
| `managed_disks_export.py` | Managed Disks |
| `virtual_networks_export.py` | Virtual Networks (VNets) |
| `subnets_export.py` | Subnets |
| `network_security_groups_export.py` | Network Security Groups and flattened rules |
| `public_ips_export.py` | Public IP Addresses |
| `storage_accounts_export.py` | Storage Accounts |
| `key_vault_export.py` | Key Vault |
| `role_assignments_export.py` | RBAC Role Assignments |

### Tier 2 — Common Workloads (10 exporters)

| Script | Azure Service |
|---|---|
| `aks_clusters_export.py` | AKS Clusters |
| `app_service_export.py` | App Service / Web Apps |
| `function_apps_export.py` | Function Apps |
| `azure_sql_export.py` | Azure SQL Databases |
| `cosmos_db_export.py` | Cosmos DB Accounts |
| `load_balancers_export.py` | Load Balancers |
| `application_gateway_export.py` | Application Gateways |
| `azure_firewall_export.py` | Azure Firewalls |
| `route_tables_export.py` | Route Tables |
| `vnet_peerings_export.py` | VNet Peerings |

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

---

## Azure Permissions

StratusScanCLI-Azure requires read-only access. The minimum RBAC role assignment needed is **Reader** at the subscription scope.

```bash
az role assignment create \
  --role "Reader" \
  --assignee <your-principal-id> \
  --scope /subscriptions/<subscription-id>
```

A purpose-built read-only custom role definition will be provided in `policies/` in a future update.

---

## Troubleshooting

**Missing dependencies**
```bash
pip install azure-identity azure-mgmt-resource azure-mgmt-compute azure-mgmt-network \
    azure-mgmt-resourcegraph azure-mgmt-storage azure-mgmt-keyvault azure-mgmt-authorization \
    azure-mgmt-containerservice azure-mgmt-web azure-mgmt-sql azure-mgmt-cosmosdb \
    pandas openpyxl
```

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

This is the initial scaffold of StratusScanCLI-Azure. The 21 exporters are written and the core architecture is in place, but the tool has not yet been validated against live Azure subscriptions. The first release will be cut once end-to-end testing is complete.

### Roadmap

| Version | Target |
|---|---|
| `0.1.0` | First stable release — 21 exporters validated, Public + Government environments |
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
