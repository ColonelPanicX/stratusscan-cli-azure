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
