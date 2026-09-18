"""Exporter unit tests — mocked Azure SDK models, no live Azure."""

import enum
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import advisor_export  # noqa: E402
import api_management_export  # noqa: E402
import app_service_export  # noqa: E402
import application_gateway_export as agw_export  # noqa: E402
import blob_containers_export  # noqa: E402
import cosmos_db_export  # noqa: E402
import event_hubs_export  # noqa: E402
import file_shares_export  # noqa: E402
import function_apps_export  # noqa: E402
import key_vault_export  # noqa: E402
import key_vault_objects_export  # noqa: E402
import logic_apps_export  # noqa: E402
import managed_disks_export  # noqa: E402
import mysql_flexible_export  # noqa: E402
import network_security_groups_export as nsg_export  # noqa: E402
import postgresql_flexible_export  # noqa: E402
import private_endpoints_export  # noqa: E402
import public_ips_export  # noqa: E402
import redis_cache_export  # noqa: E402
import route_tables_export  # noqa: E402
import snapshots_export  # noqa: E402
import storage_accounts_export  # noqa: E402
import subnets_export  # noqa: E402
import virtual_machines_export as vm_export  # noqa: E402
from azure.core.exceptions import HttpResponseError  # noqa: E402


def _status(code):
    return SimpleNamespace(code=code)


def _vm(vm_id, name="vm1", statuses=None):
    return SimpleNamespace(
        id=vm_id,
        name=name,
        instance_view=SimpleNamespace(statuses=statuses) if statuses is not None else None,
    )


class _FakeVirtualMachines:
    def __init__(self, status_only_vms=None, instance_views=None, status_only_error=None):
        self._status_only_vms = status_only_vms or []
        self._instance_views = instance_views or {}
        self._status_only_error = status_only_error
        self.status_only_calls = []
        self.instance_view_calls = []

    def list_all(self, status_only=None):
        self.status_only_calls.append(status_only)
        if self._status_only_error:
            raise self._status_only_error
        return iter(self._status_only_vms)

    def instance_view(self, resource_group, name):
        self.instance_view_calls.append((resource_group, name))
        if (resource_group, name) not in self._instance_views:
            raise RuntimeError("not found")
        return self._instance_views[(resource_group, name)]


class _FakeComputeClient:
    def __init__(self, virtual_machines):
        self.virtual_machines = virtual_machines


# --- Finding 1: VM power state -------------------------------------------------


def test_power_state_from_statuses_strips_prefix():
    statuses = [_status("ProvisioningState/succeeded"), _status("PowerState/deallocated")]
    assert vm_export._power_state_from_statuses(statuses) == "deallocated"


def test_power_state_from_statuses_empty_is_blank():
    assert vm_export._power_state_from_statuses(None) == ""
    assert vm_export._power_state_from_statuses([]) == ""
    assert vm_export._power_state_from_statuses([_status("ProvisioningState/succeeded")]) == ""


def test_collect_power_states_uses_status_only_listing():
    ops = _FakeVirtualMachines(
        status_only_vms=[
            _vm("/subs/x/vmA", "vmA", [_status("PowerState/deallocated")]),
            _vm("/subs/x/vmB", "vmB", [_status("PowerState/running")]),
        ]
    )
    states = vm_export.collect_power_states(_FakeComputeClient(ops))

    assert ops.status_only_calls == ["true"]
    assert states == {"/subs/x/vma": "deallocated", "/subs/x/vmb": "running"}


def test_collect_power_states_survives_status_only_failure():
    ops = _FakeVirtualMachines(status_only_error=RuntimeError("statusOnly unsupported"))
    assert vm_export.collect_power_states(_FakeComputeClient(ops)) == {}


def test_get_status_reads_the_state_map():
    client = _FakeComputeClient(_FakeVirtualMachines())
    vm = _vm("/subs/x/vmA", "vmA")
    states = {"/subs/x/vma": "deallocated"}

    assert vm_export._get_status(client, vm, states, "rg1") == "deallocated"
    assert client.virtual_machines.instance_view_calls == []


def test_get_status_falls_back_to_instance_view_when_missing_from_map():
    view = SimpleNamespace(statuses=[_status("PowerState/stopped")])
    ops = _FakeVirtualMachines(instance_views={("rg1", "vmA"): view})
    vm = _vm("/subs/x/vmA", "vmA")

    assert vm_export._get_status(_FakeComputeClient(ops), vm, {}, "rg1") == "stopped"
    assert ops.instance_view_calls == [("rg1", "vmA")]


def test_get_status_returns_unknown_only_when_both_paths_fail():
    ops = _FakeVirtualMachines()
    vm = _vm("/subs/x/vmA", "vmA")
    assert vm_export._get_status(_FakeComputeClient(ops), vm, {}, "rg1") == "unknown"


def test_get_status_failure_is_isolated_to_one_vm():
    view = SimpleNamespace(statuses=[_status("PowerState/running")])
    ops = _FakeVirtualMachines(instance_views={("rg1", "vmB"): view})
    client = _FakeComputeClient(ops)

    assert vm_export._get_status(client, _vm("/subs/x/vmA", "vmA"), {}, "rg1") == "unknown"
    assert vm_export._get_status(client, _vm("/subs/x/vmB", "vmB"), {}, "rg1") == "running"


# --- Finding 2: Advisor savings ------------------------------------------------


def test_extract_savings_splits_monthly_and_annual():
    result = advisor_export._extract_savings(
        {"savingsAmount": "237.5", "annualSavingsAmount": "2850", "savingsCurrency": "USD"}
    )
    assert result["Potential Savings (Monthly)"] == 237.5
    assert result["Potential Savings (Annual)"] == 2850.0
    assert result["Savings Currency"] == "USD"


def test_extract_savings_annual_only_leaves_monthly_blank():
    result = advisor_export._extract_savings({"annualSavingsAmount": "2850"})
    assert result["Potential Savings (Monthly)"] == ""
    assert result["Potential Savings (Annual)"] == 2850.0


def test_extract_savings_currency_blank_when_absent():
    result = advisor_export._extract_savings({"savingsAmount": "10", "annualSavingsAmount": "120"})
    assert result["Savings Currency"] == ""


def test_extract_savings_reads_only_documented_amount_keys():
    result = advisor_export._extract_savings(
        {"monthlySavingsAmount": "99", "estimatedAnnualSavings": "1200"}
    )
    assert result["Potential Savings (Monthly)"] == ""
    assert result["Potential Savings (Annual)"] == ""


@pytest.mark.parametrize(
    "extended, expected",
    [
        ({"region": "usgovvirginia", "Region": "ignored", "location": "ignored"}, "usgovvirginia"),
        ({"Region": "usgovarizona", "location": "ignored"}, "usgovarizona"),
        ({"location": "usgovtexas"}, "usgovtexas"),
        ({"region": "", "Region": None, "location": "usgovtexas"}, "usgovtexas"),
        ({"ServerName": "s1"}, ""),
    ],
)
def test_extract_savings_region_fallback_chain(extended, expected):
    assert advisor_export._extract_savings(extended)["Region"] == expected


def test_extract_savings_carries_reservation_context():
    result = advisor_export._extract_savings(
        {
            "savingsAmount": "100",
            "term": "P3Y",
            "lookbackPeriod": "30",
            "region": "usgovvirginia",
        }
    )
    assert result["Reservation Term"] == "P3Y"
    assert result["Lookback (days)"] == 30.0
    assert result["Region"] == "usgovvirginia"


def test_extract_savings_keeps_unparseable_lookback_as_text():
    result = advisor_export._extract_savings({"savingsAmount": "100", "lookbackPeriod": "P30D"})
    assert result["Lookback (days)"] == "P30D"


def test_extract_savings_blank_when_no_cost_data():
    result = advisor_export._extract_savings({"someOtherKey": "value"})
    assert result["Potential Savings (Monthly)"] == ""
    assert result["Potential Savings (Annual)"] == ""
    assert result["Savings Currency"] == ""


def test_extract_savings_handles_empty_properties():
    for empty in ({}, None):
        result = advisor_export._extract_savings(empty)
        assert result["Potential Savings (Monthly)"] == ""
        assert result["Savings Currency"] == ""


def test_extract_savings_ignores_non_numeric_amounts():
    result = advisor_export._extract_savings({"savingsAmount": "N/A", "savingsCurrency": "USD"})
    assert result["Potential Savings (Monthly)"] == ""
    assert result["Savings Currency"] == ""


# --- SSAZR-115 / C-7: Advisor resource identity ---------------------------------

_SUB = "/subscriptions/00000000-0000-0000-0000-000000000001"
_VM_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
_DB_ID = f"{_SUB}/resourceGroups/rg1/providers/Microsoft.Sql/servers/s1/databases/d1"
_REC_SUFFIX = "/providers/Microsoft.Advisor/recommendations/11111111-2222-3333-4444-555555555555"


def _rec(**overrides):
    fields = {
        "id": None, "category": "Cost", "impact": "High",
        "impacted_field": None, "impacted_value": None,
        "last_updated": None, "recommendation_type_id": None,
        "short_description": SimpleNamespace(problem="p", solution="s"),
        "extended_properties": None, "resource_metadata": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize(
    "resource_id, expected",
    [
        (_VM_ID, ("vm1", "Microsoft.Compute/virtualMachines")),
        (_DB_ID, ("d1", "Microsoft.Sql/servers/databases")),
        (
            f"{_VM_ID}/providers/Microsoft.Security/assessments/a1",
            ("a1", "Microsoft.Security/assessments"),
        ),
        (f"{_SUB}/resourcegroups/rg1/PROVIDERS/Microsoft.Web/sites/app1", ("app1", "Microsoft.Web/sites")),
        (_SUB, ("00000000-0000-0000-0000-000000000001", "Microsoft.Resources/subscriptions")),
        (f"{_SUB}/resourceGroups/rg1", ("rg1", "Microsoft.Resources/subscriptions/resourceGroups")),
        (f"{_SUB}/providers/Microsoft.Compute/virtualMachines", ("", "Microsoft.Compute/virtualMachines")),
        ("Microsoft.Compute/virtualMachines", ("", "")),
        ("", ("", "")),
        (None, ("", "")),
    ],
)
def test_parse_resource_id(resource_id, expected):
    assert advisor_export._parse_resource_id(resource_id) == expected


def test_build_row_reads_resource_id_from_resource_metadata():
    row = advisor_export._build_row(
        _rec(
            id=f"{_VM_ID}{_REC_SUFFIX}",
            impacted_field="Microsoft.Compute/virtualMachines",
            impacted_value="vm1",
            resource_metadata=SimpleNamespace(resource_id=_VM_ID, source=None),
        )
    )
    assert row["Resource ID"] == _VM_ID
    assert row["Resource Name"] == "vm1"
    assert row["Resource Type"] == "Microsoft.Compute/virtualMachines"


def test_build_row_derives_resource_id_from_recommendation_id():
    rec_id = f"{_DB_ID}/PROVIDERS/microsoft.advisor/Recommendations/abc-123"
    for metadata in (None, SimpleNamespace(resource_id=None), SimpleNamespace(resource_id="")):
        row = advisor_export._build_row(_rec(id=rec_id, resource_metadata=metadata))
        assert row["Resource ID"] == _DB_ID
        assert row["Resource Name"] == "d1"
        assert row["Resource Type"] == "Microsoft.Sql/servers/databases"


def test_build_row_impacted_field_never_lands_in_resource_id():
    row = advisor_export._build_row(
        _rec(impacted_field="Microsoft.Compute/virtualMachines", impacted_value="vm1")
    )
    assert row["Resource ID"] == ""
    assert row["Resource Name"] == "vm1"
    assert row["Resource Type"] == "Microsoft.Compute/virtualMachines"


def test_build_row_unrecognised_recommendation_id_leaves_resource_id_blank():
    row = advisor_export._build_row(_rec(id=f"{_VM_ID}/providers/Microsoft.Other/things/t1"))
    assert row["Resource ID"] == ""


def test_build_row_subscription_scoped_recommendation():
    row = advisor_export._build_row(
        _rec(
            id=f"{_SUB}{_REC_SUFFIX}",
            impacted_field="Microsoft.Subscriptions/subscriptions",
            impacted_value="00000000-0000-0000-0000-000000000001",
            resource_metadata=SimpleNamespace(resource_id=_SUB),
        )
    )
    assert row["Resource ID"] == _SUB
    assert row["Resource Name"] == "00000000-0000-0000-0000-000000000001"
    assert row["Resource Type"] == "Microsoft.Subscriptions/subscriptions"

    bare = advisor_export._build_row(_rec(id=f"{_SUB}{_REC_SUFFIX}"))
    assert bare["Resource ID"] == _SUB
    assert bare["Resource Name"] == "00000000-0000-0000-0000-000000000001"
    assert bare["Resource Type"] == "Microsoft.Resources/subscriptions"


def test_build_row_renders_enum_members_as_values():
    class _Category(str, enum.Enum):
        COST = "Cost"

    row = advisor_export._build_row(_rec(category=_Category.COST, impact=None))
    assert row["Category"] == "Cost"
    assert row["Impact"] == ""


def test_build_row_extended_properties_json_round_trips():
    extended = {"Region": "usgovarizona", "ServerName": "s1", "savingsAmount": "12.5", "zKey": "z"}
    row = advisor_export._build_row(
        _rec(extended_properties=extended, recommendation_type_id="type-guid")
    )
    assert json.loads(row["Extended Properties (JSON)"]) == extended
    assert row["Extended Properties (JSON)"] == json.dumps(extended, sort_keys=True)
    assert row["Recommendation Type ID"] == "type-guid"
    assert row["Region"] == "usgovarizona"
    assert row["Savings Currency"] == ""

    assert advisor_export._build_row(_rec())["Extended Properties (JSON)"] == ""


def test_build_row_keeps_existing_columns_in_place_and_appends_new_ones():
    assert list(advisor_export._build_row(_rec())) == [
        "Category", "Impact", "Resource ID", "Resource Name", "Resource Type",
        "Recommendation", "Solution",
        "Potential Savings (Monthly)", "Potential Savings (Annual)", "Savings Currency",
        "Reservation Term", "Lookback (days)", "Region",
        "Last Updated", "Recommendation Type ID", "Extended Properties (JSON)",
    ]


def test_collect_recommendations_builds_a_row_per_recommendation(monkeypatch):
    recs = [
        _rec(id=f"{_VM_ID}{_REC_SUFFIX}", resource_metadata=SimpleNamespace(resource_id=_VM_ID)),
        _rec(id=f"{_DB_ID}{_REC_SUFFIX}"),
    ]
    client = SimpleNamespace(recommendations=SimpleNamespace(list=lambda: iter(recs)))
    monkeypatch.setattr(advisor_export.utils, "get_azure_client", lambda service, sub_id: client)

    rows = advisor_export.collect_recommendations("sub-id")
    assert [r["Resource ID"] for r in rows] == [_VM_ID, _DB_ID]


def test_build_row_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.advisor.models")
    payload = {
        "id": f"{_VM_ID}{_REC_SUFFIX}",
        "name": "11111111-2222-3333-4444-555555555555",
        "type": "Microsoft.Advisor/recommendations",
        "properties": {
            "category": "Cost",
            "impact": "Medium",
            "impactedField": "Microsoft.Compute/virtualMachines",
            "impactedValue": "vm1",
            "lastUpdated": "2017-02-24T22:24:43.3216408Z",
            "recommendationTypeId": "e10b1381-5f0a-47ff-8c7b-37bd13d7c974",
            "shortDescription": {"problem": "Right-size the VM", "solution": "Resize it"},
            "extendedProperties": {"savingsAmount": "237.5", "annualSavingsAmount": "2850"},
            "resourceMetadata": {
                "resourceId": _VM_ID,
                "source": f"{_VM_ID}/providers/Microsoft.Security/assessments/a1",
                "singular": "Virtual machine",
                "plural": "Virtual machines",
            },
        },
    }
    rec = models.ResourceRecommendationBase.deserialize(payload)

    row = advisor_export._build_row(rec)
    assert row["Category"] == "Cost"
    assert row["Impact"] == "Medium"
    assert row["Resource ID"] == _VM_ID
    assert row["Resource Name"] == "vm1"
    assert row["Resource Type"] == "Microsoft.Compute/virtualMachines"
    assert row["Recommendation"] == "Right-size the VM"
    assert row["Solution"] == "Resize it"
    assert row["Potential Savings (Monthly)"] == 237.5
    assert row["Potential Savings (Annual)"] == 2850.0
    assert row["Savings Currency"] == ""
    assert row["Last Updated"].startswith("2017-02-24T22:24:43")
    assert row["Recommendation Type ID"] == "e10b1381-5f0a-47ff-8c7b-37bd13d7c974"

    rec.resource_metadata = None
    assert advisor_export._build_row(rec)["Resource ID"] == _VM_ID


# --- SSAZR-112: NSG rule counting must survive Enum-typed direction -------------


class _Direction(str, enum.Enum):
    INBOUND = "Inbound"
    OUTBOUND = "Outbound"


def _nsg_rule(name, direction, **overrides):
    fields = {
        "name": name, "priority": 100, "direction": direction, "access": "Allow", "protocol": "Tcp",
        "source_port_range": "*", "source_port_ranges": None,
        "destination_port_range": "443", "destination_port_ranges": None,
        "source_address_prefix": "*", "source_address_prefixes": None,
        "destination_address_prefix": "*", "destination_address_prefixes": None,
        "source_application_security_groups": None, "destination_application_security_groups": None,
        "description": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _run_nsg_export(monkeypatch, directions):
    nsg = SimpleNamespace(
        id="/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Network/networkSecurityGroups/nsg1",
        name="nsg1", location="eastus", tags=None, provisioning_state="Succeeded",
        subnets=None, network_interfaces=None, default_security_rules=None,
        security_rules=[_nsg_rule(f"r{i}", d) for i, d in enumerate(directions)],
    )
    captured = {}
    monkeypatch.setattr(nsg_export, "collect_nsgs", lambda subscription_id: [nsg])
    monkeypatch.setattr(
        nsg_export.utils, "save_multiple_dataframes_to_excel",
        lambda sheets, filename: captured.update(sheets),
    )
    nsg_export.main("sub-id", "sub-name")
    return captured["NSGs"].iloc[0], captured["Rules"]


def test_nsg_rule_counts_with_enum_member_direction(monkeypatch):
    summary, rules = _run_nsg_export(
        monkeypatch, [_Direction.INBOUND, _Direction.INBOUND, _Direction.OUTBOUND]
    )
    assert (summary["Custom Inbound Rules"], summary["Custom Outbound Rules"]) == (2, 1)
    assert list(rules["Direction"]) == ["Inbound", "Inbound", "Outbound"]


def test_nsg_rule_counts_with_plain_string_direction(monkeypatch):
    summary, rules = _run_nsg_export(monkeypatch, ["Inbound", "outbound", "OUTBOUND"])
    assert (summary["Custom Inbound Rules"], summary["Custom Outbound Rules"]) == (1, 2)
    assert list(rules["Direction"]) == ["Inbound", "outbound", "OUTBOUND"]


def test_nsg_rule_with_no_direction_is_counted_in_neither_bucket(monkeypatch):
    summary, _ = _run_nsg_export(monkeypatch, [None])
    assert (summary["Custom Inbound Rules"], summary["Custom Outbound Rules"]) == (0, 0)


# --- SSAZR-115 slice 2 / NSG exposure flags and ASG columns ---------------------


@pytest.mark.parametrize(
    "overrides, any_source, mgmt",
    [
        ({"destination_port_range": "22"}, True, True),
        ({"destination_port_range": "3389", "source_address_prefix": "Internet"}, True, True),
        ({"destination_port_range": "3389", "source_address_prefix": "0.0.0.0/0"}, True, True),
        ({"destination_port_range": None, "destination_port_ranges": ["80", "20-25"]}, True, True),
        ({"destination_port_range": "0-65535"}, True, True),
        ({"destination_port_range": "*"}, True, True),
        ({"destination_port_range": "443"}, True, False),
        ({"destination_port_range": "22", "protocol": "Icmp"}, True, False),
        ({"destination_port_range": "22", "source_address_prefix": "10.0.0.0/8"}, False, False),
        ({"destination_port_range": "22", "source_address_prefix": None,
          "source_address_prefixes": ["10.0.0.0/8", "*"]}, True, True),
        ({"destination_port_range": "22", "access": "Deny"}, False, False),
        ({"destination_port_range": "22", "direction": "Outbound"}, False, False),
        ({"destination_port_range": "22", "access": _Direction.INBOUND}, False, False),
    ],
)
def test_nsg_any_source_and_mgmt_port_flags(overrides, any_source, mgmt):
    rule = _nsg_rule("r", overrides.pop("direction", "Inbound"), **overrides)
    assert nsg_export.is_any_source_inbound_allow(rule) is any_source
    assert nsg_export.exposes_mgmt_ports(rule) is mgmt


def test_nsg_flags_survive_enum_members_and_land_on_both_sheets(monkeypatch):
    class _Access(str, enum.Enum):
        ALLOW = "Allow"

    asg = "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Network/applicationSecurityGroups/web-asg"
    rules = [
        _nsg_rule("ssh", _Direction.INBOUND, access=_Access.ALLOW, destination_port_range="22"),
        _nsg_rule("asg", _Direction.INBOUND, source_address_prefix="10.0.0.0/8",
                  source_application_security_groups=[SimpleNamespace(id=asg)]),
    ]
    nsg = SimpleNamespace(
        id="/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Network/networkSecurityGroups/nsg1",
        name="nsg1", location="eastus", tags=None, provisioning_state="Succeeded",
        subnets=None, network_interfaces=None, default_security_rules=None, security_rules=rules,
    )
    captured = {}
    monkeypatch.setattr(nsg_export, "collect_nsgs", lambda subscription_id: [nsg])
    monkeypatch.setattr(
        nsg_export.utils, "save_multiple_dataframes_to_excel",
        lambda sheets, filename: captured.update(sheets),
    )
    nsg_export.main("sub-id", "sub-name")

    summary = captured["NSGs"].iloc[0]
    assert bool(summary["Any-Source Inbound Allow"]) is True
    assert bool(summary["Mgmt Ports Exposed"]) is True
    assert bool(summary["Unattached"]) is True

    rules_df = captured["Rules"]
    assert list(rules_df["Any-Source Inbound Allow"]) == [True, False]
    assert list(rules_df["Mgmt Ports Exposed"]) == [True, False]
    assert list(rules_df["Source ASGs"]) == ["", "web-asg"]
    assert list(rules_df["Destination ASGs"]) == ["", ""]


# --- SSAZR-115 slice 2 / C-1: disk encryption and orphan state -------------------


class _EncryptionType(str, enum.Enum):
    CMK = "EncryptionAtRestWithCustomerKey"


def _disk(**overrides):
    fields = {
        "id": "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Compute/disks/d1",
        "name": "d1", "location": "eastus", "tags": None, "disk_size_gb": 32, "sku": None, "os_type": None,
        "disk_state": None, "encryption": None, "managed_by": None, "zones": None,
        "network_access_policy": None, "public_network_access": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_disk_encryption_blank_when_not_returned():
    assert managed_disks_export._encryption_type(_disk()) == ""
    assert managed_disks_export._encryption_type(_disk(encryption=SimpleNamespace(type=None))) == ""


def test_disk_encryption_renders_enum_value_and_des_name():
    enc = SimpleNamespace(
        type=_EncryptionType.CMK,
        disk_encryption_set_id="/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Compute/diskEncryptionSets/des1",
    )
    row = managed_disks_export._build_row(_disk(encryption=enc))
    assert row["Encryption"] == "EncryptionAtRestWithCustomerKey"
    assert row["Disk Encryption Set"] == "des1"


@pytest.mark.parametrize(
    "disk_state, managed_by, expected",
    [
        ("Unattached", None, "Yes"),
        ("Attached", "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1", "No"),
        ("Reserved", "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1", "No"),
        ("ActiveSAS", None, "No"),
        (None, None, "Yes"),
        (None, "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1", "No"),
    ],
)
def test_disk_orphan_prefers_disk_state(disk_state, managed_by, expected):
    assert managed_disks_export._orphaned(_disk(disk_state=disk_state, managed_by=managed_by)) == expected


def test_disk_row_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.compute.models")
    disk = models.Disk({
        "id": "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Compute/disks/d1",
        "name": "d1", "location": "eastus", "sku": {"name": "Premium_LRS"},
        "properties": {"diskState": "Unattached", "diskSizeGB": 64, "networkAccessPolicy": "DenyAll"},
    })
    row = managed_disks_export._build_row(disk)
    assert row["Encryption"] == ""
    assert row["State"] == "Unattached"
    assert row["Orphaned"] == "Yes"
    assert row["SKU"] == "Premium_LRS"
    assert row["Network Access Policy"] == "DenyAll"
    assert row["Public Network Access"] == ""


# --- SSAZR-115 slice 2 / C-2 + C-3: storage soft delete and replication ----------


def _storage_account(**overrides):
    fields = {
        "id": "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/acct1",
        "name": "acct1", "location": "eastus", "tags": None,
        "sku": SimpleNamespace(name="Standard_GRS", tier="Standard"), "kind": "StorageV2",
        "access_tier": None, "enable_https_traffic_only": True, "public_network_access": None,
        "minimum_tls_version": "TLS1_2", "blob_restore_status": None, "allow_blob_public_access": None,
        "provisioning_state": "Succeeded", "allow_shared_key_access": None, "encryption": None,
        "network_rule_set": None, "allow_cross_tenant_replication": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _blob_props(enabled=True, days=7, container_enabled=False, container_days=None):
    return SimpleNamespace(
        delete_retention_policy=SimpleNamespace(enabled=enabled, days=days),
        container_delete_retention_policy=SimpleNamespace(enabled=container_enabled, days=container_days),
    )


def test_storage_soft_delete_comes_from_blob_service_properties():
    row = storage_accounts_export._build_row(_storage_account(), _blob_props())
    assert row["Blob Soft Delete"] is True
    assert row["Blob Soft Delete Days"] == 7
    assert row["Container Soft Delete"] is False
    assert row["Container Soft Delete Days"] == ""


def test_storage_soft_delete_blank_when_properties_unavailable():
    row = storage_accounts_export._build_row(_storage_account(), None)
    assert row["Blob Soft Delete"] == ""
    assert row["Blob Soft Delete Days"] == ""
    assert row["Container Soft Delete"] == ""


def test_storage_soft_delete_blank_when_policy_missing_from_properties():
    props = SimpleNamespace(delete_retention_policy=None, container_delete_retention_policy=None)
    row = storage_accounts_export._build_row(_storage_account(), props)
    assert row["Blob Soft Delete"] == ""
    assert row["Container Soft Delete"] == ""


@pytest.mark.parametrize(
    "sku_name, expected",
    [("Standard_GRS", "GRS"), ("Standard_RAGZRS", "RAGZRS"), ("Premium_LRS", "LRS"), ("Standard", ""), (None, "")],
)
def test_storage_replication_split_from_sku_name(sku_name, expected):
    assert storage_accounts_export._replication(SimpleNamespace(name=sku_name, tier="Standard")) == expected


def test_storage_row_never_fabricates_public_network_access_or_flags():
    row = storage_accounts_export._build_row(_storage_account(), None)
    assert row["Public Network Access"] == ""
    assert row["Performance Tier"] == "Standard"
    assert row["Replication"] == "GRS"
    assert row["Allow Blob Public Access"] == ""
    assert row["Allow Shared Key Access"] == ""
    assert row["Infrastructure Encryption"] == ""
    assert row["Encryption Key Source"] == ""
    assert row["Network Default Action"] == ""
    assert row["Allow Cross-Tenant Replication"] == ""


def test_storage_row_keeps_existing_columns_in_place_and_appends_new_ones():
    assert list(storage_accounts_export._build_row(_storage_account(), None)) == [
        "Name", "Resource Group", "Location", "SKU", "Kind", "Access Tier", "HTTPS Only",
        "Performance Tier", "Public Network Access", "Minimum TLS Version", "Blob Soft Delete",
        "Allow Blob Public Access", "Provisioning State", "Tags",
        "Replication", "Blob Soft Delete Days", "Container Soft Delete", "Container Soft Delete Days",
        "Allow Shared Key Access", "Infrastructure Encryption", "Encryption Key Source",
        "Network Default Action", "Network Bypass", "Allow Cross-Tenant Replication",
    ]


class _FakeBlobServices:
    def __init__(self, props_by_account, failing=()):
        self._props = props_by_account
        self._failing = set(failing)
        self.calls = []

    def get_service_properties(self, resource_group_name, account_name):
        self.calls.append((resource_group_name, account_name))
        if account_name in self._failing:
            raise HttpResponseError(message="FeatureNotSupportedForAccount")
        return self._props[account_name]


def test_storage_export_isolates_per_account_failure(monkeypatch):
    accounts = [
        _storage_account(name="good"),
        _storage_account(
            name="bad",
            id="/subscriptions/s/resourceGroups/rg2/providers/Microsoft.Storage/storageAccounts/bad",
        ),
    ]
    blob_services = _FakeBlobServices({"good": _blob_props(days=14)}, failing={"bad"})
    client = SimpleNamespace(
        storage_accounts=SimpleNamespace(list=lambda: iter(accounts)),
        blob_services=blob_services,
    )
    captured = {}
    monkeypatch.setattr(storage_accounts_export.utils, "get_azure_client", lambda service, sub_id: client)
    monkeypatch.setattr(
        storage_accounts_export.utils, "save_dataframe_to_excel",
        lambda df, filename, sheet_name=None: captured.update(df=df),
    )
    storage_accounts_export.main("sub-id", "sub-name")

    df = captured["df"]
    assert blob_services.calls == [("rg1", "good"), ("rg2", "bad")]
    assert list(df["Blob Soft Delete"]) == [True, ""]
    assert list(df["Blob Soft Delete Days"]) == [14, ""]


def test_storage_row_against_real_sdk_models():
    models = pytest.importorskip("azure.mgmt.storage.models")
    acct = models.StorageAccount({
        "id": "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/acct1",
        "name": "acct1", "location": "eastus", "kind": "StorageV2",
        "sku": {"name": "Standard_RAGRS", "tier": "Standard"},
        "properties": {
            "supportsHttpsTrafficOnly": True, "minimumTlsVersion": "TLS1_2",
            "allowSharedKeyAccess": False, "allowCrossTenantReplication": False,
            "encryption": {"keySource": "Microsoft.Keyvault", "requireInfrastructureEncryption": True},
            "networkAcls": {"defaultAction": "Deny", "bypass": "AzureServices"},
        },
    })
    props = models.BlobServiceProperties({
        "id": f"{acct.id}/blobServices/default", "name": "default",
        "properties": {
            "deleteRetentionPolicy": {"enabled": True, "days": 30},
            "containerDeleteRetentionPolicy": {"enabled": True, "days": 7},
        },
    })
    row = storage_accounts_export._build_row(acct, props)
    assert row["SKU"] == "Standard_RAGRS"
    assert row["Kind"] == "StorageV2"
    assert row["Performance Tier"] == "Standard"
    assert row["Replication"] == "RAGRS"
    assert row["Public Network Access"] == ""
    assert row["Minimum TLS Version"] == "TLS1_2"
    assert (row["Blob Soft Delete"], row["Blob Soft Delete Days"]) == (True, 30)
    assert (row["Container Soft Delete"], row["Container Soft Delete Days"]) == (True, 7)
    assert row["Allow Shared Key Access"] is False
    assert row["Infrastructure Encryption"] is True
    assert row["Encryption Key Source"] == "Microsoft.Keyvault"
    assert row["Network Default Action"] == "Deny"
    assert row["Network Bypass"] == "AzureServices"
    assert row["Allow Cross-Tenant Replication"] is False


# --- SSAZR-115 slice 2 / C-4: public IP association ------------------------------

_NET = "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Network"


def _pip(ip_configuration_id=None, nat_gateway_id=None):
    return SimpleNamespace(
        id=f"{_NET}/publicIPAddresses/pip1", name="pip1", location="eastus", tags=None,
        ip_address="1.2.3.4", public_ip_allocation_method="Static", sku=None,
        public_ip_address_version="IPv4", dns_settings=None, zones=None, provisioning_state=None,
        ip_configuration=SimpleNamespace(id=ip_configuration_id) if ip_configuration_id else None,
        nat_gateway=SimpleNamespace(id=nat_gateway_id) if nat_gateway_id else None,
    )


@pytest.mark.parametrize(
    "ip_configuration_id, nat_gateway_id, expected",
    [
        (f"{_NET}/applicationGateways/agw1/frontendIPConfigurations/feip", None, ("Application Gateway", "agw1")),
        (f"{_NET}/bastionHosts/bas1/bastionHostIpConfigurations/ipconf", None, ("Bastion Host", "bas1")),
        (f"{_NET}/networkInterfaces/nic1/ipConfigurations/ipconfig1", None, ("Network Interface", "nic1")),
        (f"{_NET}/loadBalancers/lb1/frontendIPConfigurations/fe", None, ("Load Balancer", "lb1")),
        (f"{_NET}/virtualNetworkGateways/vng1/ipConfigurations/default", None, ("Virtual Network Gateway", "vng1")),
        (f"{_NET}/azureFirewalls/fw1/azureFirewallIpConfigurations/c1", None, ("Azure Firewall", "fw1")),
        (f"{_NET}/somethingNew/x1/ipConfigurations/c1", None, ("somethingNew", "x1")),
        (None, f"{_NET}/natGateways/nat1", ("NAT Gateway", "nat1")),
        (None, None, ("", "")),
    ],
)
def test_public_ip_association_is_generic(ip_configuration_id, nat_gateway_id, expected):
    pip = _pip(ip_configuration_id, nat_gateway_id)
    assert public_ips_export._association(pip) == expected
    row = public_ips_export._build_row(pip)
    assert row["Associated Resource Type"] == expected[0]
    assert row["Associated Resource"] == expected[1]
    assert row["Attached"] is bool(expected[0])


def test_public_ip_association_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.network.models")
    pip = models.PublicIPAddress({
        "id": f"{_NET}/publicIPAddresses/pip1", "name": "pip1", "location": "eastus",
        "sku": {"name": "Standard"},
        "properties": {
            "ipAddress": "1.2.3.4", "publicIPAllocationMethod": "Static",
            "ipConfiguration": {"id": f"{_NET}/bastionHosts/bas1/bastionHostIpConfigurations/ipconf"},
        },
    })
    row = public_ips_export._build_row(pip)
    assert row["SKU"] == "Standard"
    assert row["Allocation Method"] == "Static"
    assert (row["Associated Resource Type"], row["Associated Resource"], row["Attached"]) == (
        "Bastion Host", "bas1", True,
    )


# --- SSAZR-115 slice 2 / C-5: Application Gateway WAF via policy -----------------

_WAF_POLICY_ID = f"{_NET}/ApplicationGatewayWebApplicationFirewallPolicies/wafpol1"


def _gateway(firewall_policy_id=None, legacy=None, listener_policy_ids=(), **overrides):
    fields = {
        "id": f"{_NET}/applicationGateways/agw1", "name": "agw1", "location": "eastus", "tags": None,
        "sku": SimpleNamespace(name="WAF_v2", tier="WAF_v2", capacity=2),
        "web_application_firewall_configuration": legacy,
        "firewall_policy": SimpleNamespace(id=firewall_policy_id) if firewall_policy_id else None,
        "ssl_policy": None, "enable_http2": None, "zones": None, "provisioning_state": "Succeeded",
        "frontend_ip_configurations": None, "backend_address_pools": None, "request_routing_rules": None,
        "http_listeners": [
            SimpleNamespace(name=f"l{i}", firewall_policy=SimpleNamespace(id=pid) if pid else None)
            for i, pid in enumerate(listener_policy_ids)
        ],
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _policy(policy_id=_WAF_POLICY_ID, mode="Prevention", state="Enabled"):
    return SimpleNamespace(
        id=policy_id, name=policy_id.split("/")[-1],
        policy_settings=SimpleNamespace(mode=mode, state=state),
    )


def test_agw_waf_enabled_via_policy_with_mode_and_state():
    policies = {_WAF_POLICY_ID.lower(): _policy(mode="Detection", state="Enabled")}
    waf = agw_export._waf_columns(_gateway(firewall_policy_id=_WAF_POLICY_ID.upper()), policies)
    assert waf == {
        "WAF Enabled": True, "WAF Mode": "Detection", "WAF State": "Enabled",
        "WAF Policy": "WAFPOL1", "WAF Source": "Policy", "Listener WAF Policies": 0,
    }


def test_agw_waf_policy_present_but_lookup_failed_leaves_mode_blank():
    waf = agw_export._waf_columns(_gateway(firewall_policy_id=_WAF_POLICY_ID), {})
    assert waf["WAF Enabled"] is True
    assert waf["WAF Mode"] == ""
    assert waf["WAF State"] == ""
    assert waf["WAF Policy"] == "wafpol1"


def test_agw_waf_from_legacy_configuration():
    legacy = SimpleNamespace(enabled=True, firewall_mode="Prevention")
    waf = agw_export._waf_columns(_gateway(legacy=legacy), {})
    assert (waf["WAF Enabled"], waf["WAF Mode"], waf["WAF State"], waf["WAF Source"]) == (
        True, "Prevention", "Enabled", "Legacy Config",
    )
    disabled = agw_export._waf_columns(_gateway(legacy=SimpleNamespace(enabled=False, firewall_mode="Detection")), {})
    assert (disabled["WAF Enabled"], disabled["WAF State"]) == (False, "Disabled")


def test_agw_waf_listener_only_policy_counts_as_enabled():
    waf = agw_export._waf_columns(_gateway(listener_policy_ids=(_WAF_POLICY_ID, None)), {})
    assert waf["WAF Enabled"] is True
    assert waf["Listener WAF Policies"] == 1
    assert waf["WAF Source"] == ""


def test_agw_no_waf_at_all():
    waf = agw_export._waf_columns(_gateway(), {})
    assert waf == {
        "WAF Enabled": False, "WAF Mode": "", "WAF State": "", "WAF Policy": "",
        "WAF Source": "", "Listener WAF Policies": 0,
    }


def test_agw_policy_listing_failure_returns_empty_map():
    def _boom():
        raise HttpResponseError(message="throttled")

    client = SimpleNamespace(web_application_firewall_policies=SimpleNamespace(list_all=_boom))
    assert agw_export.collect_waf_policies(client) == {}


def test_agw_row_against_real_sdk_models():
    models = pytest.importorskip("azure.mgmt.network.models")
    gw = models.ApplicationGateway({
        "id": f"{_NET}/applicationGateways/agw1", "name": "agw1", "location": "eastus", "zones": ["1", "2"],
        "properties": {
            "sku": {"name": "WAF_v2", "tier": "WAF_v2", "capacity": 2},
            "firewallPolicy": {"id": _WAF_POLICY_ID},
            "sslPolicy": {"policyType": "Predefined", "policyName": "AppGwSslPolicy20220101", "minProtocolVersion": "TLSv1_2"},
            "enableHttp2": True,
            "httpListeners": [{"name": "l1", "properties": {"protocol": "Https"}}],
        },
    })
    policy = models.WebApplicationFirewallPolicy({
        "id": _WAF_POLICY_ID, "name": "wafpol1", "location": "eastus",
        "properties": {"policySettings": {"state": "Enabled", "mode": "Prevention"}},
    })
    row = agw_export._build_row(gw, {_WAF_POLICY_ID.lower(): policy})
    assert row["SKU Name"] == "WAF_v2"
    assert row["SKU Tier"] == "WAF_v2"
    assert row["WAF Enabled"] is True
    assert row["WAF Mode"] == "Prevention"
    assert row["WAF State"] == "Enabled"
    assert row["WAF Policy"] == "wafpol1"
    assert row["SSL Policy Type"] == "Predefined"
    assert row["SSL Policy Name"] == "AppGwSslPolicy20220101"
    assert row["SSL Min Protocol Version"] == "TLSv1_2"
    assert row["HTTP/2 Enabled"] is True
    assert row["Zones"] == "1, 2"
    assert row["HTTP Listeners"] == 1


# --- SSAZR-115 slice 2 / C-11: snapshot orphan scope ------------------------------

_THIS_SUB = "11111111-1111-1111-1111-111111111111"
_OTHER_SUB = "22222222-2222-2222-2222-222222222222"


def _disk_id(sub, name="d1"):
    return f"/subscriptions/{sub}/resourceGroups/rg1/providers/Microsoft.Compute/disks/{name}"


@pytest.mark.parametrize(
    "source_id, existing, expected",
    [
        (_disk_id(_THIS_SUB), {_disk_id(_THIS_SUB).lower()}, "No"),
        (_disk_id(_THIS_SUB), set(), "Yes"),
        (_disk_id(_THIS_SUB.upper()), set(), "Yes"),
        (_disk_id(_OTHER_SUB), set(), "N/A (other subscription)"),
        (f"/subscriptions/{_THIS_SUB}/resourceGroups/rg1/providers/Microsoft.Compute/snapshots/s0", set(), "N/A"),
        ("", set(), "N/A"),
    ],
)
def test_snapshot_orphan_only_within_current_subscription(source_id, existing, expected):
    assert snapshots_export._orphaned(source_id, _THIS_SUB, existing) == expected


def test_snapshot_row_reads_source_scope_case_insensitively():
    snap = SimpleNamespace(
        id=f"/subscriptions/{_THIS_SUB}/resourcegroups/RG-Snap/providers/Microsoft.Compute/snapshots/s1",
        name="s1", location="eastus", tags=None, os_type=None, disk_size_gb=None, sku=None,
        time_created=None, incremental=True, provisioning_state=None, encryption=None,
        network_access_policy=None, public_network_access=None,
        creation_data=SimpleNamespace(source_resource_id=_disk_id(_OTHER_SUB, "src")),
    )
    row = snapshots_export._build_row(snap, _THIS_SUB, set())
    assert row["Resource Group"] == "RG-Snap"
    assert row["Source Disk"] == "src"
    assert row["Source Resource Group"] == "rg1"
    assert row["Source Subscription"] == _OTHER_SUB
    assert row["Orphaned"] == "N/A (other subscription)"
    assert row["Encryption"] == ""


def test_snapshot_without_creation_data_is_not_orphaned():
    snap = SimpleNamespace(creation_data=None)
    assert snapshots_export._source_disk_id(snap) == ""


# --- SSAZR-115 slice 2 / C-16: subnet prefixes and attachments --------------------


def _subnet(**overrides):
    fields = {
        "name": "s1", "address_prefix": None, "address_prefixes": None, "network_security_group": None,
        "route_table": None, "nat_gateway": None, "delegations": None, "service_endpoints": None,
        "default_outbound_access": None, "provisioning_state": "Succeeded",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


_VNET = SimpleNamespace(id=f"{_NET}/virtualNetworks/vnet1", name="vnet1", location="eastus")


def test_subnet_multi_prefix_joins_address_prefixes():
    row = subnets_export._build_row(_VNET, _subnet(address_prefixes=["10.0.0.0/24", "fd00::/64"]))
    assert row["Address Prefix"] == "10.0.0.0/24, fd00::/64"
    assert row["No NSG"] is True
    assert row["Service Endpoint Count"] == 0
    assert row["Default Outbound Access"] == ""


def test_subnet_single_prefix_wins_over_prefix_list():
    row = subnets_export._build_row(_VNET, _subnet(address_prefix="10.1.0.0/24", address_prefixes=["ignored"]))
    assert row["Address Prefix"] == "10.1.0.0/24"


def test_subnet_attachments_and_delegations():
    subnet = _subnet(
        address_prefix="10.0.0.0/24",
        network_security_group=SimpleNamespace(id=f"{_NET}/networkSecurityGroups/nsg1"),
        nat_gateway=SimpleNamespace(id=f"{_NET}/natGateways/nat1"),
        delegations=[SimpleNamespace(service_name="Microsoft.Web/serverFarms")],
        service_endpoints=[SimpleNamespace(service="Microsoft.Storage"), SimpleNamespace(service="Microsoft.Sql")],
        default_outbound_access=False,
    )
    row = subnets_export._build_row(_VNET, subnet)
    assert row["NSG"] == "nsg1"
    assert row["No NSG"] is False
    assert row["NAT Gateway"] == "nat1"
    assert row["Delegations"] == "Microsoft.Web/serverFarms"
    assert row["Service Endpoint Count"] == 2
    assert row["Default Outbound Access"] is False


def test_subnet_row_against_real_sdk_model():
    models = pytest.importorskip("azure.mgmt.network.models")
    subnet = models.Subnet({
        "id": f"{_NET}/virtualNetworks/vnet1/subnets/s1", "name": "s1",
        "properties": {
            "addressPrefixes": ["10.0.0.0/24", "fd00::/64"],
            "delegations": [{"name": "d", "properties": {"serviceName": "Microsoft.Web/serverFarms"}}],
            "serviceEndpoints": [{"service": "Microsoft.Storage"}],
        },
    })
    row = subnets_export._build_row(_VNET, subnet)
    assert row["Address Prefix"] == "10.0.0.0/24, fd00::/64"
    assert row["No NSG"] is True
    assert row["Delegations"] == "Microsoft.Web/serverFarms"
    assert row["Service Endpoint Count"] == 1


# --- SSAZR-115 slice 2 / C-17: Cosmos DB API ----------------------------------------


class _CosmosKind(str, enum.Enum):
    GLOBAL_DOCUMENT_DB = "GlobalDocumentDB"
    MONGO_DB = "MongoDB"


def _cosmos(kind, capabilities=()):
    return SimpleNamespace(kind=kind, capabilities=[SimpleNamespace(name=c) for c in capabilities])


@pytest.mark.parametrize(
    "kind, capabilities, expected",
    [
        (_CosmosKind.MONGO_DB, (), "MongoDB"),
        ("MongoDB", ("EnableMongo",), "MongoDB"),
        (_CosmosKind.GLOBAL_DOCUMENT_DB, ("EnableCassandra",), "Cassandra"),
        ("GlobalDocumentDB", ("EnableServerless", "EnableGremlin"), "Gremlin"),
        ("GlobalDocumentDB", ("EnableTable",), "Table"),
        ("GlobalDocumentDB", ("EnableServerless",), "NoSQL"),
        ("GlobalDocumentDB", (), "NoSQL"),
        ("Parse", (), "Parse"),
        (None, (), ""),
    ],
)
def test_cosmos_api_from_kind_and_capabilities(kind, capabilities, expected):
    assert cosmos_db_export._api(_cosmos(kind, capabilities)) == expected


def test_cosmos_row_keeps_raw_capabilities():
    acct = SimpleNamespace(
        id="/subscriptions/s/resourceGroups/rg1/providers/Microsoft.DocumentDB/databaseAccounts/c1",
        name="c1", location="eastus", tags=None, kind="GlobalDocumentDB",
        capabilities=[SimpleNamespace(name="EnableServerless"), SimpleNamespace(name="EnableTable")],
        consistency_policy=None, document_endpoint=None, locations=None, enable_automatic_failover=None,
        enable_multiple_write_locations=None, public_network_access=None, provisioning_state=None,
        disable_local_auth=None, minimal_tls_version=None,
    )
    row = cosmos_db_export._build_row(acct)
    assert row["API"] == "Table"
    assert row["Capabilities"] == "EnableServerless, EnableTable"
    assert row["Automatic Failover"] == ""
    assert row["Disable Local Auth"] == ""


# --- SSAZR-115 slice 2 / C-14: App Service runtime read only when returned -------


def test_app_service_runtime_blank_when_site_config_not_returned():
    columns = app_service_export.site_config_columns(None)
    assert set(columns.values()) == {""}


def test_app_service_runtime_prefers_linux_then_windows_fx_version():
    linux = SimpleNamespace(
        linux_fx_version="PYTHON|3.12", windows_fx_version=None, net_framework_version="v4.0",
        node_version=None, python_version=None, php_version=None, java_version=None,
        min_tls_version="1.2", ftps_state="Disabled",
    )
    columns = app_service_export.site_config_columns(linux)
    assert columns["Runtime Stack"] == "PYTHON|3.12"
    assert columns[".NET Version"] == "v4.0"
    assert columns["Node Version"] == ""
    assert columns["Min TLS Version"] == "1.2"
    assert columns["FTPS State"] == "Disabled"

    windows = SimpleNamespace(
        linux_fx_version=None, windows_fx_version="DOTNET|8.0", net_framework_version=None,
        node_version=None, python_version=None, php_version=None, java_version=None,
        min_tls_version=None, ftps_state=None,
    )
    assert app_service_export.site_config_columns(windows)["Runtime Stack"] == "DOTNET|8.0"


# --- SSAZR-115 slice 2 / route tables: Routes sheet --------------------------------


def test_route_tables_export_writes_routes_sheet(monkeypatch):
    routes = [
        SimpleNamespace(name="default", address_prefix="0.0.0.0/0", next_hop_type="VirtualAppliance",
                        next_hop_ip_address="10.0.0.4", provisioning_state="Succeeded"),
        SimpleNamespace(name="local", address_prefix="10.0.0.0/16", next_hop_type="VnetLocal",
                        next_hop_ip_address=None, provisioning_state="Succeeded"),
    ]
    rt = SimpleNamespace(
        id=f"{_NET}/routeTables/rt1", name="rt1", location="eastus", tags=None, routes=routes,
        subnets=[SimpleNamespace(id="s")], disable_bgp_route_propagation=None, provisioning_state=None,
    )
    captured = {}
    monkeypatch.setattr(route_tables_export, "collect_route_tables", lambda subscription_id: [rt])
    monkeypatch.setattr(
        route_tables_export.utils, "save_multiple_dataframes_to_excel",
        lambda sheets, filename: captured.update(sheets),
    )
    route_tables_export.main("sub-id", "sub-name")

    summary = captured["Route Tables"].iloc[0]
    assert summary["Route Count"] == 2
    assert summary["Default Route Next Hop"] == "VirtualAppliance"
    assert summary["Disable BGP Route Propagation"] == ""

    routes_df = captured["Routes"]
    assert list(routes_df["Route Table"]) == ["rt1", "rt1"]
    assert list(routes_df["Next Hop Type"]) == ["VirtualAppliance", "VnetLocal"]
    assert list(routes_df["Next Hop IP"]) == ["10.0.0.4", ""]


# --- SSAZR-115 slice 2 / private endpoints: no model mutation ---------------------


def test_private_endpoint_connections_do_not_mutate_the_model():
    auto = [SimpleNamespace(private_link_service_id="/a/b/c", group_ids=["blob"],
                            private_link_service_connection_state=SimpleNamespace(status="Approved"))]
    manual = [SimpleNamespace(private_link_service_id="/a/b/d", group_ids=["file"],
                              private_link_service_connection_state=SimpleNamespace(status="Pending"))]
    pe = SimpleNamespace(private_link_service_connections=auto, manual_private_link_service_connections=manual)

    assert len(private_endpoints_export._connections(pe)) == 2
    assert len(private_endpoints_export._connections(pe)) == 2
    assert len(auto) == 1
    assert private_endpoints_export._target_resource(pe) == "c, d"
    assert private_endpoints_export._connection_status(pe) == "Approved, Pending"


# --- SSAZR-119: throttling and call shapes ------------------------------------------

_SCRIPTS = Path(__file__).parent.parent / "scripts"
_SUB_ID = "00000000-0000-0000-0000-000000000001"
_SA_ID = f"/subscriptions/{_SUB_ID}/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1"
_KV_ID = f"/subscriptions/{_SUB_ID}/resourceGroups/rg1/providers/Microsoft.KeyVault/vaults/kv1"


class _FakeResponse:
    def __init__(self, status_code, headers=None, body='{"error": {"code": "Throttled", "message": "slow down"}}'):
        self.status_code = status_code
        self.reason = "Too Many Requests" if status_code == 429 else "Error"
        self.headers = headers or {}
        self.content_type = "application/json"
        self.request = None
        self._body = body

    def text(self):
        return self._body


def _http_error(status_code, headers=None):
    return HttpResponseError(response=_FakeResponse(status_code, headers))


def _patch_export_io(monkeypatch, module, sheets_seen, tmp_path):
    monkeypatch.setattr(module.utils, "detect_environment", lambda: "public")
    monkeypatch.setattr(
        module.utils, "create_export_filename", lambda *a: str(tmp_path / "out.xlsx")
    )

    def _save(df, filename, sheet_name="Sheet1", errors=None):
        sheets_seen.append((sheet_name, df, list(errors or [])))

    monkeypatch.setattr(module.utils, "save_dataframe_to_excel", _save)


_SUBSCRIPTION_WIDE = [
    (api_management_export, "collect_services", "api_management_service", "list"),
    (event_hubs_export, "collect_namespaces", "namespaces", "list"),
    (logic_apps_export, "collect_workflows", "workflows", "list_by_subscription"),
    (mysql_flexible_export, "collect_servers", "servers", "list"),
    (postgresql_flexible_export, "collect_servers", "servers", "list_by_subscription"),
    (redis_cache_export, "collect_caches", "redis", "list_by_subscription"),
]


@pytest.mark.parametrize(
    "module, collect, operation_group, method",
    _SUBSCRIPTION_WIDE, ids=[m.__name__ for m, *_ in _SUBSCRIPTION_WIDE],
)
def test_subscription_wide_collect_uses_the_pinned_sdk_method(monkeypatch, module, collect, operation_group, method):
    """The method name matching the pinned wheel is tried first and no resource-group client is built."""
    item = SimpleNamespace(name="one")
    ops = SimpleNamespace(**{
        method: lambda: iter([item]),
        "list_by_resource_group": lambda rg: pytest.fail("per-RG fallback must be gone"),
    })
    services_requested = []

    def _client(service, sub_id=None):
        services_requested.append(service)
        return SimpleNamespace(**{operation_group: ops})

    monkeypatch.setattr(module.utils, "get_azure_client", _client)
    assert getattr(module, collect)(_SUB_ID) == [item]
    assert "resource" not in services_requested


@pytest.mark.parametrize("module", [m for m, *_ in _SUBSCRIPTION_WIDE], ids=[m.__name__ for m, *_ in _SUBSCRIPTION_WIDE])
def test_subscription_wide_collect_fails_loudly_when_the_sdk_renames_the_method(monkeypatch, module):
    monkeypatch.setattr(
        module.utils, "get_azure_client",
        lambda service, sub_id=None: SimpleNamespace(
            api_management_service=SimpleNamespace(), namespaces=SimpleNamespace(),
            workflows=SimpleNamespace(), servers=SimpleNamespace(), redis=SimpleNamespace(),
        ),
    )
    collect = next(c for m, c, *_ in _SUBSCRIPTION_WIDE if m is module)
    with pytest.raises(AttributeError):
        getattr(module, collect)(_SUB_ID)


@pytest.mark.parametrize(
    "script",
    ["api_management_export.py", "event_hubs_export.py", "logic_apps_export.py",
     "mysql_flexible_export.py", "postgresql_flexible_export.py", "redis_cache_export.py"],
)
def test_subscription_wide_exporters_carry_no_resource_group_fallback(script):
    source = (_SCRIPTS / script).read_text(encoding="utf-8")
    assert "utils.list_subscription_wide(" in source
    assert "list_by_resource_group" not in source
    assert "resource_groups.list(" not in source
    assert "hasattr(" not in source


# --- SSAZR-119: Storage RP list throttling (blob containers / file shares) --------------


class _FakeStorageClient:
    def __init__(self, answers, accounts=("sa1",)):
        self._answers = list(answers)
        self.calls = []
        self.storage_accounts = SimpleNamespace(
            list=lambda: iter(SimpleNamespace(id=_SA_ID.replace("sa1", a), name=a) for a in accounts)
        )
        self.blob_containers = SimpleNamespace(list=self._list)
        self.file_shares = SimpleNamespace(list=self._list)

    def _list(self, rg, account):
        self.calls.append((rg, account))
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return iter(answer)


def _container(name="c1"):
    return SimpleNamespace(
        name=name, metadata=None, public_access=None, lease_state=None, has_immutability_policy=False,
        has_legal_hold=False, default_encryption_scope="", last_modified_time=None,
    )


def _share(name="s1"):
    return SimpleNamespace(
        name=name, access_tier=None, share_quota=100, enabled_protocols=None, root_squash=None,
        lease_state=None, lease_status=None,
    )


_STORAGE_EXPORTERS = [
    (blob_containers_export, _container, "blob_containers.list"),
    (file_shares_export, _share, "file_shares.list"),
]


def _run_storage(monkeypatch, tmp_path, module, client):
    sheets = []
    _patch_export_io(monkeypatch, module, sheets, tmp_path)
    monkeypatch.setattr(module.utils, "get_azure_client", lambda service, sub_id=None: client)
    monkeypatch.delenv(module.PACE_ENV, raising=False)
    slept = []
    monkeypatch.setattr(module.time, "sleep", slept.append)
    result = module.main(_SUB_ID, "SUB")
    return result, sheets, slept


@pytest.mark.parametrize("module, item, operation", _STORAGE_EXPORTERS, ids=["blob", "files"])
def test_storage_list_429_is_retried_once_after_retry_after(monkeypatch, tmp_path, module, item, operation):
    client = _FakeStorageClient([_http_error(429, {"Retry-After": "7"}), [item()]])
    result, sheets, slept = _run_storage(monkeypatch, tmp_path, module, client)
    assert len(client.calls) == 2
    assert slept == [7.0]
    assert result.rows == 1
    assert result.errors == []


@pytest.mark.parametrize("module, item, operation", _STORAGE_EXPORTERS, ids=["blob", "files"])
def test_storage_second_429_is_recorded_not_retried_again(monkeypatch, tmp_path, module, item, operation):
    client = _FakeStorageClient([
        _http_error(429, {"Retry-After": "3"}), _http_error(429, {"Retry-After": "3"}),
    ])
    result, sheets, slept = _run_storage(monkeypatch, tmp_path, module, client)
    assert len(client.calls) == 2
    assert slept == [3.0]
    assert result.rows == 0
    assert [e["Operation"] for e in result.errors] == [operation]
    assert result.errors[0]["Scope"] == "sa1"


@pytest.mark.parametrize("module, item, operation", _STORAGE_EXPORTERS, ids=["blob", "files"])
def test_storage_429_without_retry_after_is_recorded_without_a_retry(monkeypatch, tmp_path, module, item, operation):
    client = _FakeStorageClient([_http_error(429)])
    result, sheets, slept = _run_storage(monkeypatch, tmp_path, module, client)
    assert len(client.calls) == 1
    assert slept == []
    assert [e["Operation"] for e in result.errors] == [operation]


@pytest.mark.parametrize("module, item, operation", _STORAGE_EXPORTERS, ids=["blob", "files"])
def test_storage_non_429_failure_is_recorded_and_isolated(monkeypatch, tmp_path, module, item, operation):
    client = _FakeStorageClient([_http_error(403), [item("kept")]], accounts=("sa1", "sa2"))
    result, sheets, slept = _run_storage(monkeypatch, tmp_path, module, client)
    assert slept == []
    assert result.rows == 1
    assert [e["Scope"] for e in result.errors] == ["sa1"]


@pytest.mark.parametrize("module, item, operation", _STORAGE_EXPORTERS, ids=["blob", "files"])
def test_storage_pacing_env_spaces_the_per_account_calls(monkeypatch, tmp_path, module, item, operation):
    client = _FakeStorageClient([[item()], [item()], [item()]], accounts=("sa1", "sa2", "sa3"))
    sheets = []
    _patch_export_io(monkeypatch, module, sheets, tmp_path)
    monkeypatch.setattr(module.utils, "get_azure_client", lambda service, sub_id=None: client)
    monkeypatch.setenv(module.PACE_ENV, "0.25")
    slept = []
    monkeypatch.setattr(module.time, "sleep", slept.append)
    result = module.main(_SUB_ID, "SUB")
    assert result.rows == 3
    assert slept == [0.25, 0.25]


@pytest.mark.parametrize("module", [m for m, *_ in _STORAGE_EXPORTERS], ids=["blob", "files"])
def test_storage_pacing_env_defaults_to_zero_and_rejects_garbage(monkeypatch, module):
    monkeypatch.delenv(module.PACE_ENV, raising=False)
    assert module.list_pace_seconds() == 0.0
    monkeypatch.setenv(module.PACE_ENV, "-4")
    assert module.list_pace_seconds() == 0.0
    monkeypatch.setenv(module.PACE_ENV, "soon")
    with pytest.raises(ValueError):
        module.list_pace_seconds()


def test_file_shares_unsupported_account_is_still_skipped_after_throttle_handling(monkeypatch, tmp_path):
    unsupported = HttpResponseError(response=_FakeResponse(
        400, body='{"error": {"code": "FeatureNotSupportedForAccount", "message": "no files"}}'
    ))
    client = _FakeStorageClient([unsupported, [_share()]], accounts=("sa1", "sa2"))
    result, sheets, slept = _run_storage(monkeypatch, tmp_path, file_shares_export, client)
    assert result.rows == 1
    assert result.errors == []


# --- SSAZR-119: Key Vault listing without per-vault get -----------------------------------


def _vault(name="kv1"):
    return SimpleNamespace(
        id=_KV_ID, name=name, location="eastus", tags={"env": "prod"},
        properties=SimpleNamespace(
            sku=SimpleNamespace(name="standard"), enable_soft_delete=True, soft_delete_retention_in_days=90,
            enable_purge_protection=True, enable_rbac_authorization=True, public_network_access="Enabled",
            vault_uri="https://kv1.vault.azure.net/",
        ),
    )


def _fake_keyvault_client(vaults):
    return SimpleNamespace(vaults=SimpleNamespace(
        list_by_subscription=lambda: iter(vaults),
        list=lambda: pytest.fail("vaults.list returns bare TrackedResource; must not be used"),
        get=lambda rg, name: pytest.fail("per-vault get must not be called"),
    ))


def test_key_vault_export_reads_properties_from_list_by_subscription(monkeypatch, tmp_path):
    sheets = []
    _patch_export_io(monkeypatch, key_vault_export, sheets, tmp_path)
    monkeypatch.setattr(key_vault_export.utils, "get_azure_client", lambda s, sub_id=None: _fake_keyvault_client([_vault()]))
    result = key_vault_export.main(_SUB_ID, "SUB")
    assert result.rows == 1 and result.errors == []
    (_, df, _) = sheets[0]
    row = df.iloc[0].to_dict()
    assert row["Resource Group"] == "rg1"
    assert row["SKU"] == "standard"
    assert row["Vault URI"] == "https://kv1.vault.azure.net/"
    assert list(df.columns) == [
        "Name", "Resource Group", "Location", "SKU", "Soft Delete Enabled", "Soft Delete Retention Days",
        "Purge Protection Enabled", "RBAC Authorization", "Public Network Access", "Vault URI", "Tags",
    ]


def test_key_vault_objects_collects_uris_from_list_by_subscription(monkeypatch):
    no_uri = _vault("kv2")
    no_uri.properties = SimpleNamespace(vault_uri=None)
    monkeypatch.setattr(
        key_vault_objects_export.utils, "get_azure_client",
        lambda s, sub_id=None: _fake_keyvault_client([_vault(), no_uri]),
    )
    uris, errors = key_vault_objects_export.collect_vault_uris(_SUB_ID)
    assert uris == [("kv1", "https://kv1.vault.azure.net/")]
    assert errors == []


def test_key_vault_exporters_never_call_vaults_get():
    for script in ("key_vault_export.py", "key_vault_objects_export.py"):
        source = (_SCRIPTS / script).read_text(encoding="utf-8")
        assert "vaults.list_by_subscription()" in source
        assert "vaults.get(" not in source
        assert "vaults.list()" not in source


# --- SSAZR-119 / C-14: App Service site configuration behind an explicit switch ------


def _site(name="app1", kind="app"):
    return SimpleNamespace(
        name=name, id=f"/subscriptions/{_SUB_ID}/resourceGroups/rg1/providers/Microsoft.Web/sites/{name}",
        resource_group="rg1", location="eastus", kind=kind, state="Running", https_only=True,
        default_host_name=f"{name}.azurewebsites.net", server_farm_id="/x/y/plan1", site_config=None,
        outbound_ip_addresses="1.2.3.4", tags=None, public_network_access="Enabled",
    )


def _site_config():
    return SimpleNamespace(
        linux_fx_version="PYTHON|3.12", windows_fx_version=None, net_framework_version="v4.0",
        node_version=None, python_version=None, php_version=None, java_version=None,
        min_tls_version="1.2", ftps_state="Disabled",
    )


class _FakeWebClient:
    def __init__(self, sites, config=None):
        self.config_calls = []
        self._config = config
        self.web_apps = SimpleNamespace(list=lambda: iter(sites), get_configuration=self._get_configuration)

    def _get_configuration(self, rg, name):
        self.config_calls.append((rg, name))
        if isinstance(self._config, Exception):
            raise self._config
        return self._config


_APP_EXPORTERS = [
    (app_service_export, "app", "collect_web_apps"),
    (function_apps_export, "functionapp,linux", "collect_function_apps"),
]


@pytest.mark.parametrize("module, kind, collect", _APP_EXPORTERS, ids=["app-service", "function-apps"])
def test_app_config_lookup_is_off_by_default(monkeypatch, module, kind, collect):
    monkeypatch.delenv(module.CONFIG_ENV, raising=False)
    client = _FakeWebClient([_site(kind=kind)], _site_config())
    errors = []
    rows = module.build_rows(client, getattr(module, collect)(client), errors)
    assert client.config_calls == []
    assert rows[0]["Runtime Stack"] == ""
    assert rows[0]["Min TLS Version"] == ""
    assert errors == []


@pytest.mark.parametrize("module, kind, collect", _APP_EXPORTERS, ids=["app-service", "function-apps"])
def test_app_config_lookup_fills_runtime_columns_when_enabled(monkeypatch, module, kind, collect):
    monkeypatch.setenv(module.CONFIG_ENV, "1")
    client = _FakeWebClient([_site(kind=kind)], _site_config())
    errors = []
    rows = module.build_rows(client, getattr(module, collect)(client), errors)
    assert client.config_calls == [("rg1", "app1")]
    assert rows[0]["Runtime Stack"] == "PYTHON|3.12"
    assert rows[0][".NET Version"] == "v4.0"
    assert rows[0]["Min TLS Version"] == "1.2"
    assert rows[0]["FTPS State"] == "Disabled"
    assert errors == []


@pytest.mark.parametrize("module, kind, collect", _APP_EXPORTERS, ids=["app-service", "function-apps"])
def test_app_config_lookup_failure_is_recorded_per_app(monkeypatch, module, kind, collect):
    monkeypatch.setenv(module.CONFIG_ENV, "1")
    client = _FakeWebClient([_site(kind=kind)], _http_error(403))
    errors = []
    rows = module.build_rows(client, getattr(module, collect)(client), errors)
    assert rows[0]["Runtime Stack"] == ""
    assert [e["Operation"] for e in errors] == ["web_apps.get_configuration"]
    assert errors[0]["Scope"] == "app1"


@pytest.mark.parametrize("value", ["", "0", "true", "yes"])
def test_app_config_switch_accepts_only_the_literal_1(monkeypatch, value):
    monkeypatch.setenv(app_service_export.CONFIG_ENV, value)
    assert app_service_export.config_lookup_enabled() is False
    monkeypatch.setenv(app_service_export.CONFIG_ENV, " 1 ")
    assert app_service_export.config_lookup_enabled() is True


def test_app_service_main_goes_partial_when_a_config_read_fails(monkeypatch, tmp_path):
    monkeypatch.setenv(app_service_export.CONFIG_ENV, "1")
    sheets = []
    _patch_export_io(monkeypatch, app_service_export, sheets, tmp_path)
    client = _FakeWebClient([_site(), _site("fn1", "functionapp")], _http_error(429))
    monkeypatch.setattr(app_service_export.utils, "get_azure_client", lambda s, sub_id=None: client)
    result = app_service_export.main(_SUB_ID, "SUB")
    assert result.rows == 1
    assert len(result.errors) == 1
    assert sheets[0][2] == result.errors
