"""Exporter unit tests — mocked Azure SDK models, no live Azure."""

import enum
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import advisor_export  # noqa: E402
import network_security_groups_export as nsg_export  # noqa: E402
import virtual_machines_export as vm_export  # noqa: E402


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
    assert result["Savings Currency"] == "USD"


def test_extract_savings_accepts_estimated_annual_alias():
    result = advisor_export._extract_savings({"estimatedAnnualSavings": "1200"})
    assert result["Potential Savings (Annual)"] == 1200.0


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


# --- SSAZR-112: NSG rule counting must survive Enum-typed direction -------------


class _Direction(str, enum.Enum):
    INBOUND = "Inbound"
    OUTBOUND = "Outbound"


def _nsg_rule(name, direction):
    return SimpleNamespace(
        name=name, priority=100, direction=direction, access="Allow", protocol="Tcp",
        source_port_range="*", source_port_ranges=None,
        destination_port_range="443", destination_port_ranges=None,
        source_address_prefix="*", source_address_prefixes=None,
        destination_address_prefix="*", destination_address_prefixes=None,
        description=None,
    )


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
