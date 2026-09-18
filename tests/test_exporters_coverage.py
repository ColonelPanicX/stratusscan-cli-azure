"""Coverage-gap exporter tests (SSAZR-120 slice 1) — fake clients plus real SDK models, no live Azure."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import activity_log_settings_export  # noqa: E402
import defender_alerts_export  # noqa: E402
import flow_logs_export  # noqa: E402
import regulatory_compliance_export  # noqa: E402
import role_definitions_export  # noqa: E402

_SUB = "/subscriptions/00000000-0000-0000-0000-000000000001"
_NSG_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Network/networkSecurityGroups/nsg1"
_VNET_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1"
_SUBNET_ID = f"{_VNET_ID}/subnets/snet1"
_VM_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"


class _Response:
    def __init__(self, status_code=400, body=None):
        self.status_code = status_code
        self.headers = {}
        self.reason = "error"
        self._body = body or {"error": {"code": "Forbidden", "message": "denied"}}

    def json(self):
        return self._body

    def text(self, encoding=None):
        import json

        return json.dumps(self._body)


def _http_error(code="Forbidden", status=403):
    from azure.core.exceptions import HttpResponseError

    return HttpResponseError(response=_Response(status, {"error": {"code": code, "message": "m"}}))


def _patch_client(monkeypatch, module, client):
    monkeypatch.setattr(module.utils, "get_azure_client", lambda service, sub_id=None: client)


# --- role definitions ------------------------------------------------------------


def _permission(actions=(), not_actions=(), data_actions=(), not_data_actions=()):
    return SimpleNamespace(
        actions=list(actions), not_actions=list(not_actions),
        data_actions=list(data_actions), not_data_actions=list(not_data_actions),
    )


def _role(name="guid-1", role_name="Reader", role_type="BuiltInRole", permissions=None, **extra):
    fields = {
        "name": name, "role_name": role_name, "role_type": role_type,
        "description": "desc", "assignable_scopes": [_SUB],
        "permissions": permissions if permissions is not None else [_permission(["*/read"])],
        "created_on": None, "updated_on": None, "created_by": "",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def test_role_definitions_split_custom_from_built_in():
    custom, builtin = role_definitions_export.split_rows([
        _role(name="c1", role_name="Billing Reader Plus", role_type="CustomRole"),
        _role(name="b1", role_name="Reader", role_type="BuiltInRole"),
        _role(name="c2", role_name="Ops", role_type="customrole"),
    ])
    assert [row["Name"] for row in custom] == ["Billing Reader Plus", "Ops"]
    assert [row["Role ID"] for row in builtin] == ["b1"]
    assert builtin[0]["Type"] == "BuiltInRole"


def test_role_definitions_join_every_permission_block():
    role = _role(permissions=[
        _permission(["A/read", "B/read"], ["C/write"]),
        _permission(["D/read"], [], ["E/data/read"], ["F/data/write"]),
    ])
    (row,) = role_definitions_export.split_rows([role])[1]
    assert row["Actions"] == "A/read, B/read, D/read"
    assert row["NotActions"] == "C/write"
    assert row["DataActions"] == "E/data/read"
    assert row["NotDataActions"] == "F/data/write"


def test_role_definitions_truncate_at_the_excel_cell_limit():
    action = "Microsoft.VeryLongProviderName/resources/read"
    role = _role(permissions=[_permission([action] * 2000)])
    (row,) = role_definitions_export.split_rows([role])[1]
    assert len(row["Actions"]) == role_definitions_export.CELL_CHARACTER_LIMIT
    assert row["Actions"].endswith(role_definitions_export.TRUNCATION_MARKER)


def test_role_definitions_read_a_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.authorization.v2022_04_01.models")
    role = models.RoleDefinition.deserialize({
        "name": "acdd72a7-3385-48ef-bd42-f606fba81ae7",
        "properties": {
            "roleName": "Reader", "type": "BuiltInRole", "description": "View everything",
            "assignableScopes": ["/"],
            "permissions": [{"actions": ["*/read"], "notActions": [],
                             "dataActions": [], "notDataActions": []}],
            "createdOn": "2015-06-02T00:18:27.3542039Z",
            "updatedOn": "2021-11-11T20:13:54.9397456Z",
            "createdBy": "admin@example.com",
        },
    })
    custom, builtin = role_definitions_export.split_rows([role])
    assert custom == []
    (row,) = builtin
    assert row["Name"] == "Reader"
    assert row["Role ID"] == "acdd72a7-3385-48ef-bd42-f606fba81ae7"
    assert row["Actions"] == "*/read"
    assert row["Assignable Scopes"] == "/"
    assert row["Created On"].startswith("2015-06-02")
    assert row["Created By"] == "admin@example.com"


def test_role_definitions_empty_listing_is_no_resources_found(monkeypatch):
    _patch_client(monkeypatch, role_definitions_export,
                  SimpleNamespace(role_definitions=SimpleNamespace(list=lambda scope: iter(()))))
    with pytest.raises(role_definitions_export.utils.NoResourcesFound):
        role_definitions_export.main("00000000-0000-0000-0000-000000000001", "Sub")


# --- activity log settings -------------------------------------------------------


def _log(category, enabled=True):
    return SimpleNamespace(category=category, category_group=None, enabled=enabled)


def _activity_setting(name="ds1", categories=(("Administrative", True),), **extra):
    fields = {
        "name": name,
        "logs": [_log(c, e) for c, e in categories],
        "workspace_id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.OperationalInsights/workspaces/ws1",
        "storage_account_id": None,
        "event_hub_authorization_rule_id": None,
        "event_hub_name": None,
        "marketplace_partner_id": None,
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def test_activity_log_zero_settings_is_a_finding_row_not_an_empty_export(monkeypatch):
    client = SimpleNamespace(subscription_diagnostic_settings=SimpleNamespace(list=lambda: iter(())))
    _patch_client(monkeypatch, activity_log_settings_export, client)
    saved = {}
    monkeypatch.setattr(
        activity_log_settings_export.utils, "save_multiple_dataframes_to_excel",
        lambda sheets, filename, **kwargs: saved.update(sheets) or filename,
    )

    result = activity_log_settings_export.main("00000000-0000-0000-0000-000000000001", "Sub")

    settings_sheet = saved["Activity Log Settings"]
    assert len(settings_sheet) == 1
    assert settings_sheet.iloc[0]["Setting Name"] == "(none)"
    assert settings_sheet.iloc[0]["Assessment"] == activity_log_settings_export.NO_SETTINGS_FINDING
    assert list(saved["Assessment"]["Exported"]) == ["No", "No", "No"]
    assert result.rows == 0 and result.errors == []


def test_activity_log_assessment_names_the_categories_and_destinations():
    settings = [
        _activity_setting("ds-admin", (("Administrative", True), ("Security", False))),
        _activity_setting(
            "ds-policy", (("Policy", True),),
            workspace_id=None,
            storage_account_id=f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1",
        ),
    ]
    rows = {row["Category"]: row for row in activity_log_settings_export.build_assessment_rows(settings)}
    assert rows["Administrative"]["Exported"] == "Yes"
    assert rows["Administrative"]["Destinations"] == "LogAnalytics:ws1"
    assert rows["Policy"]["Settings"] == "ds-policy"
    assert rows["Policy"]["Destinations"] == "Storage:sa1"
    assert rows["Security"]["Exported"] == "No" and rows["Security"]["Settings"] == ""


def test_activity_log_event_hub_namespace_is_parsed_from_the_rule_id():
    rule = (f"{_SUB}/resourceGroups/rg1/providers/Microsoft.EventHub/namespaces/ns1"
            "/authorizationrules/RootManageSharedAccessKey")
    setting = _activity_setting("ds-eh", (("Security", True),), workspace_id=None,
                                event_hub_authorization_rule_id=rule, event_hub_name="hub1")
    (row,) = activity_log_settings_export.build_rows([setting])
    assert row["Event Hub Namespace"] == "ns1"
    assert row["Destinations"] == "EventHub:hub1"
    assert row["Assessment"].startswith("Exports Security → EventHub:hub1")


def test_activity_log_setting_without_an_audit_category_says_so():
    (row,) = activity_log_settings_export.build_rows([
        _activity_setting("ds-alerts", (("Alert", True), ("Autoscale", True)))
    ])
    assert row["Log Categories"] == "Alert, Autoscale"
    assert row["Assessment"] == "No audit category (Administrative, Security, Policy) enabled"


# --- flow logs -------------------------------------------------------------------


class _FakeNetwork:
    def __init__(self, per_watcher, watchers=(), nsgs=(), vnets=()):
        self.network_watchers = SimpleNamespace(list_all=lambda: iter(watchers))
        self.flow_logs = SimpleNamespace(list=self._list)
        self.network_security_groups = SimpleNamespace(list_all=lambda: iter(nsgs))
        self.virtual_networks = SimpleNamespace(list_all=lambda: iter(vnets))
        self._per_watcher = per_watcher
        self.calls = []

    def _list(self, resource_group_name, network_watcher_name):
        self.calls.append((resource_group_name, network_watcher_name))
        answer = self._per_watcher(network_watcher_name)
        if isinstance(answer, Exception):
            raise answer
        return iter(answer)


def _watcher(name="nw1", rg="NetworkWatcherRG"):
    return SimpleNamespace(
        id=f"{_SUB}/resourceGroups/{rg}/providers/Microsoft.Network/networkWatchers/{name}",
        name=name,
    )


def _named(resource_id):
    return SimpleNamespace(id=resource_id, name=resource_id.rstrip("/").split("/")[-1])


def _sdk_flow_log(name, target_id, enabled=True):
    models = pytest.importorskip("azure.mgmt.network.models")
    return models.FlowLog({
        "id": f"{_SUB}/resourceGroups/NetworkWatcherRG/providers/Microsoft.Network"
              f"/networkWatchers/nw1/flowLogs/{name}",
        "name": name,
        "location": "eastus",
        "properties": {
            "targetResourceId": target_id,
            "storageId": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1",
            "enabled": enabled,
            "retentionPolicy": {"days": 30, "enabled": True},
            "format": {"type": "JSON", "version": 2},
            "flowAnalyticsConfiguration": {"networkWatcherFlowAnalyticsConfiguration": {
                "enabled": True,
                "workspaceRegion": "eastus",
                "workspaceResourceId": f"{_SUB}/resourceGroups/rg1/providers"
                                       "/Microsoft.OperationalInsights/workspaces/ws1",
                "trafficAnalyticsInterval": 60,
            }},
            "provisioningState": "Succeeded",
        },
    })


def test_flow_log_rows_come_off_a_real_sdk_model():
    client = _FakeNetwork(lambda nw: [_sdk_flow_log("fl-nsg", _NSG_ID)], watchers=[_watcher()])
    rows = flow_logs_export.collect_flow_logs(client, [_watcher()], [])
    (row,) = rows
    assert client.calls == [("NetworkWatcherRG", "nw1")]
    assert row["Flow Log Type"] == "NSG (retires 09.30.2027)"
    assert row["Target Type"] == "Microsoft.Network/networkSecurityGroups"
    assert row["Target Name"] == "nsg1"
    assert row["Resource Group"] == "NetworkWatcherRG"
    assert row["Enabled"] == "Yes"
    assert row["Retention Days"] == "30" and row["Retention Enabled"] == "Yes"
    assert row["Format"] == "JSON" and row["Format Version"] == "2"
    assert row["Traffic Analytics Enabled"] == "Yes"
    assert row["Traffic Analytics Workspace"] == "ws1"
    assert row["Traffic Analytics Interval (min)"] == "60"
    assert row["Provisioning State"] == "Succeeded"


def test_flow_log_type_follows_the_target_resource_type():
    assert flow_logs_export.flow_log_type("Microsoft.Network/virtualNetworks") == "VNet"
    assert flow_logs_export.flow_log_type("Microsoft.Network/virtualNetworks/subnets") == "VNet"
    assert flow_logs_export.flow_log_type("Microsoft.Network/networkInterfaces") == "VNet"
    assert flow_logs_export.flow_log_type("Microsoft.Compute/virtualMachines") == ""


def test_flow_log_watcher_error_is_recorded_and_the_run_continues():
    def answer(name):
        return _http_error("AuthorizationFailed", 403) if name == "nw-bad" else [
            _sdk_flow_log("fl1", _NSG_ID)
        ]

    watchers = [_watcher("nw-bad"), _watcher("nw1")]
    errors = []
    rows = flow_logs_export.collect_flow_logs(_FakeNetwork(answer), watchers, errors)
    assert len(rows) == 1
    assert [(e["Operation"], e["Error Code"]) for e in errors] == [
        ("flow_logs.list", "AuthorizationFailed")
    ]


def test_flow_log_coverage_flags_uncovered_nsgs_and_subnet_scoped_vnets():
    rows = [
        {"Name": "fl-subnet", "Target Resource ID": _SUBNET_ID, "Enabled": "Yes"},
        {"Name": "fl-off", "Target Resource ID": _NSG_ID, "Enabled": "No"},
    ]
    client = _FakeNetwork(lambda nw: [], nsgs=[_named(_NSG_ID)], vnets=[_named(_VNET_ID)])
    coverage = flow_logs_export.build_coverage_rows(client, rows, [])
    by_name = {row["Name"]: row for row in coverage}
    assert by_name["nsg1"]["Flow Log"] == "None"
    assert by_name["vnet1"]["Flow Log"] == "fl-subnet"
    assert by_name["vnet1"]["Flow Log Target"] == _SUBNET_ID


def test_flow_log_coverage_listing_failure_is_recorded():
    def boom():
        raise _http_error("AuthorizationFailed", 403)

    client = _FakeNetwork(lambda nw: [], nsgs=[], vnets=[])
    client.network_security_groups = SimpleNamespace(list_all=boom)
    errors = []
    coverage = flow_logs_export.build_coverage_rows(client, [], errors)
    assert coverage == []
    assert [e["Operation"] for e in errors] == ["network_security_groups.list_all"]


def test_flow_logs_without_watchers_is_no_resources_found(monkeypatch):
    _patch_client(monkeypatch, flow_logs_export, _FakeNetwork(lambda nw: []))
    with pytest.raises(flow_logs_export.utils.NoResourcesFound):
        flow_logs_export.main("00000000-0000-0000-0000-000000000001", "Sub")


# --- defender alerts -------------------------------------------------------------


def _sdk_alert(**properties):
    models = pytest.importorskip("azure.mgmt.security.v2022_01_01.models")
    body = {
        "alertDisplayName": "Suspicious file detected",
        "severity": "High",
        "status": "Active",
        "intent": "Execution",
        "alertType": "VM_EICAR",
        "description": "A suspicious file was executed",
        "remediationSteps": ["Isolate the machine", "Run a scan"],
        "vendorName": "Microsoft",
        "productName": "Microsoft Defender for Cloud",
        "compromisedEntity": "vm1",
        "isIncident": False,
        "systemAlertId": "2518298467986649999_a1b2",
        "alertUri": "https://portal.azure.com/alert",
        "timeGeneratedUtc": "2026-09-01T10:06:00.0000000Z",
        "startTimeUtc": "2026-09-01T10:00:00.0000000Z",
        "endTimeUtc": "2026-09-01T10:05:00.0000000Z",
        "resourceIdentifiers": [{"type": "AzureResource", "azureResourceId": _VM_ID}],
        "entities": [{"type": "file", "directory": "/home/user", "name": "eicar.com"}],
        "extendedProperties": {"compromised host": "vm1", "command line": "curl http://evil"},
    }
    body.update(properties)
    return models.Alert.deserialize({"name": "alert-1", "properties": body})


def test_defender_alert_row_from_a_real_sdk_model(monkeypatch):
    alert = _sdk_alert()
    _patch_client(monkeypatch, defender_alerts_export,
                  SimpleNamespace(alerts=SimpleNamespace(list=lambda: iter([alert]))))
    (row,) = defender_alerts_export.collect_alerts("00000000-0000-0000-0000-000000000001")
    assert row["Alert Display Name"] == "Suspicious file detected"
    assert row["Severity"] == "High" and row["Status"] == "Active" and row["Intent"] == "Execution"
    assert row["Resource ID"] == _VM_ID
    assert row["Resource Name"] == "vm1"
    assert row["Resource Type"] == "Microsoft.Compute/virtualMachines"
    assert row["Remediation Steps"] == "Isolate the machine | Run a scan"
    assert row["Detected Time"].startswith("2026-09-01T10:06")
    assert row["Is Incident"] == "No"


def test_defender_alert_never_exports_entities_or_extended_properties(monkeypatch):
    alert = _sdk_alert()
    _patch_client(monkeypatch, defender_alerts_export,
                  SimpleNamespace(alerts=SimpleNamespace(list=lambda: iter([alert]))))
    (row,) = defender_alerts_export.collect_alerts("00000000-0000-0000-0000-000000000001")
    serialized = " ".join(str(value) for value in row.values())
    assert "eicar.com" not in serialized
    assert "curl http://evil" not in serialized
    assert "Entities" not in row and "Extended Properties" not in row


def test_defender_alert_without_an_azure_resource_identifier_leaves_the_columns_blank(monkeypatch):
    alert = _sdk_alert(resourceIdentifiers=[{
        "type": "LogAnalytics",
        "workspaceId": "f0000000-0000-0000-0000-000000000000",
        "workspaceSubscriptionId": "00000000-0000-0000-0000-000000000001",
        "workspaceResourceGroup": "rg1",
        "agentId": "a0000000-0000-0000-0000-000000000000",
    }])
    _patch_client(monkeypatch, defender_alerts_export,
                  SimpleNamespace(alerts=SimpleNamespace(list=lambda: iter([alert]))))
    (row,) = defender_alerts_export.collect_alerts("00000000-0000-0000-0000-000000000001")
    assert row["Resource ID"] == "" and row["Resource Name"] == "" and row["Resource Type"] == ""
    assert row["Compromised Entity"] == "vm1"


def test_defender_alerts_empty_listing_is_no_resources_found(monkeypatch):
    _patch_client(monkeypatch, defender_alerts_export,
                  SimpleNamespace(alerts=SimpleNamespace(list=lambda: iter(()))))
    with pytest.raises(defender_alerts_export.utils.NoResourcesFound):
        defender_alerts_export.main("00000000-0000-0000-0000-000000000001", "Sub")


# --- regulatory compliance -------------------------------------------------------


class _FakeSecurity:
    def __init__(self, standards, per_standard):
        self.regulatory_compliance_standards = SimpleNamespace(list=lambda: iter(standards))
        self.regulatory_compliance_controls = SimpleNamespace(list=self._list)
        self._per_standard = per_standard

    def _list(self, standard_name):
        answer = self._per_standard(standard_name)
        if isinstance(answer, Exception):
            raise answer
        return iter(answer)


def _standard(name, state="Failed", passed=3, failed=4, skipped=0, unsupported=1):
    return SimpleNamespace(
        name=name, state=state, passed_controls=passed, failed_controls=failed,
        skipped_controls=skipped, unsupported_controls=unsupported,
    )


def _control(name, state="Passed"):
    return SimpleNamespace(
        name=name, state=state, description="control description",
        passed_assessments=5, failed_assessments=0, skipped_assessments=2,
    )


def test_regulatory_compliance_controls_are_keyed_to_their_standard():
    client = _FakeSecurity(
        [_standard("FedRAMP-H"), _standard("NIST-SP-800-53-R5")],
        lambda name: [_control(f"{name}-AC-1")],
    )
    standards = regulatory_compliance_export.collect_standards(client)
    errors = []
    rows = regulatory_compliance_export.collect_controls(client, standards, errors)
    assert [(row["Standard"], row["Control"]) for row in rows] == [
        ("FedRAMP-H", "FedRAMP-H-AC-1"), ("NIST-SP-800-53-R5", "NIST-SP-800-53-R5-AC-1"),
    ]
    assert rows[0]["Passed Assessments"] == "5" and rows[0]["Skipped Assessments"] == "2"
    assert errors == []


def test_regulatory_compliance_standard_failure_is_partial_not_fatal():
    def answer(name):
        return _http_error("Forbidden", 403) if name == "HIPAA" else [_control("AC-1")]

    client = _FakeSecurity([_standard("HIPAA"), _standard("FedRAMP-H")], answer)
    errors = []
    rows = regulatory_compliance_export.collect_controls(client, client.regulatory_compliance_standards.list(), errors)
    assert [row["Standard"] for row in rows] == ["FedRAMP-H"]
    assert [(e["Scope"], e["Operation"]) for e in errors] == [
        ("HIPAA", "regulatory_compliance_controls.list")
    ]


def test_regulatory_compliance_standard_row_carries_every_count():
    row = regulatory_compliance_export._standard_row(_standard("PCI-DSS-v4"))
    assert row == {
        "Standard": "PCI-DSS-v4", "State": "Failed", "Passed Controls": "3",
        "Failed Controls": "4", "Skipped Controls": "0", "Unsupported Controls": "1",
    }


def test_regulatory_compliance_without_standards_is_no_resources_found(monkeypatch):
    _patch_client(monkeypatch, regulatory_compliance_export, _FakeSecurity([], lambda name: []))
    with pytest.raises(regulatory_compliance_export.utils.NoResourcesFound):
        regulatory_compliance_export.main("00000000-0000-0000-0000-000000000001", "Sub")


# =================================================================================
# SSAZR-120 slice 2
# =================================================================================

import app_service_plans_export  # noqa: E402
import backup_items_export  # noqa: E402
import cognitive_services_export  # noqa: E402
import disk_encryption_sets_export  # noqa: E402
import waf_policies_export  # noqa: E402

_VAULT_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.RecoveryServices/vaults/vault1"
_DES_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Compute/diskEncryptionSets/des1"


def _patch_client_by_service(monkeypatch, module, clients):
    monkeypatch.setattr(
        module.utils, "get_azure_client", lambda service, sub_id=None: clients[service]
    )


# --- backup items ----------------------------------------------------------------


def _backup_model(class_name, payload):
    models = pytest.importorskip("azure.mgmt.recoveryservicesbackup.models")
    return getattr(models, class_name)(payload)


def _vault(name="vault1", **properties):
    props = {
        "provisioningState": "Succeeded",
        "publicNetworkAccess": "Enabled",
        "redundancySettings": {
            "standardTierStorageRedundancy": "GeoRedundant",
            "crossRegionRestore": "Enabled",
        },
        "securitySettings": {
            "immutabilitySettings": {"state": "Unlocked"},
            "multiUserAuthorization": "Enabled",
            "softDeleteSettings": {
                "softDeleteState": "Enabled", "softDeleteRetentionPeriodInDays": 14,
            },
        },
        "encryption": {
            "keyVaultProperties": {"keyUri": "https://kv1.vault.azure.net/keys/k1/v1"},
            "infrastructureEncryption": "Enabled",
            "kekIdentity": {"useSystemAssignedIdentity": True},
        },
    }
    props.update(properties)
    models = pytest.importorskip("azure.mgmt.recoveryservices.models")
    return models.Vault({
        "id": _VAULT_ID.replace("vault1", name), "name": name, "location": "eastus",
        "sku": {"name": "RS0", "tier": "Standard"}, "properties": props,
    })


class _FakeBackup:
    """Vault-scoped child listings; names in `failures` raise instead of answering."""

    def __init__(self, items=(), policies=(), config=None, failures=()):
        self._items = list(items)
        self._policies = list(policies)
        self._config = config
        self._failures = set(failures)
        self.calls = []
        self.backup_protected_items = SimpleNamespace(list=self._list_items)
        self.backup_policies = SimpleNamespace(list=self._list_policies)
        self.backup_resource_vault_configs = SimpleNamespace(get=self._get_config)

    def _answer(self, operation, vault_name, resource_group_name):
        self.calls.append((operation, vault_name, resource_group_name))
        if operation in self._failures:
            raise _http_error("AuthorizationFailed", 403)

    def _list_items(self, vault_name, resource_group_name):
        self._answer("items", vault_name, resource_group_name)
        return iter(self._items)

    def _list_policies(self, vault_name, resource_group_name):
        self._answer("policies", vault_name, resource_group_name)
        return iter(self._policies)

    def _get_config(self, vault_name, resource_group_name):
        self._answer("config", vault_name, resource_group_name)
        return self._config


def _protected_item(name="vm;i1", item_type="Microsoft.Compute/virtualMachines", **overrides):
    props = {
        "protectedItemType": item_type,
        "friendlyName": "vm1",
        "protectionState": "Protected",
        "protectionStatus": "Healthy",
        "healthStatus": "Passed",
        "lastBackupStatus": "Healthy",
        "lastBackupTime": "2026-09-01T02:00:00Z",
        "lastRecoveryPoint": "2026-09-01T02:30:00Z",
        "policyName": "DefaultPolicy",
        "backupManagementType": "AzureIaasVM",
        "workloadType": "VM",
        "containerName": "iaasvmcontainerv2;rg1;vm1",
        "sourceResourceId": _VM_ID,
        "isArchiveEnabled": False,
        "isScheduledForDeferredDelete": False,
        "softDeleteRetentionPeriodInDays": 14,
    }
    props.update(overrides)
    return _backup_model("ProtectedItemResource", {"name": name, "properties": props})


def _protection_policy(name="DefaultPolicy"):
    return _backup_model("ProtectionPolicyResource", {"name": name, "properties": {
        "backupManagementType": "AzureIaasVM", "policyType": "V2", "timeZone": "UTC",
        "protectedItemsCount": 3, "instantRpRetentionRangeInDays": 2,
        "schedulePolicy": {"schedulePolicyType": "SimpleSchedulePolicy",
                           "scheduleRunFrequency": "Daily",
                           "scheduleRunTimes": ["2026-09-01T18:30:00Z"]},
        "retentionPolicy": {
            "retentionPolicyType": "LongTermRetentionPolicy",
            "dailySchedule": {"retentionDuration": {"count": 30, "durationType": "Days"}},
            "weeklySchedule": {"daysOfTheWeek": ["Sunday"],
                               "retentionDuration": {"count": 12, "durationType": "Weeks"}},
            "monthlySchedule": {"retentionDuration": {"count": 60, "durationType": "Months"}},
            "yearlySchedule": {"monthsOfYear": ["January"],
                               "retentionDuration": {"count": 10, "durationType": "Years"}},
        },
    }})


def _vault_config():
    return _backup_model("BackupResourceVaultConfigResource", {"name": "vaultconfig", "properties": {
        "storageType": "GeoRedundant", "storageTypeState": "Locked",
        "softDeleteFeatureState": "Enabled", "softDeleteRetentionPeriodInDays": 14,
        "enhancedSecurityState": "Enabled",
    }})


def test_backup_item_row_resolves_the_nested_protected_item_discriminator():
    row = backup_items_export.build_item_row(_protected_item(), "vault1", "rg1")
    assert row["Friendly Name"] == "vm1"
    assert row["Protection State"] == "Protected"
    assert row["Protection Status"] == "Healthy"
    assert row["Health Status"] == "Passed"
    assert row["Last Backup Status"] == "Healthy"
    assert row["Last Backup Time"] == "2026-09-01 02:00:00"
    assert row["Latest Recovery Point"] == "2026-09-01 02:30:00"
    assert row["Policy Name"] == "DefaultPolicy"
    assert row["Protected Item Type"] == "Microsoft.Compute/virtualMachines"
    assert row["Source Resource ID"] == _VM_ID
    assert row["Archive Enabled"] == "No"


def test_backup_item_row_reads_a_first_level_subtype_unchanged():
    row = backup_items_export.build_item_row(
        _protected_item(name="fs;i2", item_type="AzureFileShareProtectedItem",
                        backupManagementType="AzureStorage", workloadType="AzureFileShare"),
        "vault1", "rg1",
    )
    assert row["Friendly Name"] == "vm1"
    assert row["Backup Management Type"] == "AzureStorage"


def test_backup_policy_row_carries_schedule_and_every_retention_tier():
    row = backup_items_export.build_policy_row(_protection_policy(), "vault1", "rg1")
    assert row["Schedule"] == "Daily | 2026-09-01 18:30:00"
    assert row["Daily Retention"] == "30 Days"
    assert row["Weekly Retention"] == "12 Weeks | Sunday"
    assert row["Monthly Retention"] == "60 Months"
    assert row["Yearly Retention"] == "10 Years | January"
    assert row["Instant Restore Retention (days)"] == "2"
    assert row["Protected Items Count"] == "3"


def test_backup_vault_row_reports_redundancy_soft_delete_immutability_and_cmk():
    client = _FakeBackup(items=[_protected_item()], policies=[_protection_policy()],
                          config=_vault_config())
    vault_rows, item_rows, policy_rows = backup_items_export.collect_vault_children(
        client, [_vault()], []
    )
    (row,) = vault_rows
    assert row["Name"] == "vault1" and row["Resource Group"] == "rg1"
    assert row["Storage Type"] == "GeoRedundant"
    assert row["Cross Region Restore"] == "Enabled"
    assert row["Soft Delete State"] == "Enabled"
    assert row["Soft Delete Retention (days)"] == "14"
    assert row["Immutability State"] == "Unlocked"
    assert row["Encryption Key Source"] == "Microsoft.KeyVault"
    assert row["Encryption Key URI"] == "https://kv1.vault.azure.net/keys/k1/v1"
    assert row["Encryption Identity"] == "SystemAssigned"
    assert row["Protected Items"] == 1 and row["Policies"] == 1
    assert len(item_rows) == 1 and len(policy_rows) == 1


def test_backup_vault_without_children_still_produces_a_vault_row():
    client = _FakeBackup(config=_vault_config())
    vault_rows, item_rows, policy_rows = backup_items_export.collect_vault_children(
        client, [_vault()], []
    )
    assert len(vault_rows) == 1 and item_rows == [] and policy_rows == []


def test_backup_per_vault_error_is_recorded_and_the_run_continues():
    client = _FakeBackup(policies=[_protection_policy()], config=_vault_config(),
                          failures=("items",))
    errors = []
    vault_rows, item_rows, policy_rows = backup_items_export.collect_vault_children(
        client, [_vault()], errors
    )
    assert item_rows == [] and len(policy_rows) == 1 and len(vault_rows) == 1
    assert [(e["Scope"], e["Operation"], e["Error Code"]) for e in errors] == [
        (_VAULT_ID, "backup_protected_items.list", "AuthorizationFailed")
    ]


def test_backup_vault_config_error_falls_back_to_the_vault_resource():
    client = _FakeBackup(config=_vault_config(), failures=("config",))
    errors = []
    (row,), _, _ = backup_items_export.collect_vault_children(client, [_vault()], errors)
    assert [e["Operation"] for e in errors] == ["backup_resource_vault_configs.get"]
    assert row["Soft Delete State"] == "Enabled"
    assert row["Storage Type"] == "GeoRedundant"


def test_backup_items_without_vaults_is_no_resources_found(monkeypatch):
    clients = {
        "recoveryservices": SimpleNamespace(
            vaults=SimpleNamespace(list_by_subscription_id=lambda: iter(()))
        ),
        "recoveryservicesbackup": _FakeBackup(),
    }
    _patch_client_by_service(monkeypatch, backup_items_export, clients)
    with pytest.raises(backup_items_export.utils.NoResourcesFound):
        backup_items_export.main("00000000-0000-0000-0000-000000000001", "Sub")


# --- WAF policies ----------------------------------------------------------------


def _sdk_waf_policy(name="waf1", mode="Prevention", custom_rules=None, **properties):
    models = pytest.importorskip("azure.mgmt.network.models")
    props = {
        "policySettings": {
            "mode": mode, "state": "Enabled", "requestBodyCheck": True,
            "maxRequestBodySizeInKb": 128, "fileUploadLimitInMb": 100,
        },
        "managedRules": {"managedRuleSets": [
            {"ruleSetType": "OWASP", "ruleSetVersion": "3.2"},
            {"ruleSetType": "Microsoft_BotManagerRuleSet", "ruleSetVersion": "1.0"},
        ]},
        "customRules": custom_rules if custom_rules is not None else [{
            "name": "BlockCH", "priority": 10, "ruleType": "MatchRule", "action": "Block",
            "state": "Enabled", "rateLimitThreshold": 100, "rateLimitDuration": "OneMin",
            "matchConditions": [{
                "matchVariables": [{"variableName": "RequestHeader", "selector": "User-Agent"}],
                "operator": "Contains", "negationConditon": False,
                "matchValues": ["badbot"], "transforms": ["Lowercase"],
            }],
        }],
        "applicationGateways": [{
            "id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Network"
                  "/applicationGateways/agw1",
            "name": "agw1", "location": "eastus",
        }],
        "httpListeners": [{"id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Network"
                                 "/applicationGateways/agw1/httpListeners/listener1"}],
        "pathBasedRules": [],
        "resourceState": "Enabled",
        "provisioningState": "Succeeded",
    }
    props.update(properties)
    return models.WebApplicationFirewallPolicy({
        "id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Network"
              f"/ApplicationGatewayWebApplicationFirewallPolicies/{name}",
        "name": name, "location": "eastus", "tags": {"env": "prod"}, "properties": props,
    })


def test_waf_policy_row_from_a_real_sdk_model():
    row = waf_policies_export.build_policy_row(_sdk_waf_policy())
    assert row["Name"] == "waf1" and row["Resource Group"] == "rg1"
    assert row["Policy Type"] == "Application Gateway"
    assert row["Mode"] == "Prevention" and row["State"] == "Enabled"
    assert row["Request Body Check"] == "Yes"
    assert row["Max Request Body Size (KB)"] == "128"
    assert row["File Upload Limit (MB)"] == "100"
    assert row["Managed Rule Sets"] == "OWASP 3.2, Microsoft_BotManagerRuleSet 1.0"
    assert row["Managed Rule Set Count"] == 2
    assert row["Custom Rule Count"] == 1
    assert row["Associated Application Gateways"] == "agw1"
    assert row["Associated Listeners"] == "listener1"
    assert row["Provisioning State"] == "Succeeded"
    assert row["Tags"] == "env=prod"


def test_waf_detection_mode_is_reported_verbatim():
    assert waf_policies_export.build_policy_row(_sdk_waf_policy(mode="Detection"))["Mode"] == "Detection"


def test_waf_custom_rule_rows_summarize_their_match_conditions():
    (row,) = waf_policies_export.build_custom_rule_rows(_sdk_waf_policy())
    assert row["Policy"] == "waf1" and row["Rule Name"] == "BlockCH"
    assert row["Priority"] == "10" and row["Action"] == "Block" and row["State"] == "Enabled"
    assert row["Rule Type"] == "MatchRule"
    assert row["Match Conditions"] == (
        "RequestHeader[User-Agent] Contains [badbot] (transforms: Lowercase)"
    )
    assert row["Rate Limit Threshold"] == "100"


def test_waf_policy_without_custom_rules_yields_no_custom_rule_rows():
    policy = _sdk_waf_policy(custom_rules=[])
    assert waf_policies_export.build_custom_rule_rows(policy) == []
    assert waf_policies_export.build_policy_row(policy)["Custom Rule Count"] == 0


def test_waf_policies_empty_listing_is_no_resources_found(monkeypatch):
    _patch_client(monkeypatch, waf_policies_export, SimpleNamespace(
        web_application_firewall_policies=SimpleNamespace(list_all=lambda: iter(()))
    ))
    with pytest.raises(waf_policies_export.utils.NoResourcesFound):
        waf_policies_export.main("00000000-0000-0000-0000-000000000001", "Sub")


# --- cognitive services ----------------------------------------------------------


def _sdk_account(name="openai1", kind="OpenAI", **properties):
    models = pytest.importorskip("azure.mgmt.cognitiveservices.models")
    props = {
        "endpoint": "https://openai1.openai.azure.com/",
        "publicNetworkAccess": "Disabled",
        "disableLocalAuth": True,
        "customSubDomainName": "openai1",
        "restrictOutboundNetworkAccess": True,
        "allowedFqdnList": ["contoso.com"],
        "provisioningState": "Succeeded",
        "networkAcls": {
            "defaultAction": "Deny", "bypass": "AzureServices",
            "ipRules": [{"value": "1.2.3.4"}],
            "virtualNetworkRules": [{"id": _SUBNET_ID}],
        },
        "encryption": {
            "keySource": "Microsoft.KeyVault",
            "keyVaultProperties": {
                "keyName": "cmk1", "keyVaultUri": "https://kv1.vault.azure.net/",
                "keyVersion": "v1",
            },
        },
        "privateEndpointConnections": [{"id": "/pe1"}, {"id": "/pe2"}],
    }
    props.update(properties)
    return models.Account.deserialize({
        "id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/{name}",
        "name": name, "location": "eastus", "kind": kind,
        "sku": {"name": "S0", "tier": "Standard"},
        "identity": {"type": "SystemAssigned",
                     "principalId": "11111111-1111-1111-1111-111111111111"},
        "tags": {"env": "prod"}, "properties": props,
    })


def test_cognitive_services_row_from_a_real_sdk_model():
    row = cognitive_services_export.build_row(_sdk_account())
    assert row["Name"] == "openai1" and row["Kind"] == "OpenAI"
    assert row["Resource Group"] == "rg1" and row["SKU"] == "S0"
    assert row["Endpoint"] == "https://openai1.openai.azure.com/"
    assert row["Public Network Access"] == "Disabled"
    assert row["Disable Local Auth"] == "Yes"
    assert row["Custom Subdomain"] == "openai1"
    assert row["Network ACL Default Action"] == "Deny"
    assert row["IP Rule Count"] == 1 and row["VNet Rule Count"] == 1
    assert row["Private Endpoint Count"] == 2
    assert row["Encryption Key Source"] == "Microsoft.KeyVault"
    assert row["Encryption Key Vault URI"] == "https://kv1.vault.azure.net/"
    assert row["Identity Type"] == "SystemAssigned"
    assert row["Restrict Outbound Network Access"] == "Yes"
    assert row["Allowed FQDN Count"] == 1


def test_cognitive_services_local_auth_left_blank_when_the_service_omits_it():
    row = cognitive_services_export.build_row(_sdk_account(disableLocalAuth=None))
    assert row["Disable Local Auth"] == ""


def test_cognitive_services_never_calls_list_keys_and_exports_no_key_material():
    source = Path(cognitive_services_export.__file__).read_text(encoding="utf-8")
    assert "list_keys" not in source
    assert "regenerate_key" not in source

    class _KeysExplode:
        def list(self):
            return iter([_sdk_account()])

        def list_keys(self, *args, **kwargs):
            raise AssertionError("cognitive_services_export must never read account keys")

    client = SimpleNamespace(accounts=_KeysExplode())
    rows = [cognitive_services_export.build_row(a) for a in client.accounts.list()]
    columns = set(cognitive_services_export.COLUMNS)
    assert not any("key 1" in c.lower() or "key 2" in c.lower() or c.lower().endswith("key")
                   for c in columns)
    # The CMK columns are identifiers only: a vault URI and a key name, never a key value.
    assert rows[0]["Encryption Key Vault URI"] == "https://kv1.vault.azure.net/"
    assert rows[0]["Encryption Key Name"] == "cmk1"


def test_cognitive_services_empty_listing_is_no_resources_found(monkeypatch):
    _patch_client(monkeypatch, cognitive_services_export,
                  SimpleNamespace(accounts=SimpleNamespace(list=lambda: iter(()))))
    with pytest.raises(cognitive_services_export.utils.NoResourcesFound):
        cognitive_services_export.main("00000000-0000-0000-0000-000000000001", "Sub")


# --- app service plans -----------------------------------------------------------


def _sdk_plan(name="plan1", tier="PremiumV3", sites=3, **properties):
    models = pytest.importorskip("azure.mgmt.web.models")
    props = {
        "numberOfWorkers": 2, "maximumNumberOfWorkers": 30,
        "maximumElasticWorkerCount": 1, "elasticScaleEnabled": False,
        "reserved": True, "hyperV": False, "zoneRedundant": True,
        "perSiteScaling": False, "numberOfSites": sites, "isSpot": False,
        "status": "Ready", "provisioningState": "Succeeded",
    }
    props.update(properties)
    return models.AppServicePlan({
        "id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Web/serverfarms/{name}",
        "name": name, "location": "eastus", "kind": "linux", "tags": {"env": "prod"},
        "sku": {"name": "P1v3", "tier": tier, "size": "P1v3", "family": "Pv3", "capacity": 2},
        "properties": props,
    })


def test_app_service_plan_row_from_a_real_sdk_model():
    row = app_service_plans_export.build_row(_sdk_plan())
    assert row["Name"] == "plan1" and row["Resource Group"] == "rg1"
    assert row["SKU Name"] == "P1v3" and row["SKU Tier"] == "PremiumV3"
    assert row["SKU Size"] == "P1v3" and row["SKU Family"] == "Pv3"
    assert row["SKU Capacity"] == "2" and row["Worker Count"] == "2"
    assert row["Maximum Worker Count"] == "30"
    assert row["Maximum Elastic Worker Count"] == "1"
    assert row["Linux (Reserved)"] == "Yes" and row["Hyper-V"] == "No"
    assert row["Zone Redundant"] == "Yes" and row["Per-Site Scaling"] == "No"
    assert row["Number of Sites"] == "3" and row["Empty Plan"] == "No"
    assert row["Free/Shared Tier (no SLA)"] == "No"
    assert row["Status"] == "Ready" and row["Provisioning State"] == "Succeeded"


def test_app_service_plan_free_and_shared_tiers_are_flagged():
    assert app_service_plans_export.is_no_sla_tier("Free")
    assert app_service_plans_export.is_no_sla_tier("shared")
    assert not app_service_plans_export.is_no_sla_tier("Basic")
    assert not app_service_plans_export.is_no_sla_tier("Dynamic")
    row = app_service_plans_export.build_row(_sdk_plan(tier="Free", sites=0))
    assert row["Free/Shared Tier (no SLA)"] == "Yes"
    assert row["Empty Plan"] == "Yes"


def test_app_service_plan_app_service_environment_name_is_carried():
    row = app_service_plans_export.build_row(_sdk_plan(
        hostingEnvironmentProfile={"id": "/ase1", "name": "ase1"}
    ))
    assert row["App Service Environment"] == "ase1"


def test_app_service_plans_empty_listing_is_no_resources_found(monkeypatch):
    _patch_client(monkeypatch, app_service_plans_export,
                  SimpleNamespace(app_service_plans=SimpleNamespace(list=lambda: iter(()))))
    with pytest.raises(app_service_plans_export.utils.NoResourcesFound):
        app_service_plans_export.main("00000000-0000-0000-0000-000000000001", "Sub")


# --- disk encryption sets --------------------------------------------------------


def _sdk_encryption_set(name="des1", **properties):
    models = pytest.importorskip("azure.mgmt.compute.models")
    props = {
        "encryptionType": "EncryptionAtRestWithCustomerKey",
        "activeKey": {
            "keyUrl": "https://kv1.vault.azure.net/keys/cmk1/abcdef",
            "sourceVault": {"id": f"{_SUB}/resourceGroups/rg1/providers"
                                  "/Microsoft.KeyVault/vaults/kv1"},
        },
        "previousKeys": [{"keyUrl": "https://kv1.vault.azure.net/keys/cmk1/000000"}],
        "rotationToLatestKeyVersionEnabled": True,
        "provisioningState": "Succeeded",
        "federatedClientId": "None",
    }
    props.update(properties)
    return models.DiskEncryptionSet({
        "id": _DES_ID.replace("des1", name), "name": name, "location": "eastus",
        "tags": {"env": "prod"},
        "identity": {"type": "SystemAssigned",
                     "principalId": "22222222-2222-2222-2222-222222222222"},
        "properties": props,
    })


def _sdk_disk(name="disk1", set_id=_DES_ID):
    models = pytest.importorskip("azure.mgmt.compute.models")
    return models.Disk({"name": name, "location": "eastus",
                        "properties": {"encryption": {"diskEncryptionSetId": set_id}}})


def _sdk_snapshot(name="snap1", set_id=_DES_ID):
    models = pytest.importorskip("azure.mgmt.compute.models")
    return models.Snapshot({"name": name, "location": "eastus",
                            "properties": {"encryption": {"diskEncryptionSetId": set_id}}})


def _sdk_image(name="img1", set_id=_DES_ID):
    models = pytest.importorskip("azure.mgmt.compute.models")
    return models.Image({"name": name, "location": "eastus", "properties": {"storageProfile": {
        "osDisk": {"osType": "Linux", "osState": "Generalized",
                   "diskEncryptionSet": {"id": set_id}},
        "dataDisks": [{"lun": 0, "diskEncryptionSet": {"id": set_id}}],
    }}})


class _FakeCompute:
    def __init__(self, sets=(), disks=(), snapshots=(), images=(), failures=()):
        self._failures = set(failures)
        self.disk_encryption_sets = SimpleNamespace(list=lambda: iter(sets))
        self.disks = SimpleNamespace(list=lambda: self._listing("disks", disks))
        self.snapshots = SimpleNamespace(list=lambda: self._listing("snapshots", snapshots))
        self.images = SimpleNamespace(list=lambda: self._listing("images", images))

    def _listing(self, name, value):
        if name in self._failures:
            raise _http_error("AuthorizationFailed", 403)
        return iter(value)


def test_disk_encryption_set_row_exports_the_key_url_never_key_material():
    client = _FakeCompute(disks=[_sdk_disk()], snapshots=[_sdk_snapshot()], images=[_sdk_image()])
    counts = disk_encryption_sets_export.count_consumers(client, [])
    row = disk_encryption_sets_export.build_row(_sdk_encryption_set(), counts)
    assert row["Name"] == "des1" and row["Resource Group"] == "rg1"
    assert row["Encryption Type"] == "EncryptionAtRestWithCustomerKey"
    assert row["Active Key URL"] == "https://kv1.vault.azure.net/keys/cmk1/abcdef"
    assert row["Active Key Vault ID"].endswith("/vaults/kv1")
    assert row["Previous Key Count"] == 1
    assert row["Rotation To Latest Key Version Enabled"] == "Yes"
    assert row["Identity Type"] == "SystemAssigned"
    assert row["Disks Using"] == 1 and row["Snapshots Using"] == 1
    assert row["Images Using"] == 2  # os disk + one data disk

    source = Path(disk_encryption_sets_export.__file__).read_text(encoding="utf-8")
    for forbidden in ("keyvault-keys", "get_key(", "KeyClient", "key_value", "secret"):
        assert forbidden not in source
    assert all("Key Material" not in column for column in disk_encryption_sets_export.COLUMNS)


def test_disk_encryption_set_with_no_consumers_counts_zero():
    client = _FakeCompute()
    counts = disk_encryption_sets_export.count_consumers(client, [])
    row = disk_encryption_sets_export.build_row(_sdk_encryption_set(), counts)
    assert (row["Disks Using"], row["Snapshots Using"], row["Images Using"]) == (0, 0, 0)


def test_disk_encryption_set_auto_key_rotation_error_is_rendered():
    encryption_set = _sdk_encryption_set(
        autoKeyRotationError={"code": "KeyVaultAccessForbidden", "message": "no access"}
    )
    row = disk_encryption_sets_export.build_row(encryption_set, {})
    assert row["Auto Key Rotation Error"] == "KeyVaultAccessForbidden: no access"


def test_disk_encryption_set_consumer_listing_failure_is_partial_not_fatal():
    client = _FakeCompute(disks=[_sdk_disk()], failures=("snapshots",))
    errors = []
    counts = disk_encryption_sets_export.count_consumers(client, errors)
    row = disk_encryption_sets_export.build_row(_sdk_encryption_set(), counts)
    assert row["Disks Using"] == 1 and row["Snapshots Using"] == 0
    assert [(e["Scope"], e["Operation"], e["Error Code"]) for e in errors] == [
        ("Snapshots Using", "snapshots.list", "AuthorizationFailed")
    ]


def test_disk_encryption_sets_empty_listing_is_no_resources_found(monkeypatch):
    _patch_client(monkeypatch, disk_encryption_sets_export, _FakeCompute())
    with pytest.raises(disk_encryption_sets_export.utils.NoResourcesFound):
        disk_encryption_sets_export.main("00000000-0000-0000-0000-000000000001", "Sub")
