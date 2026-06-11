# RBAC Policies

Read-only Azure RBAC role definitions for running StratusScanCLI-Azure under least
privilege. Use these instead of the broad built-in **Reader** role when an audit
requires that the scanning principal's permissions be enumerated and justified.

## `azure-readonly-role.json` — StratusScan Reader

A custom role granting **control-plane read access only** to exactly the resource
providers the exporters inventory — nothing more. No `DataActions`, no write/delete,
and the only non-`read` action is the non-mutating Cost Management usage query.

### Why `Microsoft.CostManagement/query/action`

The cost exporter calls the Cost Management **Query** API (`query.usage`), which is a
`POST` modeled as an `/action` operation ("Query Usage") rather than a `/read`. It
returns data and changes nothing, but it is **not** covered by
`Microsoft.CostManagement/*/read`, so it is granted explicitly. It is the only
`/action` in the role; everything else is `*/read`.

### Why no `DataActions`

Every exporter uses the management plane. Data-plane inventory (e.g. enumerating
individual Key Vault keys/secrets/certs — see deferred issue SSAZR-065) would require
`DataActions` and per-resource data-plane role assignments that this role deliberately
does not grant. Keeping `DataActions` empty is what makes "read-only" auditable.

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
The current list covers all 69 exporters.
