# RBAC Policies

Read-only Azure RBAC role definitions for running StratusScanCLI-Azure under least
privilege. Use these instead of the broad built-in **Reader** role when an audit
requires that the scanning principal's permissions be enumerated and justified.

## `azure-readonly-role.json` — StratusScan Reader

A custom role granting **control-plane read access only** to exactly the resource
providers the exporters inventory — nothing more. No `DataActions`, no write/delete,
and the only non-`read` actions are three non-mutating queries.

### Why the three `/action` entries

Some Azure query APIs are `POST` operations modeled as `/action` rather than `/read`.
They return data and change nothing, but a `*/read` wildcard does not cover them, so
each is granted explicitly:

| Action | Used by | Operation |
|---|---|---|
| `Microsoft.CostManagement/query/action` | `cost_management_export.py` | Query Usage (`query.usage`) |
| `Microsoft.PolicyInsights/policyStates/queryResults/action` | `policy_compliance_export.py` | Query policy states (`list_query_results_for_subscription`) |
| `Microsoft.PolicyInsights/policyStates/summarize/action` | `policy_compliance_export.py` | Summarize policy states (`summarize_for_subscription`) |

Source for the PolicyInsights action strings:
[Azure permissions for Management and governance](https://learn.microsoft.com/azure/role-based-access-control/permissions/management-and-governance#microsoftpolicyinsights)
— "Query information about policy states" / "Query summary information about policy
latest states". Everything else in the role is `*/read`.

### Why no `DataActions`

Almost every exporter uses the management plane, and **StratusScan Reader** is a pure
management-plane role: `DataActions` is empty, which is what makes "read-only"
auditable.

The one data-plane exporter — `key_vault_objects_export.py` (Key Vault
keys/secrets/certificates metadata) — is **not** covered by this role and is not meant
to be. It reads the Key Vault data plane, which requires per-vault data-plane access
the management role does not grant. To run it, additionally assign the scanning
principal one of:

- **RBAC vaults** (`enableRbacAuthorization = true`): the built-in **Key Vault Reader**
  role (lists keys/secrets/certs metadata without exposing secret values), scoped to
  the vault, subscription, or management group.
- **Access-policy vaults**: a vault access policy granting **List** on keys, secrets,
  and certificates.

Vaults the principal cannot read are skipped with a logged warning, so the exporter is
safe to run with partial coverage. It never reads secret/key *values* — metadata only.

## Creating the role

1. Replace the `AssignableScopes` placeholder with your subscription ID (or a
   management-group ID to cover many subscriptions):

   ```bash
   # subscription scope
   "/subscriptions/<subscription-id>"
   # or management-group scope (multi-subscription)
   "/providers/Microsoft.Management/managementGroups/<mg-id>"
   ```

2. Create the role (Azure CLI, works in Cloud Shell):

   ```bash
   az role definition create --role-definition policies/azure-readonly-role.json
   ```

3. Assign it to the scanning principal (user, group, or service principal):

   ```bash
   az role assignment create \
     --assignee "<principal-object-id>" \
     --role "StratusScan Reader" \
     --scope "/subscriptions/<subscription-id>"
   ```

## Azure Government

The same definition applies in `AzureUSGovernment`; run the `az` commands against a
Cloud Shell or CLI signed in to the government cloud
(`az cloud set --name AzureUSGovernment`). Action strings are identical across clouds.

## Keeping it in sync

The `Actions` list mirrors the provider namespaces behind `utils._CLIENT_MAP`. When an
exporter introduces a **new** `azure-mgmt-*` client, add that provider's `*/read` here.
The current list covers all 75 exporters.
