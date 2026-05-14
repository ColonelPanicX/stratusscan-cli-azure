# Owner-Aligned Refactor Plan

This plan turns the work from the closed PR branches into small, reviewable
changes that match the StratusScan product philosophy and the repo owner's
architecture requirements.

## Goal

Preserve the valuable technical work from the rejected PRs while restoring the
architecture the owner asked for:

- Terminal-only, menu-driven CLI.
- One independently runnable exporter script per resource or focused category.
- One exporter produces one scoped `.xlsx` workbook.
- `stratusscan_azure.py` stays a thin subprocess launcher.
- Resource Graph is allowed as an implementation detail inside targeted
  exporters.
- No monolithic "everything" workbook as the primary user workflow.
- No HTML reports or parallel artifact types.
- No resource modification, credential storage, daemon, API server, or web UI.

## What We Learned From The Closed PRs

### PR #4: `sslib` foundation and broad Resource Graph export

Owner feedback:

- The `sslib/` refactor has good ideas, but it was bundled into too large a
  structural rewrite.
- Replacing many per-resource exporters with one broad `resource_graph_export.py`
  removes targeted-export behavior.
- The right model is still one script per resource or category, even if those
  scripts use Resource Graph KQL internally.

Salvage:

- Cloud-aware auth and endpoint helpers.
- Output filename and workbook helpers.
- Subscription filtering concepts.
- Resource Graph KQL patterns.
- Smoke-test patterns.

Do not salvage:

- The monolithic Resource Graph workbook as the main inventory model.
- Deletion of existing per-resource exporters in the same PR as new foundation
  work.

### PR #5: Flattened NSG rules

Owner feedback:

- The flattened NSG rule data is valuable and auditor-aligned.
- It should be a standalone `network_security_groups_export.py`, not a bonus
  sheet inside a broad Resource Graph workbook.

Salvage:

- KQL that unions custom and default NSG security rules.
- Row schema for priority, direction, access, protocol, source/destination, and
  ports.

### PR #6: FinOps waste and tag coverage

Owner feedback:

- Orphaned resources, stale snapshots, tag coverage, and untagged resources are
  useful.
- They should be a standalone `finops_export.py`, not extra sheets appended to
  a full-tenant inventory workbook.

Salvage:

- KQL for orphaned disks, unassigned public IPs, orphaned NICs, stale snapshots,
  tag coverage, and untagged resources.

### PR #7: Cost findings HTML report

Owner feedback:

- HTML output does not fit StratusScan. Findings belong in workbooks.
- The owner corrected the initial objection to Cost Management API calls:
  Azure Cost Management data is acceptable when implemented as a standard
  exporter.
- A `cost_management_export.py` that queries Cost Management and writes `.xlsx`
  would be a good focused PR.

Salvage:

- Cost Management Query API implementation.
- US Gov routing fix using `timeframe=Custom` with explicit `timePeriod`.
- Graceful handling for subscriptions without Cost Management permissions.

Do not salvage:

- HTML report generation.
- Auto-generating sidecar artifacts during unrelated exporters.

## Branching Strategy

The rejected branches should be treated as source material only.

For every new PR:

```bash
git fetch origin
git switch dev
git pull --ff-only origin dev
git switch -c feature/<small-focused-slug>
```

Then copy or cherry-pick only the narrow code needed for that PR.

Do not base new PRs on:

- `feature/cost-findings-report`
- `feature/cost-addons`
- `feature/security-addons`
- `sslib-foundation`
- any branch that deletes the existing per-resource exporter structure

## PR Acceptance Criteria

Every PR must satisfy:

- It targets `dev`.
- It has one primary purpose.
- It preserves existing exporter granularity unless the PR is explicitly adding
  one new targeted exporter.
- Any new exporter can run directly with `python scripts/<path>.py`.
- The main menu only launches the exporter as a subprocess.
- Output is an `.xlsx` workbook written through the repo's output helper or the
  existing local pattern.
- Errors are recorded in a `Summary` sheet or human-readable CLI message instead
  of crashing the whole run where partial export is possible.
- Azure calls are read-only.
- Public and US Gov clouds are either supported or unavailable services are
  skipped cleanly with a logged reason.
- Runtime dependencies remain Cloud Shell-friendly and minimal.
- Tests or smoke checks cover importability and menu registration where
  practical.

## Proposed PR Sequence

### PR 1: Document the owner contract

Purpose:

- Add `stratusscan-philosophy.md`.
- Add `AGENTS.md`.
- Align existing agent/contributor docs so future work follows the same
  architecture.

Allowed changes:

- Documentation only.

Not allowed:

- Runtime refactors.
- Exporter changes.

Validation:

- Markdown review.
- Confirm no runtime files changed.

### PR 2: Minimal shared helpers, if needed

Purpose:

- Introduce only the shared helpers required to support focused exporters
  without duplicating auth, cloud, output, or subscription logic.

Candidate scope:

- `sslib.auth.get_credential()`
- `sslib.cloud.detect_cloud()`
- `sslib.cloud.arm_client_kwargs()`
- `sslib.output.make_filename()`
- `sslib.output.save_dataframes()`
- `sslib.subscriptions` filtering helpers

Rules:

- Keep the PR small.
- Do not rewrite every existing exporter in this PR.
- Do not remove existing exporters.
- Do not add feature behavior beyond enabling future exporters.
- No `print()` in shared library code.

Validation:

- Smoke import tests for new shared modules.
- Manual menu startup.

### PR 3: Standalone NSG rules exporter

Purpose:

- Implement flattened NSG rule export in the owner-approved shape.

File target:

- `scripts/network/network_security_groups_export.py`

Behavior:

- Runs directly.
- Uses Resource Graph KQL internally.
- Produces a dedicated NSG workbook.
- Includes custom and default rules.
- Keeps audit-relevant columns: subscription, resource group, NSG name,
  location, rule type, rule name, priority, direction, access, protocol,
  source/destination prefixes, source/destination ports, ASGs, description, ID.

Menu:

- Register or preserve the menu item for Network Security Groups.

Validation:

- Import smoke test.
- Dry/manual run against an Azure tenant if credentials are available.
- Confirm workbook has `Summary` first and rule detail sheet after.

### PR 4: Standalone FinOps signal exporter

Purpose:

- Add a focused FinOps workbook based on inventory-derived waste and governance
  signals.

File target:

- `scripts/finops_export.py`

Sheets:

- `Summary`
- `Orphaned Resources`
- `Stale Snapshots`
- `Tag Coverage`
- `Untagged Resources`

Behavior:

- Uses Resource Graph KQL only.
- Requires no billing permissions.
- Does not claim exact dollar savings.
- Uses descriptive, pivot-friendly columns.

Menu:

- Add a top-level menu item for FinOps signals.

Validation:

- Import smoke test.
- Manual run where possible.
- Confirm no new runtime dependencies.

### PR 5: Standalone Cost Management exporter

Purpose:

- Add actual billed-cost export in the owner-approved workbook shape.

File target:

- `scripts/cost_management_export.py`

Optional helper:

- `sslib/cost_management.py`, if not already introduced in PR 2.

Behavior:

- Queries Azure Cost Management read-only API.
- Writes `.xlsx`, not HTML.
- Uses active cloud ARM endpoint and scope.
- Uses `timeframe=Custom` with explicit previous-month `timePeriod` for gov
  cloud compatibility.
- Handles subscriptions without Cost Management access by recording the error in
  `Summary` and continuing.

Sheets:

- `Summary`
- `Costs By Resource`
- Optional: `Costs By Subscription`
- Optional: `Costs By Resource Group`

Menu:

- Add a top-level menu item for Cost Management.

Validation:

- Import smoke test.
- Manual run in at least one tenant.
- Confirm subscriptions without permissions do not fail the whole export.

### PR 6+: Resource Graph-backed targeted exporter modernization

Purpose:

- Improve existing per-resource exporters one at a time by using Resource Graph
  internally while preserving their targeted script and workbook contract.

Candidate order:

1. `scripts/compute/virtual_machines_export.py`
2. `scripts/storage/storage_accounts_export.py`
3. `scripts/network/public_ips_export.py`
4. `scripts/network/load_balancers_export.py`
5. `scripts/network/application_gateway_export.py`
6. `scripts/compute/managed_disks_export.py`
7. `scripts/resource_groups_export.py`

Rules:

- One exporter per PR unless two are tightly coupled and small.
- Preserve or improve existing workbook names.
- Preserve independent script execution.
- Use Resource Graph KQL internally where it improves cross-subscription
  coverage and performance.
- Do not reintroduce a broad 50-sheet Resource Graph workbook.

Validation:

- Import smoke test.
- Manual run of the touched exporter.
- Compare workbook sheet intent against the previous exporter.

## What To Avoid

- "Foundation" PRs that also add major feature behavior.
- Deleting the old exporter tree in the same PR that introduces new helpers.
- Adding feature sheets to a broad inventory workbook when the feature should be
  its own exporter.
- Sidecar HTML reports.
- Output formats other than `.xlsx`.
- Live dashboards, monitoring loops, APIs, or services.
- Dependencies that make Azure Cloud Shell setup heavier.
- User-facing config switches for cloud partitions that can be detected.

## Review Template For Each PR

Include this checklist in every PR description:

```markdown
## Architecture Checklist

- [ ] One primary purpose
- [ ] Exporter remains independently runnable
- [ ] Main menu only launches subprocesses
- [ ] Output is `.xlsx`
- [ ] No HTML/web/API/daemon behavior
- [ ] Read-only Azure access only
- [ ] Cloud Shell-friendly dependencies
- [ ] Public/Gov cloud behavior considered
- [ ] Errors degrade gracefully where partial export is possible
- [ ] Tests or smoke checks updated
```

## Working Agreement

Before opening a PR, verify the branch diff against `origin/dev`:

```bash
git diff --stat origin/dev...HEAD
git diff --name-status origin/dev...HEAD
```

If the diff shows unrelated rewrites, deleted exporter trees, generated files, or
multiple feature areas, split the work before submitting.
