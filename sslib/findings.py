"""
sslib.findings — Build a self-contained HTML cost findings report.

Reads the in-memory sheets dict produced by resource_graph_export plus the
cost map from sslib.cost_management, computes prioritised findings
(unattached disks, stale snapshots, stopped VMs, idle Standard public
IPs), and renders a single-file HTML report.

Output is fully self-contained — inline CSS, no images, no external
scripts — so it can be emailed or attached as a deliverable. No print()
is emitted from this module; callers are responsible for writing the
returned string to disk.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_cost_findings_html(
    sheets: Dict[str, Any],
    cost_map: Dict[str, float],
    scope_label: str,
    cloud_name: str,
    coverage_period: Optional[str] = None,
) -> str:
    """
    Build a self-contained HTML cost findings report.

    sheets: {sheet_name: pandas.DataFrame} — same dict the exporter writes
        to xlsx.
    cost_map: {resource_id_lower: cost} from sslib.cost_management.
    scope_label: tenant/subscription label for the report header.
    cloud_name: e.g. "AzureCloud" or "AzureUSGovernment".
    coverage_period: human-readable string for the cost coverage window;
        if omitted, derived from cost_management's last-full-month.
    """
    findings = _compute_findings(sheets, cost_map)
    return _render_html(findings, scope_label, cloud_name, cost_map, coverage_period)


# ---------------------------------------------------------------------------
# Finding computation
# ---------------------------------------------------------------------------


def _compute_findings(sheets: Dict[str, Any], cost_map: Dict[str, float]) -> List[Dict[str, Any]]:
    """Return list of finding dicts in priority order (most actionable first)."""
    findings: List[Dict[str, Any]] = []

    f = _unattached_disks_finding(sheets.get("Disks"), cost_map)
    if f:
        findings.append(f)

    f = _stopped_vms_finding(sheets.get("Stopped VMs"), cost_map)
    if f:
        findings.append(f)

    f = _stale_snapshots_finding(sheets.get("Snapshots"), cost_map)
    if f:
        findings.append(f)

    f = _idle_public_ips_finding(sheets.get("Public IPs"), cost_map)
    if f:
        findings.append(f)

    return findings


def _unattached_disks_finding(df, cost_map):
    if df is None or df.empty or "id" not in df.columns:
        return None

    mb = df.get("managedBy")
    if mb is None:
        return None
    orphans = df[mb.isna() | (mb.astype(str).str.strip() == "")].copy()
    if orphans.empty:
        return None

    orphans["cost"] = orphans["id"].astype(str).str.lower().map(cost_map).fillna(0.0)
    _add_age_days(orphans)
    orphans = orphans.sort_values("cost", ascending=False)

    total_size = int(orphans["diskSizeGB"].fillna(0).sum()) if "diskSizeGB" in orphans.columns else 0
    return {
        "name": "Unattached Disks",
        "description": (
            "Managed disks not attached to any VM. Billed at the full "
            "provisioned rate every month regardless of use. The Age "
            "column is days since the disk was created — an upper bound "
            "on \"days unused\" since Azure does not expose a "
            "last-detached timestamp via Resource Graph."
        ),
        "action": (
            "Review with the resource owner. Convert to a snapshot first if "
            "retention is required, then delete the disk."
        ),
        "count": len(orphans),
        "total_size_gb": total_size,
        "total_cost": float(orphans["cost"].sum()),
        "max_age_days": _max_age(orphans),
        "columns": [
            ("subscriptionId", "Subscription"),
            ("resourceGroup", "Resource Group"),
            ("name", "Disk"),
            ("diskSizeGB", "Size (GB)"),
            ("skuName", "SKU"),
            ("ageDays", "Age (days)"),
            ("cost", "Last month ($)"),
        ],
        "rows": _top_rows(orphans, ["subscriptionId", "resourceGroup", "name",
                                     "diskSizeGB", "skuName", "ageDays",
                                     "cost"], n=10),
    }


def _stopped_vms_finding(df, cost_map):
    if df is None or df.empty or "id" not in df.columns:
        return None
    df = df.copy()
    df["vm_cost"] = df["id"].astype(str).str.lower().map(cost_map).fillna(0.0)
    if "osDiskId" in df.columns:
        df["os_disk_cost"] = df["osDiskId"].astype(str).str.lower().map(cost_map).fillna(0.0)
    else:
        df["os_disk_cost"] = 0.0
    df["cost"] = df["vm_cost"] + df["os_disk_cost"]
    _add_age_days(df)
    df = df.sort_values("cost", ascending=False)

    return {
        "name": "Stopped VMs (compute idle, disks still billing)",
        "description": (
            "Deallocated VMs do not bill for compute, but their attached "
            "OS and data disks continue to bill at the provisioned rate. "
            "The Cost ($) column shows the VM + OS disk cost; data disks "
            "(not joined here) add further to the actual waste. The Age "
            "column is days since the VM was created — Resource Graph "
            "does not expose a reliable last-deallocated timestamp, so "
            "use this as the VM lifecycle reference rather than \"how "
            "long it has been stopped\"."
        ),
        "action": (
            "If retained for fast restart, accept the disk cost. Otherwise "
            "delete the VM and its disks — a snapshot first preserves any "
            "data worth keeping."
        ),
        "count": len(df),
        "total_cost": float(df["cost"].sum()),
        "max_age_days": _max_age(df),
        "columns": [
            ("subscriptionId", "Subscription"),
            ("resourceGroup", "Resource Group"),
            ("name", "VM"),
            ("vmSize", "Size"),
            ("powerState", "Power State"),
            ("osDiskSizeGB", "OS Disk (GB)"),
            ("dataDiskCount", "Data Disks"),
            ("ageDays", "Age (days)"),
            ("cost", "Last month ($)"),
        ],
        "rows": _top_rows(df, ["subscriptionId", "resourceGroup", "name",
                                "vmSize", "powerState", "osDiskSizeGB",
                                "dataDiskCount", "ageDays", "cost"], n=10),
    }


def _stale_snapshots_finding(df, cost_map):
    if df is None or df.empty or "id" not in df.columns:
        return None
    if "timeCreated" not in df.columns:
        return None
    import pandas as pd

    df = df.copy()
    df["timeCreated"] = pd.to_datetime(df["timeCreated"], errors="coerce", utc=True)
    now = pd.Timestamp.utcnow()
    df["ageInDays"] = (now - df["timeCreated"]).dt.days
    stale = df[df["ageInDays"].fillna(0) > 90].copy()
    if stale.empty:
        return None

    stale["cost"] = stale["id"].astype(str).str.lower().map(cost_map).fillna(0.0)
    stale = stale.sort_values("cost", ascending=False)

    total_size = int(stale["diskSizeGB"].fillna(0).sum()) if "diskSizeGB" in stale.columns else 0
    max_age = int(stale["ageInDays"].fillna(0).max()) if "ageInDays" in stale.columns else None
    return {
        "name": "Stale Snapshots (>90 days old)",
        "description": (
            "Snapshots older than 90 days. Most are one-off backups taken "
            "for migrations or test rollbacks that were never cleaned up. "
            "The Age column here is exact — derived from the snapshot's "
            "creation timestamp."
        ),
        "action": (
            "Review with the resource owner; if unrecognised, delete. "
            "Incremental snapshots cost less than full snapshots; the "
            "incremental column shows which is which."
        ),
        "count": len(stale),
        "total_size_gb": total_size,
        "total_cost": float(stale["cost"].sum()),
        "max_age_days": max_age,
        "columns": [
            ("subscriptionId", "Subscription"),
            ("resourceGroup", "Resource Group"),
            ("name", "Snapshot"),
            ("diskSizeGB", "Size (GB)"),
            ("ageInDays", "Age (days)"),
            ("incremental", "Incremental"),
            ("cost", "Last month ($)"),
        ],
        "rows": _top_rows(stale, ["subscriptionId", "resourceGroup", "name",
                                   "diskSizeGB", "ageInDays", "incremental",
                                   "cost"], n=10),
    }


def _idle_public_ips_finding(df, cost_map):
    if df is None or df.empty or "id" not in df.columns:
        return None

    associated = df.get("associatedTo")
    sku = df.get("skuName")
    if associated is None or sku is None:
        return None
    idle = df[
        (associated.isna() | (associated.astype(str).str.strip() == ""))
        & (sku.astype(str).str.lower() == "standard")
    ].copy()
    if idle.empty:
        return None

    idle["cost"] = idle["id"].astype(str).str.lower().map(cost_map).fillna(0.0)
    _add_age_days(idle)
    idle = idle.sort_values("cost", ascending=False)

    return {
        "name": "Idle Standard Public IPs",
        "description": (
            "Standard SKU public IP addresses not associated with any "
            "resource. Bill at the idle rate (Basic SKU IPs, not shown, "
            "are free when idle). The Age column is days since the IP "
            "was created — an upper bound on \"days unused\" since "
            "Resource Graph does not expose a last-disassociated time."
        ),
        "action": (
            "Delete unless explicitly reserved for a planned reattach. "
            "Static Standard IPs do not change on deletion-and-recreate "
            "in many cases — confirm with the owner first."
        ),
        "count": len(idle),
        "total_cost": float(idle["cost"].sum()),
        "max_age_days": _max_age(idle),
        "columns": [
            ("subscriptionId", "Subscription"),
            ("resourceGroup", "Resource Group"),
            ("name", "Public IP"),
            ("skuName", "SKU"),
            ("ipAddress", "IP"),
            ("ageDays", "Age (days)"),
            ("cost", "Last month ($)"),
        ],
        "rows": _top_rows(idle, ["subscriptionId", "resourceGroup", "name",
                                  "skuName", "ipAddress", "ageDays",
                                  "cost"], n=10),
    }


def _top_rows(df, columns: List[str], n: int = 10) -> List[Dict[str, Any]]:
    available = [c for c in columns if c in df.columns]
    out = df.head(n)[available].fillna("").to_dict(orient="records")
    return out


def _add_age_days(df, time_col: str = "timeCreated") -> None:
    """In-place: add ageDays column (int) computed from timeCreated."""
    import pandas as pd

    if time_col not in df.columns:
        df["ageDays"] = pd.NA
        return
    ts = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    now = pd.Timestamp.utcnow()
    df["ageDays"] = ((now - ts).dt.days).fillna(0).astype(int)


def _max_age(df, age_col: str = "ageDays") -> Optional[int]:
    if age_col not in df.columns:
        return None
    try:
        m = df[age_col].max()
        if m is None:
            return None
        m = int(m)
        return m if m > 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


_CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
        Helvetica, Arial, sans-serif;
    max-width: 1100px;
    margin: 2rem auto;
    padding: 0 1.5rem;
    color: #1a1a1a;
    background: #f7f8fa;
    line-height: 1.5;
}
h1 { font-size: 1.75rem; margin: 0 0 0.25rem; }
h2 { font-size: 1.25rem; margin: 0 0 1rem; color: #1a1a1a; }
.meta { color: #666; font-size: 0.9rem; margin-bottom: 2rem; }
.card {
    background: white;
    border: 1px solid #e2e5e9;
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}
.summary-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
}
@media (max-width: 700px) {
    .summary-grid { grid-template-columns: repeat(2, 1fr); }
}
.stat {
    background: #f0f3f7;
    border-radius: 6px;
    padding: 1rem;
    text-align: center;
}
.stat-value {
    font-size: 1.6rem;
    font-weight: 700;
    color: #2c3e50;
    font-variant-numeric: tabular-nums;
}
.stat-value.money { color: #c0392b; }
.stat-label {
    color: #5e6b7a;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 0.25rem;
}
.finding-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 1rem;
    flex-wrap: wrap;
}
.finding-name { font-size: 1.15rem; font-weight: 600; margin: 0; }
.finding-cost {
    font-size: 1.4rem;
    font-weight: 700;
    color: #c0392b;
    font-variant-numeric: tabular-nums;
}
.finding-meta {
    color: #5e6b7a;
    font-size: 0.85rem;
    margin-top: 0.25rem;
}
.description {
    color: #3a3a3a;
    margin: 0.75rem 0;
}
.action {
    background: #fffaeb;
    border-left: 3px solid #f1c40f;
    padding: 0.75rem 1rem;
    margin: 1rem 0;
    font-size: 0.9rem;
    border-radius: 0 4px 4px 0;
}
.action strong { color: #7a5d00; }
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
    font-size: 0.875rem;
}
th {
    text-align: left;
    padding: 0.6rem 0.5rem;
    background: #f0f3f7;
    border-bottom: 2px solid #d8dde4;
    font-weight: 600;
    color: #2c3e50;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
td {
    padding: 0.55rem 0.5rem;
    border-bottom: 1px solid #eef0f3;
    vertical-align: top;
}
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.cost { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; color: #c0392b; }
.no-findings {
    color: #5e6b7a;
    font-style: italic;
    padding: 2rem;
    text-align: center;
}
.footer {
    color: #7a8290;
    font-size: 0.8rem;
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid #e2e5e9;
}
.footer code {
    background: #ecf0f4;
    padding: 0.1rem 0.35rem;
    border-radius: 3px;
    font-size: 0.85em;
}
"""


def _fmt_money(v: float) -> str:
    if v is None:
        return "$0"
    return f"${v:,.2f}" if v < 100 else f"${v:,.0f}"


def _fmt_int(v) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v) if v is not None else ""


def _render_cell(value, key) -> str:
    if value is None or value == "":
        return ""
    if key == "cost":
        return f'<td class="cost">{_fmt_money(float(value))}</td>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<td class="num">{value:,.0f}</td>' if float(value).is_integer() else f'<td class="num">{value:,.2f}</td>'
    return f"<td>{html.escape(str(value))}</td>"


def _render_finding(f: Dict[str, Any]) -> str:
    rows_html = []
    for row in f["rows"]:
        cells = "".join(_render_cell(row.get(k), k) for k, _ in f["columns"])
        rows_html.append(f"<tr>{cells}</tr>")
    headers = "".join(f"<th>{html.escape(label)}</th>" for _, label in f["columns"])

    meta_parts = [f"{f['count']:,} resource(s) flagged"]
    if f.get("total_size_gb"):
        meta_parts.append(f"{f['total_size_gb']:,} GB total")
    if f.get("max_age_days"):
        meta_parts.append(f"oldest {f['max_age_days']:,} days")
    meta = " · ".join(meta_parts)

    return f"""
    <div class="card">
      <div class="finding-header">
        <h3 class="finding-name">{html.escape(f['name'])}</h3>
        <div class="finding-cost">{_fmt_money(f['total_cost'])}</div>
      </div>
      <div class="finding-meta">{meta} · showing top {len(f['rows'])} by cost</div>
      <div class="description">{html.escape(f['description'])}</div>
      <div class="action"><strong>Recommended:</strong> {html.escape(f['action'])}</div>
      <table>
        <thead><tr>{headers}</tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    </div>
    """


def _render_html(
    findings: List[Dict[str, Any]],
    scope_label: str,
    cloud_name: str,
    cost_map: Dict[str, float],
    coverage_period: Optional[str],
) -> str:
    total_cost = sum(f["total_cost"] for f in findings)
    total_count = sum(f["count"] for f in findings)
    categories = len(findings)
    coverage = f"{len(cost_map):,} resources" if cost_map else "no cost data"

    period = coverage_period or _default_period_label()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if findings:
        findings_html = "\n".join(_render_finding(f) for f in findings)
    else:
        findings_html = (
            '<div class="card"><div class="no-findings">'
            "No actionable cost findings detected. Either the tenant is "
            "well-maintained, or the source sheets needed to compute "
            "findings (Disks, Snapshots, Public IPs, Stopped VMs) were "
            "empty in this export."
            "</div></div>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Azure Cost Findings — {html.escape(scope_label)}</title>
<style>{_CSS}</style>
</head>
<body>
  <h1>Azure Cost Findings — {html.escape(scope_label)}</h1>
  <div class="meta">
    Cloud: <strong>{html.escape(cloud_name)}</strong> ·
    Coverage period: <strong>{html.escape(period)}</strong> ·
    Generated: {html.escape(generated)}
  </div>

  <div class="card">
    <h2>Executive Summary</h2>
    <div class="summary-grid">
      <div class="stat">
        <div class="stat-value money">{_fmt_money(total_cost)}</div>
        <div class="stat-label">Recoverable / month</div>
      </div>
      <div class="stat">
        <div class="stat-value">{_fmt_int(total_count)}</div>
        <div class="stat-label">Resources flagged</div>
      </div>
      <div class="stat">
        <div class="stat-value">{_fmt_int(categories)}</div>
        <div class="stat-label">Finding categories</div>
      </div>
      <div class="stat">
        <div class="stat-value">{html.escape(coverage)}</div>
        <div class="stat-label">Cost data coverage</div>
      </div>
    </div>
  </div>

  {findings_html}

  <div class="footer">
    Cost figures are actual billed amounts from the Azure Cost Management
    API for the coverage period, already net of any reserved instance,
    Azure Hybrid Benefit, or enterprise agreement discounts. The
    underlying inventory is from Azure Resource Graph. Stopped-VM cost
    includes VM compute + OS disk only; attached data disks bill
    separately and are listed in the Data Disks column.
    Generated by <code>stratusscan-azure</code>.
  </div>
</body>
</html>
"""


def _default_period_label() -> str:
    """Human-readable label for the previous full calendar month."""
    today = datetime.now(timezone.utc).date()
    first_this = today.replace(day=1)
    last_prev = first_this.replace(day=1)
    from datetime import timedelta
    last_prev = first_this - timedelta(days=1)
    return last_prev.strftime("%B %Y")
