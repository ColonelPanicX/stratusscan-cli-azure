#!/usr/bin/env python3
"""StratusScanCLI-Azure — AKS Clusters Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("aks-clusters-export")
utils.log_script_start("aks_clusters_export.py", "Azure Kubernetes Service Clusters Export")

log = utils.get_logger()


def collect_clusters(subscription_id: str) -> list:
    client = utils.get_azure_client("containerservice", subscription_id)
    log.info("Listing all AKS clusters in subscription %s", subscription_id)
    return list(client.managed_clusters.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("containerservice", environment):
        sys.exit(0)

    clusters = collect_clusters(subscription_id)
    if not clusters:
        print("No AKS clusters found.")
        return

    rows = []
    for cluster in clusters:
        rg = utils.extract_resource_group(cluster.id)
        tags = cluster.tags or {}
        agent_pools = cluster.agent_pool_profiles or []
        total_nodes = sum(p.count or 0 for p in agent_pools)
        node_vm_sizes = ", ".join({p.vm_size or "" for p in agent_pools if p.vm_size})
        rows.append({
            "Name": cluster.name,
            "Resource Group": rg,
            "Location": cluster.location,
            "Kubernetes Version": cluster.kubernetes_version or "",
            "Provisioning State": cluster.provisioning_state or "",
            "Power State": str(cluster.power_state.code) if cluster.power_state else "",
            "Node Count": total_nodes,
            "Node VM Sizes": node_vm_sizes,
            "Agent Pool Count": len(agent_pools),
            "RBAC Enabled": cluster.enable_rbac,
            "Network Plugin": (
                cluster.network_profile.network_plugin
                if cluster.network_profile else ""
            ),
            "DNS Prefix": cluster.dns_prefix or "",
            "FQDN": cluster.fqdn or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "aks-clusters", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="AKS Clusters")
    print(f"Exported {len(rows)} AKS cluster(s) → {filename}")
    log.info("Export complete: %d clusters", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
