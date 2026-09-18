"""Governance / security exporter tests (SSAZR-115 slice 2) — fake SDK models, no live Azure."""

import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import action_groups_export  # noqa: E402
import azure_sql_export  # noqa: E402
import defender_assessments_export  # noqa: E402
import log_analytics_export  # noqa: E402
import management_groups_export  # noqa: E402
import metric_alerts_export  # noqa: E402
import policy_compliance_export  # noqa: E402
import role_assignments_export  # noqa: E402

_SUB = "/subscriptions/00000000-0000-0000-0000-000000000001"
_VM_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
_DB_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Sql/servers/s1/databases/d1"
_ASSESSMENT_GUID = "21300918-b2e3-0346-785f-c77ff57d243b"


def _patch_client(monkeypatch, module, client):
    monkeypatch.setattr(module.utils, "get_azure_client", lambda service, sub_id=None: client)


# --- C-6: Defender assessments ---------------------------------------------------


def _metadata(name=_ASSESSMENT_GUID, **overrides):
    fields = {
        "name": name,
        "display_name": "Install endpoint protection",
        "severity": "High",
        "categories": ["Compute", "Networking"],
        "description": "Desc",
        "remediation_description": "Fix it",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _assessment(resource_details, status=None, name=_ASSESSMENT_GUID):
    return SimpleNamespace(
        name=name,
        display_name="Install endpoint protection",
        status=status,
        resource_details=resource_details,
        metadata=None,
    )


def test_assessment_resource_identity_from_azure_resource_details():
    row = defender_assessments_export._build_row(
        _assessment(SimpleNamespace(source="Azure", id=_VM_ID)), {}
    )
    assert row["Resource ID"] == _VM_ID
    assert row["Resource Name"] == "vm1"
    assert row["Resource Type"] == "Microsoft.Compute/virtualMachines"
    assert row["Resource Source"] == "Azure"


def test_assessment_resource_type_for_nested_and_subscription_ids():
    assert defender_assessments_export._resource_type_from_id(_DB_ID) == "Microsoft.Sql/servers/databases"
    assert defender_assessments_export._resource_type_from_id(_SUB) == "Microsoft.Resources/subscriptions"
    assert (
        defender_assessments_export._resource_type_from_id(f"{_SUB}/resourceGroups/rg1")
        == "Microsoft.Resources/subscriptions/resourceGroups"
    )
    assert defender_assessments_export._resource_type_from_id("") == ""


def test_assessment_on_premise_resource_details():
    details = SimpleNamespace(source="OnPremise", machine_name="srv01", source_computer_id="abc-123")
    row = defender_assessments_export._build_row(_assessment(details), {})
    assert row["Resource ID"] == "abc-123"
    assert row["Resource Name"] == "srv01"
    assert row["Resource Type"] == ""
    assert row["Resource Source"] == "OnPremise"


def test_assessment_source_string_never_lands_in_resource_id():
    row = defender_assessments_export._build_row(_assessment(SimpleNamespace(source="Azure")), {})
    assert row["Resource ID"] == ""
    assert row["Resource Name"] == ""


def test_assessment_metadata_join_by_guid():
    row = defender_assessments_export._build_row(
        _assessment(SimpleNamespace(source="Azure", id=_VM_ID)),
        {_ASSESSMENT_GUID: _metadata()},
    )
    assert row["Severity"] == "High"
    assert row["Category"] == "Compute, Networking"
    assert row["Description"] == "Desc"
    assert row["Remediation"] == "Fix it"


def test_assessment_without_metadata_leaves_columns_blank():
    row = defender_assessments_export._build_row(
        _assessment(SimpleNamespace(source="Azure", id=_VM_ID)), {"other-guid": _metadata("other-guid")}
    )
    assert (row["Severity"], row["Category"], row["Description"], row["Remediation"]) == ("", "", "", "")


def test_assessment_status_detail_columns():
    status = SimpleNamespace(
        code="NotApplicable",
        cause="OffByPolicy",
        description="The effective policy was evaluated to off",
        first_evaluation_date=datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc),
        status_change_date=None,
    )
    row = defender_assessments_export._build_row(_assessment(None, status=status), {})
    assert row["Status"] == "NotApplicable"
    assert row["Status Cause"] == "OffByPolicy"
    assert row["Status Description"].startswith("The effective policy")
    assert row["First Evaluation Date"] == "2026-01-02T03:04:05+00:00"
    assert row["Status Change Date"] == ""


def test_collect_assessments_calls_metadata_list_once(monkeypatch):
    calls = {"metadata": 0}

    def metadata_list():
        calls["metadata"] += 1
        return iter([_metadata()])

    assessments = [_assessment(SimpleNamespace(source="Azure", id=_VM_ID)) for _ in range(3)]
    client = SimpleNamespace(
        assessments=SimpleNamespace(list=lambda scope: iter(assessments)),
        assessments_metadata=SimpleNamespace(list=metadata_list),
    )
    _patch_client(monkeypatch, defender_assessments_export, client)

    rows = defender_assessments_export.collect_assessments("sub-id")
    assert calls["metadata"] == 1
    assert [r["Severity"] for r in rows] == ["High"] * 3


def test_collect_assessments_metadata_failure_leaves_severity_blank(monkeypatch):
    def failing():
        raise RuntimeError("boom")
        yield  # pragma: no cover

    client = SimpleNamespace(
        assessments=SimpleNamespace(
            list=lambda scope: iter([_assessment(SimpleNamespace(source="Azure", id=_VM_ID))])
        ),
        assessments_metadata=SimpleNamespace(list=failing),
    )
    _patch_client(monkeypatch, defender_assessments_export, client)

    rows = defender_assessments_export.collect_assessments("sub-id")
    assert len(rows) == 1
    assert rows[0]["Severity"] == ""
    assert rows[0]["Resource ID"] == _VM_ID


def test_assessment_row_against_real_sdk_models():
    models = pytest.importorskip("azure.mgmt.security.v2021_06_01.models")
    assessment = models.SecurityAssessmentResponse.deserialize(
        {
            "id": f"{_VM_ID}/providers/Microsoft.Security/assessments/{_ASSESSMENT_GUID}",
            "name": _ASSESSMENT_GUID,
            "type": "Microsoft.Security/assessments",
            "properties": {
                "resourceDetails": {"source": "Azure", "id": _VM_ID},
                "displayName": "Install endpoint protection",
                "status": {
                    "code": "Unhealthy",
                    "cause": "",
                    "description": "",
                    "firstEvaluationDate": "2026-01-02T03:04:05Z",
                    "statusChangeDate": "2026-02-03T04:05:06Z",
                },
            },
        }
    )
    metadata = models.SecurityAssessmentMetadataResponse.deserialize(
        {
            "id": f"/providers/Microsoft.Security/assessmentMetadata/{_ASSESSMENT_GUID}",
            "name": _ASSESSMENT_GUID,
            "type": "Microsoft.Security/assessmentMetadata",
            "properties": {
                "displayName": "Install endpoint protection",
                "severity": "High",
                "categories": ["Compute"],
                "description": "Desc",
                "remediationDescription": "Fix it",
                "assessmentType": "BuiltIn",
            },
        }
    )
    assert isinstance(assessment.resource_details, models.AzureResourceDetails)

    row = defender_assessments_export._build_row(assessment, {metadata.name: metadata})
    assert row["Resource ID"] == _VM_ID
    assert row["Resource Name"] == "vm1"
    assert row["Resource Type"] == "Microsoft.Compute/virtualMachines"
    assert row["Severity"] == "High"
    assert row["Category"] == "Compute"
    assert row["Status"] == "Unhealthy"
    assert row["First Evaluation Date"].startswith("2026-01-02T03:04:05")
    assert row["Status Change Date"].startswith("2026-02-03T04:05:06")


# --- C-8: Role assignments -------------------------------------------------------


@pytest.mark.parametrize(
    "scope, expected",
    [
        ("/", "Root (Tenant)"),
        ("/providers/Microsoft.Management/managementGroups/mg-root", "Management Group"),
        ("/providers/microsoft.management/managementgroups/MG-Prod", "Management Group"),
        (_SUB, "Subscription"),
        (f"{_SUB}/resourceGroups/rg1", "Resource Group"),
        (f"{_SUB}/resourcegroups/rg1", "Resource Group"),
        (_VM_ID, "Resource"),
        (f"{_SUB}/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/s1", "Resource"),
        ("", ""),
    ],
)
def test_scope_type_classification(scope, expected):
    assert role_assignments_export._scope_type(scope) == expected


def _role_definition(guid, role_name, role_type="BuiltInRole"):
    return SimpleNamespace(
        id=f"/providers/Microsoft.Authorization/roleDefinitions/{guid}",
        name=guid,
        role_name=role_name,
        role_type=role_type,
    )


def _assignment(role_guid, scope=_SUB, **overrides):
    fields = {
        "name": "aaaaaaaa-0000-0000-0000-000000000001",
        "principal_id": "pppppppp-0000-0000-0000-000000000001",
        "principal_type": "User",
        "role_definition_id": f"{_SUB}/providers/Microsoft.Authorization/roleDefinitions/{role_guid}",
        "scope": scope,
        "created_on": datetime.datetime(2026, 1, 2, 3, 4, 5),
        "updated_on": datetime.datetime(2026, 1, 3, 3, 4, 5),
        "created_by": "creator-object-id",
        "condition": None,
        "description": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_collect_role_definitions_builds_guid_map(monkeypatch):
    captured = {}

    def list_definitions(scope):
        captured["scope"] = scope
        return iter([
            _role_definition("ACDD72A7-3385-48EF-BD42-F606FBA81AE7", "Reader"),
            _role_definition("custom-1", "Billing Reader Plus", "CustomRole"),
        ])

    _patch_client(
        monkeypatch, role_assignments_export,
        SimpleNamespace(role_definitions=SimpleNamespace(list=list_definitions)),
    )
    result = role_assignments_export.collect_role_definitions("sub-id")
    assert captured["scope"] == "/subscriptions/sub-id"
    assert set(result) == {"acdd72a7-3385-48ef-bd42-f606fba81ae7", "custom-1"}


def test_role_assignment_row_joins_role_name_and_type():
    definitions = {"acdd72a7-3385-48ef-bd42-f606fba81ae7": _role_definition("acdd72a7-3385-48ef-bd42-f606fba81ae7", "Reader")}
    row = role_assignments_export._build_row(
        _assignment("ACDD72A7-3385-48EF-BD42-F606FBA81AE7", condition="@Resource[x] StringEquals 'y'", description="why"),
        definitions,
    )
    assert row["Role Definition ID"] == "ACDD72A7-3385-48EF-BD42-F606FBA81AE7"
    assert row["Role Name"] == "Reader"
    assert row["Role Type"] == "BuiltInRole"
    assert row["Scope Type"] == "Subscription"
    assert row["Condition"] == "@Resource[x] StringEquals 'y'"
    assert row["Description"] == "why"
    assert row["Created By"] == "creator-object-id"
    assert row["Created On"] == "2026-01-02 03:04:05"
    assert row["Updated On"] == "2026-01-03 03:04:05"


def test_role_assignment_unknown_role_leaves_name_blank_and_keeps_guid():
    row = role_assignments_export._build_row(_assignment("unknown-guid"), {})
    assert row["Role Definition ID"] == "unknown-guid"
    assert row["Role Name"] == ""
    assert row["Role Type"] == ""


def test_role_assignment_columns_keep_existing_order_and_append():
    assert list(role_assignments_export._build_row(_assignment("g"), {})) == [
        "Assignment ID", "Principal ID", "Principal Type", "Role Definition ID",
        "Role Name", "Role Type", "Scope", "Scope Type", "Created On",
        "Condition", "Description", "Created By", "Updated On",
    ]


def test_role_assignment_row_against_real_sdk_models():
    models = pytest.importorskip("azure.mgmt.authorization.v2022_04_01.models")
    guid = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
    ra = models.RoleAssignment.deserialize(
        {
            "id": "/providers/Microsoft.Management/managementGroups/mg1/providers/Microsoft.Authorization/roleAssignments/x",
            "name": "x",
            "properties": {
                "scope": "/providers/Microsoft.Management/managementGroups/mg1",
                "roleDefinitionId": f"/providers/Microsoft.Authorization/roleDefinitions/{guid}",
                "principalId": "p1",
                "principalType": "ServicePrincipal",
                "condition": None,
                "createdOn": "2026-01-02T03:04:05Z",
                "updatedOn": "2026-01-02T03:04:05Z",
                "createdBy": "c1",
            },
        }
    )
    rd = models.RoleDefinition.deserialize(
        {
            "id": f"/providers/Microsoft.Authorization/roleDefinitions/{guid}",
            "name": guid,
            "properties": {"roleName": "Reader", "type": "BuiltInRole"},
        }
    )
    row = role_assignments_export._build_row(ra, {rd.name: rd})
    assert row["Scope Type"] == "Management Group"
    assert row["Role Name"] == "Reader"
    assert row["Role Type"] == "BuiltInRole"
    assert row["Principal Type"] == "ServicePrincipal"
    assert row["Created By"] == "c1"


# --- C-9: Action groups -----------------------------------------------------------


@pytest.mark.parametrize(
    "uri, expected",
    [
        ("https://hooks.example.com/path/to/hook", "https://hooks.example.com/path/to/hook"),
        ("https://hooks.example.com/path?token=SECRET&x=1", "https://hooks.example.com/path?…redacted"),
        ("https://hooks.example.com/path#SECRET", "https://hooks.example.com/path?…redacted"),
        ("https://user:pw@hooks.example.com:8443/p", "https://hooks.example.com:8443/p?…redacted"),
        ("", ""),
    ],
)
def test_redact_uri_drops_query_fragment_and_userinfo(uri, expected):
    assert action_groups_export._redact_uri(uri) == expected


def test_action_group_row_never_carries_webhook_query_string():
    ag = SimpleNamespace(
        id=f"{_SUB}/resourceGroups/rg1/providers/microsoft.insights/actionGroups/ag1",
        name="ag1", group_short_name="ag1", enabled=True,
        email_receivers=None, sms_receivers=None, itsm_receivers=None, azure_app_push_receivers=None,
        automation_runbook_receivers=None, azure_function_receivers=None, logic_app_receivers=None,
        webhook_receivers=[SimpleNamespace(name="hook", service_uri="https://h.example.com/a?code=SECRET")],
        arm_role_receivers=[SimpleNamespace(name="owners", role_id="8e3af657-a8ff-443c-a75c-2fe8c4bcb635")],
        voice_receivers=[SimpleNamespace(name="oncall", country_code="1", phone_number="5551234")],
        event_hub_receivers=[SimpleNamespace(name="eh", event_hub_name_space="ns1", event_hub_name="hub1")],
    )
    row = action_groups_export._build_row(ag)
    assert "SECRET" not in row["Webhook Receivers"]
    assert row["Webhook Receivers"] == "hook (https://h.example.com/a?…redacted)"
    assert row["ARM Role Receivers"] == "owners (8e3af657-a8ff-443c-a75c-2fe8c4bcb635)"
    assert row["Voice Receivers"] == "oncall (5551234)"
    assert row["Event Hub Receivers"] == "eh (ns1/hub1)"


def test_action_group_row_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.monitor.models")
    ag = models.ActionGroupResource.deserialize(
        {
            "id": f"{_SUB}/resourceGroups/rg1/providers/microsoft.insights/actionGroups/ag1",
            "name": "ag1",
            "location": "Global",
            "properties": {
                "groupShortName": "ag1",
                "enabled": True,
                "webhookReceivers": [{"name": "hook", "serviceUri": "https://h.example.com/a?code=SECRET"}],
                "armRoleReceivers": [{"name": "owners", "roleId": "role-guid"}],
                "voiceReceivers": [{"name": "v", "countryCode": "1", "phoneNumber": "5550000"}],
                "eventHubReceivers": [{"name": "eh", "eventHubNameSpace": "ns1", "eventHubName": "hub1", "subscriptionId": "s"}],
            },
        }
    )
    row = action_groups_export._build_row(ag)
    assert "SECRET" not in row["Webhook Receivers"]
    assert row["ARM Role Receivers"] == "owners (role-guid)"
    assert row["Voice Receivers"] == "v (5550000)"
    assert row["Event Hub Receivers"] == "eh (ns1/hub1)"


# --- C-10: Metric alerts ----------------------------------------------------------


def _static_criterion(metric="Percentage CPU", operator="GreaterThan", threshold=80, aggregation="Average"):
    return SimpleNamespace(
        criterion_type="StaticThresholdCriterion", metric_name=metric, operator=operator,
        threshold=threshold, time_aggregation=aggregation, dimensions=None,
    )


def _metric_alert(severity=3, criteria=None, **overrides):
    fields = {
        "id": f"{_SUB}/resourceGroups/rg1/providers/microsoft.insights/metricAlerts/a1",
        "name": "a1", "severity": severity, "enabled": True,
        "scopes": [_VM_ID], "criteria": criteria, "window_size": datetime.timedelta(minutes=5),
        "evaluation_frequency": datetime.timedelta(minutes=1), "auto_mitigate": True,
        "actions": None, "description": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_metric_alert_severity_zero_survives():
    row = metric_alerts_export._build_metric_alert_row(_metric_alert(severity=0))
    assert row["Severity"] == 0


def test_metric_alert_severity_none_is_blank():
    row = metric_alerts_export._build_metric_alert_row(_metric_alert(severity=None))
    assert row["Severity"] == ""


def test_metric_alert_threshold_zero_survives():
    criteria = SimpleNamespace(
        odata_type="Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
        all_of=[_static_criterion(metric="Errors", threshold=0)],
    )
    assert metric_alerts_export._format_criteria(criteria) == "Average(Errors) GreaterThan 0"


def test_metric_alert_dynamic_threshold_formatting():
    dynamic = SimpleNamespace(
        criterion_type="DynamicThresholdCriterion", metric_name="Requests", operator="GreaterOrLessThan",
        time_aggregation="Total", alert_sensitivity="Medium", dimensions=None,
        failing_periods=SimpleNamespace(number_of_evaluation_periods=4, min_failing_periods_to_alert=3),
    )
    criteria = SimpleNamespace(
        odata_type="Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria", all_of=[dynamic],
    )
    assert metric_alerts_export._format_criteria(criteria) == (
        "Total(Requests) GreaterOrLessThan dynamic(sensitivity=Medium, failing 3/4)"
    )


def test_metric_alert_webtest_formatting():
    criteria = SimpleNamespace(
        odata_type="Microsoft.Azure.Monitor.WebtestLocationAvailabilityCriteria",
        web_test_id=f"{_SUB}/resourceGroups/rg1/providers/microsoft.insights/webtests/wt1",
        component_id="c", failed_location_count=2,
    )
    assert metric_alerts_export._format_criteria(criteria) == "Webtest wt1: failedLocationCount=2"


def test_metric_alert_new_columns():
    row = metric_alerts_export._build_metric_alert_row(_metric_alert(scopes=[_VM_ID, _DB_ID], auto_mitigate=False))
    assert row["Evaluation Frequency"] == "1m"
    assert row["Window Size"] == "5m"
    assert row["Auto Mitigate"] == "No"
    assert row["Scope IDs"] == f"{_VM_ID}; {_DB_ID}"
    assert row["Target Resource"] == "vm1, d1"


def test_metric_alert_row_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.monitor.models")
    alert = models.MetricAlertResource.deserialize(
        {
            "id": f"{_SUB}/resourceGroups/rg1/providers/microsoft.insights/metricAlerts/a1",
            "name": "a1",
            "location": "global",
            "properties": {
                "severity": 0,
                "enabled": True,
                "scopes": [_VM_ID],
                "evaluationFrequency": "PT1M",
                "windowSize": "PT5M",
                "autoMitigate": True,
                "criteria": {
                    "odata.type": "Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria",
                    "allOf": [
                        {
                            "criterionType": "DynamicThresholdCriterion",
                            "name": "c1",
                            "metricName": "Percentage CPU",
                            "timeAggregation": "Average",
                            "operator": "GreaterThan",
                            "alertSensitivity": "High",
                            "failingPeriods": {"numberOfEvaluationPeriods": 4, "minFailingPeriodsToAlert": 4},
                            "dimensions": [{"name": "LUN", "operator": "Include", "values": ["0", "1"]}],
                        },
                        {
                            "criterionType": "StaticThresholdCriterion",
                            "name": "c2",
                            "metricName": "Disk Read Bytes",
                            "timeAggregation": "Total",
                            "operator": "LessThan",
                            "threshold": 0,
                        },
                    ],
                },
            },
        }
    )
    assert isinstance(alert.criteria, models.MetricAlertMultipleResourceMultipleMetricCriteria)
    assert isinstance(alert.criteria.all_of[0], models.DynamicMetricCriteria)

    row = metric_alerts_export._build_metric_alert_row(alert)
    assert row["Severity"] == 0
    assert row["Condition"] == (
        "Average(Percentage CPU) GreaterThan dynamic(sensitivity=High, failing 4/4) [LUN Include 0,1]; "
        "Total(Disk Read Bytes) LessThan 0"
    )
    assert row["Evaluation Frequency"] == "1m"
    assert row["Window Size"] == "5m"
    assert row["Auto Mitigate"] == "Yes"


# --- C-12: Azure SQL -------------------------------------------------------------


def _server(name, administrators=None, **overrides):
    fields = {
        "id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Sql/servers/{name}",
        "name": name, "location": "eastus", "version": "12.0", "state": "Ready",
        "fully_qualified_domain_name": f"{name}.database.windows.net",
        "public_network_access": "Disabled", "restrict_outbound_network_access": "Enabled",
        "minimal_tls_version": "1.2", "administrators": administrators,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _database(name, **overrides):
    fields = {
        "name": name, "sku": SimpleNamespace(name="GP_Gen5_2", tier="GeneralPurpose"),
        "max_size_bytes": 2 * 1024 ** 3, "status": "Online", "zone_redundant": False,
        "collation": "SQL_Latin1_General_CP1_CI_AS", "tags": {"env": "prod"},
        "requested_backup_storage_redundancy": "Geo", "is_ledger_on": False,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class _FakeSqlClient:
    def __init__(self, servers, databases, errors=None):
        self._servers = servers
        self._databases = databases
        self._errors = errors or {}
        self.expand_calls = []
        self.servers = SimpleNamespace(list=self._list_servers)
        self.databases = SimpleNamespace(list_by_server=self._list_databases)

    def _list_servers(self, expand=None):
        self.expand_calls.append(expand)
        return iter(self._servers)

    def _list_databases(self, resource_group_name, server_name):
        if server_name in self._errors:
            raise self._errors[server_name]
        return iter(self._databases.get(server_name, []))


def test_sql_server_without_user_databases_still_gets_a_row(monkeypatch):
    client = _FakeSqlClient(
        servers=[_server("empty"), _server("busy", administrators=SimpleNamespace(login="admin@x", azure_ad_only_authentication=True))],
        databases={"empty": [_database("master")], "busy": [_database("master"), _database("app")]},
    )
    _patch_client(monkeypatch, azure_sql_export, client)

    server_rows, db_rows = azure_sql_export.collect_sql_servers_and_dbs("sub-id")

    assert client.expand_calls == ["administrators/activedirectory"]
    assert [(r["Server Name"], r["Databases"]) for r in server_rows] == [("empty", 0), ("busy", 1)]
    assert [(r["Server Name"], r["Database Name"]) for r in db_rows] == [("busy", "app")]
    assert server_rows[0]["Entra-Only Authentication"] == ""
    assert server_rows[1]["Entra-Only Authentication"] == "Yes"
    assert server_rows[1]["Entra Admin Login"] == "admin@x"
    assert server_rows[1]["Public Network Access"] == "Disabled"
    assert server_rows[1]["Minimal TLS Version"] == "1.2"


def test_sql_database_listing_failure_is_marked_on_the_server_row(monkeypatch):
    exceptions = pytest.importorskip("azure.core.exceptions")
    http_error = exceptions.HttpResponseError(message="denied")
    http_error.error = SimpleNamespace(code="AuthorizationFailed")
    client = _FakeSqlClient(
        servers=[_server("locked"), _server("ok")],
        databases={"ok": [_database("app")]},
        errors={"locked": http_error},
    )
    _patch_client(monkeypatch, azure_sql_export, client)

    server_rows, db_rows = azure_sql_export.collect_sql_servers_and_dbs("sub-id")

    assert server_rows[0]["Databases"] == "ERROR (AuthorizationFailed)"
    assert server_rows[1]["Databases"] == 1
    assert len(db_rows) == 1


def test_sql_error_code_falls_back_to_exception_type():
    assert azure_sql_export._error_code(RuntimeError("x")) == "RuntimeError"


def test_sql_database_row_keeps_existing_columns_and_appends():
    row = azure_sql_export._build_database_row(_server("s"), "rg1", _database("d", is_ledger_on=True))
    assert list(row) == [
        "Server Name", "Resource Group", "Location", "Database Name", "SKU", "Edition",
        "Max Size (GB)", "Status", "Zone Redundant", "Collation", "Server FQDN", "TLS Version", "Tags",
        "Backup Storage Redundancy", "Ledger",
    ]
    assert row["Max Size (GB)"] == 2.0
    assert row["Backup Storage Redundancy"] == "Geo"
    assert row["Ledger"] == "Yes"


def test_sql_server_row_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.sql.models")
    server = models.Server(
        {
            "id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Sql/servers/s1",
            "name": "s1",
            "location": "japaneast",
            "properties": {
                "administratorLogin": "dummylogin",
                "administrators": {
                    "azureADOnlyAuthentication": True,
                    "login": "bob@contoso.com",
                    "principalType": "User",
                    "sid": "00000011-1111-2222-2222-123456789111",
                },
                "fullyQualifiedDomainName": "s1.database.windows.net",
                "minimalTlsVersion": "1.2",
                "publicNetworkAccess": "Enabled",
                "restrictOutboundNetworkAccess": "Enabled",
                "state": "Ready",
                "version": "12.0",
            },
        }
    )
    row = azure_sql_export._build_server_row(server, "rg1", 0)
    assert row["Entra-Only Authentication"] == "Yes"
    assert row["Entra Admin Login"] == "bob@contoso.com"
    assert row["Public Network Access"] == "Enabled"
    assert row["Restrict Outbound Network Access"] == "Enabled"
    assert row["Minimal TLS Version"] == "1.2"
    assert row["Version"] == "12.0"
    assert row["State"] == "Ready"


# --- Management groups -----------------------------------------------------------


def _mg_info(name, display_name="Display", tenant_id="t1"):
    return SimpleNamespace(
        id=f"/providers/Microsoft.Management/managementGroups/{name}",
        name=name, display_name=display_name, tenant_id=tenant_id,
    )


def _mg_detail(name, children=None, parent=None):
    return SimpleNamespace(
        id=f"/providers/Microsoft.Management/managementGroups/{name}",
        name=name, display_name=f"{name} display", tenant_id="t1",
        details=SimpleNamespace(parent=parent), children=children,
    )


def test_management_group_row_reads_name_display_name_and_tenant():
    parent = SimpleNamespace(id="/providers/Microsoft.Management/managementGroups/root", name="root", display_name="Tenant Root")
    detail = _mg_detail(
        "mg1",
        children=[SimpleNamespace(type="/subscriptions"), SimpleNamespace(type="Microsoft.Management/managementGroups")],
        parent=parent,
    )
    row = management_groups_export._build_row(_mg_info("mg1"), detail, "")
    assert row["Management Group Name"] == "mg1"
    assert row["Display Name"] == "mg1 display"
    assert row["ID"] == "/providers/Microsoft.Management/managementGroups/mg1"
    assert row["Tenant ID"] == "t1"
    assert row["Parent Name"] == "Tenant Root"
    assert row["Subscription Count"] == 1
    assert row["Detail Error"] == ""


def test_management_group_failed_detail_is_reported_not_zero(monkeypatch):
    exceptions = pytest.importorskip("azure.core.exceptions")
    error = exceptions.HttpResponseError(message="forbidden")
    error.error = SimpleNamespace(code="AuthorizationFailed")

    def get(group_id, expand=None):
        if group_id == "mg-denied":
            raise error
        return _mg_detail(group_id, children=[SimpleNamespace(type="/subscriptions")])

    client = SimpleNamespace(
        management_groups=SimpleNamespace(list=lambda: iter([_mg_info("mg-denied"), _mg_info("mg-ok")]), get=get)
    )
    _patch_client(monkeypatch, management_groups_export, client)

    rows = management_groups_export.collect_management_groups()
    assert rows[0]["Subscription Count"] == ""
    assert rows[0]["Detail Error"] == "AuthorizationFailed"
    assert rows[0]["Display Name"] == "Display"
    assert rows[1]["Subscription Count"] == 1
    assert rows[1]["Detail Error"] == ""


def test_management_group_row_against_real_sdk_models():
    models = pytest.importorskip("azure.mgmt.managementgroups.models")
    info = models.ManagementGroupInfo(
        {"id": "/providers/Microsoft.Management/managementGroups/x", "name": "x",
         "properties": {"tenantId": "t", "displayName": "X"}}
    )
    detail = models.ManagementGroup(
        {
            "id": "/providers/Microsoft.Management/managementGroups/x",
            "name": "x",
            "properties": {
                "tenantId": "t",
                "displayName": "X",
                "details": {"parent": {"id": "/providers/Microsoft.Management/managementGroups/root", "name": "root", "displayName": "Root"}},
                "children": [
                    {"type": "/subscriptions", "id": "/subscriptions/s1", "name": "s1"},
                    {"type": "Microsoft.Management/managementGroups", "id": "/providers/Microsoft.Management/managementGroups/y", "name": "y"},
                ],
            },
        }
    )
    row = management_groups_export._build_row(info, detail, "")
    assert row["Subscription Count"] == 1
    assert row["Tenant ID"] == "t"
    assert row["Parent Name"] == "Root"

    fallback = management_groups_export._build_row(info, None, "HTTP 403")
    assert fallback["Subscription Count"] == ""
    assert fallback["Display Name"] == "X"


# --- Log Analytics ----------------------------------------------------------------


@pytest.mark.parametrize("quota, expected", [(-1, "No cap"), (None, ""), (5, "5 GB"), (0.5, "0.5 GB")])
def test_log_analytics_daily_cap(quota, expected):
    assert log_analytics_export._format_daily_cap(quota) == expected


def test_log_analytics_row_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.loganalytics.models")
    ws = models.Workspace(
        {
            "id": f"{_SUB}/resourceGroups/rg1/providers/Microsoft.OperationalInsights/workspaces/law1",
            "name": "law1",
            "location": "eastus",
            "properties": {
                "sku": {"name": "PerGB2018"},
                "retentionInDays": 30,
                "workspaceCapping": {"dailyQuotaGb": -1},
                "publicNetworkAccessForIngestion": "Enabled",
                "publicNetworkAccessForQuery": "Disabled",
                "provisioningState": "Succeeded",
            },
        }
    )
    row = log_analytics_export._build_row(ws)
    assert row["Daily Cap"] == "No cap"
    assert row["SKU"] == "PerGB2018"
    assert row["Public Network Access (Ingestion)"] == "Enabled"
    assert row["Public Network Access (Query)"] == "Disabled"
    assert row["Retention (days)"] == 30


# --- Policy compliance ------------------------------------------------------------


def test_policy_compliance_new_columns():
    st = SimpleNamespace(
        resource_id=_VM_ID, resource_type="Microsoft.Compute/virtualMachines", resource_location="eastus",
        compliance_state="NonCompliant", policy_assignment_name="assign1", policy_definition_name="def1",
        policy_definition_action="audit", policy_definition_category="Compute", timestamp=None,
        policy_set_definition_name="nist-800-53", policy_definition_reference_id="ref-1",
        policy_definition_group_names=["NIST_SP_800-53_R5_AC-2", "NIST_SP_800-53_R5_AC-3"],
        policy_assignment_scope=_SUB,
    )
    row = policy_compliance_export._build_detail_row(st)
    assert row["Policy Set Definition"] == "nist-800-53"
    assert row["Definition Reference ID"] == "ref-1"
    assert row["Definition Group Names"] == "NIST_SP_800-53_R5_AC-2, NIST_SP_800-53_R5_AC-3"
    assert row["Assignment Scope"] == _SUB
    assert row["Compliance State"] == "NonCompliant"


def test_policy_compliance_row_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.policyinsights.models")
    st = models.PolicyState.deserialize(
        {
            "resourceId": _VM_ID,
            "policyAssignmentName": "assign1",
            "policyDefinitionName": "def1",
            "complianceState": "Compliant",
            "policySetDefinitionName": "set1",
            "policyDefinitionReferenceId": "ref1",
            "policyDefinitionGroupNames": ["g1", "g2"],
            "policyAssignmentScope": _SUB,
            "timestamp": "2026-01-02T03:04:05Z",
        }
    )
    row = policy_compliance_export._build_detail_row(st)
    assert row["Policy Set Definition"] == "set1"
    assert row["Definition Reference ID"] == "ref1"
    assert row["Definition Group Names"] == "g1, g2"
    assert row["Assignment Scope"] == _SUB
    assert row["Timestamp"].startswith("2026-01-02 03:04:05")
