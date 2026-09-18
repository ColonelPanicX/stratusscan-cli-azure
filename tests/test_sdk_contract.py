"""Offline SDK contract tests — assert the installed Azure SDKs still expose what the exporters call.

No credentials and no network. Every test skips cleanly when its SDK package is absent,
so the suite still runs on a machine with no Azure packages installed.
"""

import importlib
import inspect

import pytest

import utils

_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"


class _OfflineCredential:
    def get_token(self, *scopes, **kwargs):
        raise AssertionError("contract tests must not request a token")

    def get_token_info(self, *scopes, **kwargs):
        raise AssertionError("contract tests must not request a token")


def _client(service):
    module_path, class_name, needs_sub = utils._CLIENT_MAP[service]
    cls = getattr(pytest.importorskip(module_path), class_name)
    if needs_sub:
        return cls(_OfflineCredential(), _SUBSCRIPTION_ID)
    return cls(_OfflineCredential())


@pytest.mark.parametrize("service", sorted(utils._CLIENT_MAP))
def test_client_map_entry_resolves_to_a_real_class(service):
    module_path, class_name, _ = utils._CLIENT_MAP[service]
    module = pytest.importorskip(module_path)
    assert hasattr(module, class_name), f"{module_path} has no {class_name}"


@pytest.mark.parametrize("service", sorted(utils._CLIENT_MAP))
def test_client_map_module_maps_to_an_installed_distribution(service):
    from importlib.metadata import version

    module_path, _, _ = utils._CLIENT_MAP[service]
    pytest.importorskip(module_path)
    assert version("-".join(module_path.split(".")[:3]))


@pytest.mark.parametrize("service", sorted(utils._CLIENT_MAP))
def test_government_client_honors_the_scope_and_endpoint_it_is_given(service, monkeypatch):
    """No credential wrapper rewrites scopes any more — every client must take them from kwargs."""
    module_path, _, needs_sub = utils._CLIENT_MAP[service]
    pytest.importorskip(module_path)
    monkeypatch.setattr(utils, "_get_credential", lambda: _OfflineCredential())
    monkeypatch.setattr(utils, "detect_environment", lambda: "government")

    client = utils.get_azure_client(service, _SUBSCRIPTION_ID if needs_sub else None)

    assert client._config.credential_scopes == ["https://management.core.usgovcloudapi.net/.default"]
    # newer generated clients keep the host on _config and template the pipeline URL as "{endpoint}"
    base_url = getattr(client._config, "base_url", None) or client._client._base_url
    assert base_url.rstrip("/") == "https://management.usgovcloudapi.net"


def test_government_scope_matches_the_sdk_cloud_definition():
    core = pytest.importorskip("azure.core")
    tools = pytest.importorskip("azure.mgmt.core.tools")
    if not hasattr(tools, "get_arm_endpoints"):
        pytest.skip("azure-mgmt-core predates get_arm_endpoints")
    endpoints = tools.get_arm_endpoints(core.AzureClouds.AZURE_US_GOVERNMENT)
    assert endpoints["credential_scopes"] == [utils._GOV_ARM_SCOPE]
    assert endpoints["resource_manager"].rstrip("/") == utils._GOV_BASE_URL


def test_government_credential_is_a_plain_default_credential(monkeypatch):
    identity = pytest.importorskip("azure.identity")
    monkeypatch.setattr(utils, "_credential_cache", None)
    monkeypatch.setattr(utils, "detect_environment", lambda: "government")

    credential = utils._get_credential()

    assert isinstance(credential, identity.DefaultAzureCredential)
    assert callable(getattr(credential, "get_token_info", None))
    assert callable(getattr(credential, "close", None))


@pytest.mark.parametrize(
    "service, operation_group, method",
    [
        ("network", "network_security_groups", "list_all"),
        ("network", "firewall_policies", "list_all"),
        ("network", "virtual_wans", "list"),
        ("network", "virtual_hubs", "list"),
        ("security", "secure_scores", "list"),
        ("security", "pricings", "list"),
        ("monitor", "diagnostic_settings", "list"),
        ("monitor", "metric_alerts", "list_by_subscription"),
        ("monitor", "action_groups", "list_by_subscription_id"),
        ("monitor", "activity_log_alerts", "list_by_subscription_id"),
        ("managementgroups", "management_groups", "list"),
        ("managementgroups", "management_groups", "get"),
        ("resource", "resources", "list"),
        ("policy", "policy_definitions", "list"),
        ("apimanagement", "api_management_service", "list"),
        ("eventhub", "namespaces", "list"),
        ("logic", "workflows", "list_by_subscription"),
        ("mysql", "servers", "list"),
        ("postgresql", "servers", "list_by_subscription"),
        ("redis", "redis", "list_by_subscription"),
        ("keyvault", "vaults", "list_by_subscription"),
        ("policyinsights", "policy_states", "list_query_results_for_subscription"),
        ("policyinsights", "policy_states", "summarize_for_subscription"),
        ("monitor", "subscription_diagnostic_settings", "list"),
        ("web", "web_apps", "get_configuration"),
        ("costmanagement", "query", "usage"),
        ("storage", "blob_containers", "list"),
        ("storage", "file_shares", "list"),
        ("authorization", "role_definitions", "list"),
        ("network", "flow_logs", "list"),
        ("network", "network_watchers", "list_all"),
        ("network", "virtual_networks", "list_all"),
        ("security", "alerts", "list"),
        ("security", "regulatory_compliance_standards", "list"),
        ("security", "regulatory_compliance_controls", "list"),
    ],
)
def test_operation_group_and_method_exist(service, operation_group, method):
    client = _client(service)
    group = getattr(client, operation_group, None)
    assert group is not None, f"{service} client has no operation group {operation_group}"
    assert callable(getattr(group, method, None)), f"{service}.{operation_group} has no {method}"


def test_nsg_rule_direction_compares_correctly_through_utils_s():
    models = pytest.importorskip("azure.mgmt.network.models")
    rule = models.SecurityRule(
        {"name": "r1", "properties": {"direction": "Inbound", "access": "Allow", "protocol": "Tcp"}}
    )
    assert utils.s(rule.direction).lower() == "inbound"
    assert utils.s(rule.access) == "Allow"
    assert utils.s(rule.protocol) == "Tcp"


def test_firewall_network_rule_protocols_render_as_values():
    models = pytest.importorskip("azure.mgmt.network.models")
    rule = models.NetworkRule({"ruleType": "NetworkRule", "name": "n", "ipProtocols": ["TCP", "UDP"]})
    assert ", ".join(utils.s(p) for p in rule.ip_protocols) == "TCP, UDP"
    assert {"NetworkRule": "hit"}.get(rule.rule_type) == "hit"


def test_virtual_wan_type_lives_under_properties():
    models = pytest.importorskip("azure.mgmt.network.models")
    wan = models.VirtualWAN(
        {
            "name": "wan1",
            "type": "Microsoft.Network/virtualWans",
            "properties": {"type": "Standard", "office365LocalBreakoutCategory": "None"},
        }
    )
    assert utils.s(getattr(getattr(wan, "properties", None), "type", None)) == "Standard"
    assert utils.s(wan.office365_local_breakout_category) == "None"
    assert wan.type == "Microsoft.Network/virtualWans"


def test_secure_score_item_exposes_top_level_score_fields():
    models = pytest.importorskip("azure.mgmt.security.models")
    item = models.SecureScoreItem.deserialize(
        {
            "name": "ascScore",
            "properties": {
                "displayName": "ASC score",
                "score": {"max": 58, "current": 24.5, "percentage": 0.4224},
                "weight": 199,
            },
        }
    )
    assert (item.current, item.max, item.percentage, item.weight) == (24.5, 58, 0.4224, 199)
    assert item.display_name == "ASC score"
    assert not hasattr(item, "score")


def test_secure_score_item_absent_values_are_none_not_zero():
    models = pytest.importorskip("azure.mgmt.security.models")
    item = models.SecureScoreItem.deserialize({"name": "ascScore", "properties": {}})
    assert (item.current, item.max, item.percentage, item.weight) == (None, None, None, None)


def test_pricings_list_requires_scope_id_and_returns_a_pricing_list():
    client = _client("security")
    parameters = inspect.signature(client.pricings.list).parameters
    assert "scope_id" in parameters
    assert parameters["scope_id"].default is inspect.Parameter.empty
    pricing_list = client.pricings.models.PricingList.deserialize(
        {"value": [{"name": "VirtualMachines", "properties": {"pricingTier": "Standard"}}]}
    )
    assert [utils.s(p.pricing_tier) for p in pricing_list.value] == ["Standard"]


def test_pricings_scope_id_must_not_carry_a_leading_slash():
    operations = importlib.import_module(type(_client("security").pricings).__module__)
    request = operations.build_list_request(scope_id=f"subscriptions/{_SUBSCRIPTION_ID}")
    path = request.url.split("?")[0]
    assert path == f"/subscriptions/{_SUBSCRIPTION_ID}/providers/Microsoft.Security/pricings"


def test_diagnostic_settings_list_returns_a_pager_without_a_value_attribute():
    paging = pytest.importorskip("azure.core.paging")
    client = _client("monitor")
    result = client.diagnostic_settings.list(
        f"/subscriptions/{_SUBSCRIPTION_ID}/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa"
    )
    assert isinstance(result, paging.ItemPaged)
    assert not hasattr(result, "value")


def test_role_definitions_list_takes_scope_and_an_optional_type_filter():
    parameters = inspect.signature(_client("authorization").role_definitions.list).parameters
    assert parameters["scope"].default is inspect.Parameter.empty
    assert "filter" in parameters and parameters["filter"].default is None


def test_role_definition_permissions_and_audit_fields_live_where_the_exporter_reads_them():
    models = pytest.importorskip("azure.mgmt.authorization.v2022_04_01.models")
    role = models.RoleDefinition.deserialize(
        {
            "name": "acdd72a7-3385-48ef-bd42-f606fba81ae7",
            "properties": {
                "roleName": "Reader", "type": "BuiltInRole", "description": "d",
                "assignableScopes": ["/"],
                "permissions": [{"actions": ["*/read"], "notActions": ["Microsoft.Support/*"],
                                 "dataActions": [], "notDataActions": []}],
                "createdOn": "2015-06-02T00:18:27.3542039Z", "createdBy": "u1",
            },
        }
    )
    assert (role.role_name, role.role_type, role.created_by) == ("Reader", "BuiltInRole", "u1")
    assert role.permissions[0].actions == ["*/read"]
    assert role.permissions[0].not_actions == ["Microsoft.Support/*"]
    assert role.created_on.year == 2015


def test_flow_logs_list_takes_the_resource_group_and_watcher_name():
    parameters = inspect.signature(_client("network").flow_logs.list).parameters
    assert list(parameters)[:2] == ["resource_group_name", "network_watcher_name"]
    assert all(parameters[name].default is inspect.Parameter.empty
               for name in ("resource_group_name", "network_watcher_name"))


def test_flow_log_nested_properties_read_through_the_flattened_model():
    models = pytest.importorskip("azure.mgmt.network.models")
    flow_log = models.FlowLog(
        {
            "name": "fl1", "location": "eastus",
            "properties": {
                "targetResourceId": "/subscriptions/s/resourceGroups/rg/providers/"
                                    "Microsoft.Network/networkSecurityGroups/nsg1",
                "storageId": "/subscriptions/s/resourceGroups/rg/providers/"
                             "Microsoft.Storage/storageAccounts/sa",
                "enabled": True,
                "retentionPolicy": {"days": 30, "enabled": True},
                "format": {"type": "JSON", "version": 2},
                "flowAnalyticsConfiguration": {
                    "networkWatcherFlowAnalyticsConfiguration": {
                        "enabled": True, "workspaceRegion": "eastus",
                        "workspaceResourceId": "/subscriptions/s/resourceGroups/rg/providers/"
                                               "Microsoft.OperationalInsights/workspaces/ws",
                        "trafficAnalyticsInterval": 60,
                    }
                },
            },
        }
    )
    assert flow_log.enabled is True
    assert flow_log.retention_policy.days == 30
    assert utils.s(flow_log.format.type) == "JSON"
    analytics = flow_log.flow_analytics_configuration.network_watcher_flow_analytics_configuration
    assert analytics.enabled is True and analytics.traffic_analytics_interval == 60


def test_alert_carries_the_exported_fields_and_the_ones_deliberately_left_out():
    models = pytest.importorskip("azure.mgmt.security.v2022_01_01.models")
    alert = models.Alert.deserialize(
        {
            "name": "2518_a1",
            "properties": {
                "alertDisplayName": "Suspicious file", "severity": "High", "status": "Active",
                "intent": "Execution", "alertType": "VM_EICAR", "vendorName": "Microsoft",
                "compromisedEntity": "vm1", "remediationSteps": ["one", "two"],
                "timeGeneratedUtc": "2026-09-01T10:06:00.0000000Z",
                "resourceIdentifiers": [{"type": "AzureResource", "azureResourceId":
                                         "/subscriptions/s/resourceGroups/rg/providers/"
                                         "Microsoft.Compute/virtualMachines/vm1"}],
                "entities": [{"type": "host", "hostName": "vm1"}],
                "extendedProperties": {"compromised host": "vm1"},
            },
        }
    )
    assert alert.alert_display_name == "Suspicious file"
    assert alert.remediation_steps == ["one", "two"]
    assert alert.resource_identifiers[0].azure_resource_id.endswith("/virtualMachines/vm1")
    assert alert.entities and alert.extended_properties, "both exist; the exporter must not export them"


def test_regulatory_compliance_control_listing_takes_the_standard_name():
    parameters = inspect.signature(_client("security").regulatory_compliance_controls.list).parameters
    assert parameters["regulatory_compliance_standard_name"].default is inspect.Parameter.empty


def test_regulatory_compliance_counts_are_top_level_on_the_models():
    models = pytest.importorskip("azure.mgmt.security.v2019_01_01_preview.models")
    standard = models.RegulatoryComplianceStandard.deserialize(
        {"name": "PCI-DSS-v4", "properties": {"state": "Failed", "passedControls": 3,
                                              "failedControls": 4, "skippedControls": 0,
                                              "unsupportedControls": 1}}
    )
    control = models.RegulatoryComplianceControl.deserialize(
        {"name": "1.1.1", "properties": {"state": "Passed", "description": "d",
                                         "passedAssessments": 5, "failedAssessments": 0,
                                         "skippedAssessments": 2}}
    )
    assert (utils.s(standard.state), standard.passed_controls, standard.unsupported_controls) == ("Failed", 3, 1)
    assert (utils.s(control.state), control.passed_assessments, control.skipped_assessments) == ("Passed", 5, 2)


def test_subscription_diagnostic_setting_log_entries_carry_category_and_enabled():
    models = pytest.importorskip("azure.mgmt.monitor.models")
    setting = models.SubscriptionDiagnosticSettingsResource.deserialize(
        {
            "name": "ds1",
            "properties": {
                "workspaceId": "/subscriptions/s/resourceGroups/rg/providers/"
                               "Microsoft.OperationalInsights/workspaces/ws",
                "logs": [{"category": "Administrative", "enabled": True},
                         {"category": "Security", "enabled": False}],
            },
        }
    )
    assert [(entry.category, entry.enabled) for entry in setting.logs] == [
        ("Administrative", True), ("Security", False)
    ]
    assert setting.workspace_id.endswith("/workspaces/ws")
