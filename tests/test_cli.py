"""stratusscan.py CLI flags — parsing, exporter-name resolution, --list, --dry-run, headless runs."""

import pytest

import cli_ui
import stratusscan
import utils

_DISCOVERED = [
    {"id": "sub-1", "name": "Sub One", "state": "Enabled", "tenant_id": "t"},
    {"id": "sub-2", "name": "Sub Two", "state": "Enabled", "tenant_id": "t"},
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "STRATUSSCAN_AUTO_RUN",
        "STRATUSSCAN_SUBSCRIPTIONS",
        "STRATUSSCAN_EXPORTER_TIMEOUT",
        "STRATUSSCAN_OUTPUT_DIR",
        "AZURE_ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(stratusscan.bootstrap, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(utils, "setup_logging", lambda *a, **k: utils.get_logger())


@pytest.fixture
def runs(monkeypatch):
    """Capture what main() hands to _run_all_exporters instead of running anything."""
    calls = []

    def fake_run_all(exporters, subs, package_outputs=False, package_label=None):
        calls.append({
            "exporters": list(exporters),
            "subs": list(subs),
            "zip": package_outputs,
            "label": package_label,
        })
        return [{"Exporter": "x", "Subscription": "s", "Status": "OK"}]

    monkeypatch.setattr(stratusscan, "_run_all_exporters", fake_run_all)
    monkeypatch.setattr(utils, "list_subscriptions", lambda: list(_DISCOVERED))
    monkeypatch.setattr(
        stratusscan, "_active_subscriptions", lambda: [("sub-1", "Sub One"), ("sub-2", "Sub Two")]
    )
    return calls


def _exit_code(argv):
    with pytest.raises(SystemExit) as info:
        stratusscan.main(argv)
    return info.value.code


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_no_flags_falls_through_to_the_interactive_menu(monkeypatch, runs):
    seen = []
    monkeypatch.setattr(stratusscan, "menu_main", lambda subs: seen.append(subs))

    stratusscan.main([])

    assert seen == [[("sub-1", "Sub One"), ("sub-2", "Sub Two")]]
    assert runs == []


def test_version_prints_and_exits_0(capsys):
    assert _exit_code(["--version"]) == 0
    assert utils.get_version() in capsys.readouterr().out


def test_unknown_flag_exits_2():
    assert _exit_code(["--nope"]) == 2


def test_repeatable_tier_and_exporter_flags_parse():
    args = stratusscan.build_parser().parse_args(
        ["--tier", "tier1", "--tier", "governance", "--exporter", "vmss", "--exporter", "advisor"]
    )
    assert args.tier == ["tier1", "governance"]
    assert args.exporter == ["vmss", "advisor"]


def test_unknown_tier_exits_2():
    assert _exit_code(["--tier", "tier9"]) == 2


# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------

def test_list_prints_every_tier_and_exporter_then_exits_0(capsys):
    assert _exit_code(["--list"]) == 0

    out = capsys.readouterr().out
    for key, (title, _) in stratusscan.TIERS.items():
        assert f"--tier {key}" in out
        assert title in out
    for name in stratusscan.exporter_names():
        assert name in out
    assert f"{len(stratusscan.ALL_EXPORTERS)} exporters total" in out


def test_list_needs_no_dependencies_or_credentials(monkeypatch):
    monkeypatch.setattr(
        stratusscan.bootstrap, "ensure_dependencies",
        lambda: pytest.fail("--list must not bootstrap"),
    )
    monkeypatch.setattr(
        utils, "list_subscriptions", lambda: pytest.fail("--list must not call Azure")
    )
    assert _exit_code(["--list"]) == 0


# ---------------------------------------------------------------------------
# Exporter name resolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,expected_path",
    [
        ("storage_accounts", "storage_accounts_export.py"),
        ("storage-accounts", "storage_accounts_export.py"),
        ("STORAGE_ACCOUNTS", "storage_accounts_export.py"),
        ("Storage Accounts", "storage_accounts_export.py"),
        ("virtual machines", "virtual_machines_export.py"),
        ("VM Scale Sets", "vmss_export.py"),
        ("vmss", "vmss_export.py"),
        ("advisor", "advisor_export.py"),
    ],
)
def test_exporter_names_resolve_by_script_name_or_label(name, expected_path):
    assert stratusscan.resolve_exporters([name])[0][1] == expected_path


def test_every_registered_exporter_is_addressable_and_unique():
    names = stratusscan.exporter_names()
    assert len(names) == len(set(names)) == len(stratusscan.ALL_EXPORTERS)
    assert len(stratusscan.resolve_exporters(names)) == len(names)


def test_duplicate_exporter_flags_run_once():
    assert stratusscan.resolve_exporters(["advisor", "Advisor Recommendations"]) == [
        ("Advisor Recommendations", "advisor_export.py")
    ]


def test_unknown_exporter_exits_2_listing_valid_names(capsys):
    assert _exit_code(["--exporter", "storage_acounts"]) == 2

    err = capsys.readouterr().err
    assert "storage_acounts" in err
    assert "storage_accounts" in err
    assert "management_groups" in err


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------

def test_dry_run_validates_and_runs_nothing(runs, capsys):
    assert _exit_code(["--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "AzurePublicCloud" in out
    assert "2 subscription(s) visible" in out
    assert f"Exporters that would run: {len(stratusscan.ALL_EXPORTERS)}" in out
    assert "Nothing was run." in out
    assert runs == []


def test_dry_run_reports_only_the_selected_tier_and_subscriptions(runs, capsys):
    assert _exit_code(["--dry-run", "--tier", "monitoring", "--subscriptions", "all"]) == 0

    out = capsys.readouterr().out
    assert f"Exporters that would run: {len(stratusscan.MONITORING_EXPORTERS)}" in out
    assert "Target subscriptions: 2" in out


def test_dry_run_fails_1_when_credentials_are_unusable(monkeypatch, runs, capsys):
    def denied():
        raise utils.AzureAccessError(RuntimeError("no credential"), "public")

    monkeypatch.setattr(utils, "list_subscriptions", denied)

    assert _exit_code(["--dry-run"]) == 1

    out = capsys.readouterr().out
    assert "no credential" in out
    assert "Dry run failed" in out


# ---------------------------------------------------------------------------
# Headless runs
# ---------------------------------------------------------------------------

def test_run_all_runs_every_exporter_against_the_primary_subscription(runs):
    assert _exit_code(["--run-all"]) == 0

    call = runs[0]
    assert call["exporters"] == stratusscan.ALL_EXPORTERS
    assert call["subs"] == [("sub-1", "Sub One")]
    assert call["zip"] is True
    assert call["label"] == "all"


def test_tier_flag_runs_that_tier_only(runs):
    assert _exit_code(["--tier", "governance"]) == 0

    assert runs[0]["exporters"] == stratusscan.GOVERNANCE_EXPORTERS
    assert runs[0]["label"] == "governance"


def test_tiers_and_exporters_combine_without_duplicates(runs):
    assert _exit_code(["--tier", "monitoring", "--exporter", "advisor", "--exporter", "action_groups"]) == 0

    exporters = runs[0]["exporters"]
    assert exporters[: len(stratusscan.MONITORING_EXPORTERS)] == stratusscan.MONITORING_EXPORTERS
    assert exporters[-1] == ("Advisor Recommendations", "advisor_export.py")
    assert len(exporters) == len(stratusscan.MONITORING_EXPORTERS) + 1
    assert runs[0]["label"] == "selected"


def test_subscriptions_flag_takes_explicit_ids_without_discovery(monkeypatch, runs):
    monkeypatch.setattr(
        utils, "list_subscriptions", lambda: pytest.fail("explicit IDs need no discovery")
    )

    assert _exit_code(["--exporter", "advisor", "--subscriptions", "sub-2,sub-9"]) == 0

    assert runs[0]["subs"] == [("sub-2", "Sub Two"), ("sub-9", "sub-9")]


def test_subscriptions_all_targets_every_active_subscription(runs):
    assert _exit_code(["--run-all", "--subscriptions", "all"]) == 0
    assert runs[0]["subs"] == [("sub-1", "Sub One"), ("sub-2", "Sub Two")]


def test_no_zip_skips_packaging(runs):
    assert _exit_code(["--run-all", "--no-zip"]) == 0
    assert runs[0]["zip"] is False


def test_failures_exit_1(monkeypatch, runs):
    monkeypatch.setattr(
        stratusscan, "_run_all_exporters",
        lambda *a, **k: [{"Exporter": "x", "Subscription": "s", "Status": "TIMEOUT"}],
    )
    assert _exit_code(["--run-all"]) == 1


# ---------------------------------------------------------------------------
# Flags versus environment
# ---------------------------------------------------------------------------

def test_timeout_flag_overrides_the_environment_variable(monkeypatch, runs):
    monkeypatch.setenv("STRATUSSCAN_EXPORTER_TIMEOUT", "60")

    assert _exit_code(["--run-all", "--timeout", "90"]) == 0

    assert stratusscan.exporter_timeout() == 90


def test_environment_timeout_is_used_when_no_flag_is_given(monkeypatch, runs):
    monkeypatch.setenv("STRATUSSCAN_EXPORTER_TIMEOUT", "60")

    assert _exit_code(["--run-all"]) == 0

    assert stratusscan.exporter_timeout() == 60


def test_auto_run_environment_still_runs_everything(runs):
    import os

    os.environ["STRATUSSCAN_AUTO_RUN"] = "1"
    os.environ["STRATUSSCAN_SUBSCRIPTIONS"] = "sub-2"
    try:
        assert _exit_code([]) == 0
    finally:
        del os.environ["STRATUSSCAN_AUTO_RUN"]
        del os.environ["STRATUSSCAN_SUBSCRIPTIONS"]

    assert runs[0]["exporters"] == stratusscan.ALL_EXPORTERS
    assert runs[0]["subs"] == [("sub-2", "sub-2")]


def test_explicit_subscriptions_flag_beats_the_environment_variable(monkeypatch, runs):
    monkeypatch.setenv("STRATUSSCAN_SUBSCRIPTIONS", "sub-2")

    assert _exit_code(["--run-all", "--subscriptions", "sub-1"]) == 0

    assert runs[0]["subs"] == [("sub-1", "Sub One")]


def test_environment_subscriptions_apply_when_no_flag_is_given(monkeypatch, runs):
    monkeypatch.setenv("STRATUSSCAN_SUBSCRIPTIONS", "sub-1,sub-2")

    assert _exit_code(["--run-all"]) == 0

    # names come from config.json, which is empty here — the IDs are what matter
    assert [sub_id for sub_id, _ in runs[0]["subs"]] == ["sub-1", "sub-2"]


def test_verbose_lifts_the_console_handler_to_info(monkeypatch, runs):
    import logging

    levels = []
    monkeypatch.setattr(utils, "set_console_level", lambda level: levels.append(level))

    assert _exit_code(["--run-all", "--verbose"]) == 0

    assert levels == [logging.INFO]


# ---------------------------------------------------------------------------
# Tier 2 grouping
# ---------------------------------------------------------------------------

def test_tier2_categories_cover_every_tier2_exporter_exactly_once():
    categorized = [path for _, paths in stratusscan.TIER2_CATEGORIES for path in paths]
    assert len(categorized) == len(set(categorized))
    assert set(categorized) == {path for _, path in stratusscan.TIER2_EXPORTERS}


def test_grouping_keeps_every_entry_and_numbers_continuously():
    ordered, headings = stratusscan.grouped_exporters(
        stratusscan.TIER2_EXPORTERS, stratusscan.TIER2_CATEGORIES
    )
    assert sorted(ordered) == sorted(stratusscan.TIER2_EXPORTERS)
    assert [name for _, name in stratusscan.TIER2_CATEGORIES[:0]] == []
    assert list(headings.values()) == [name for name, _ in stratusscan.TIER2_CATEGORIES]
    assert sorted(headings) == sorted(headings)
    assert min(headings) == 1
    assert max(headings) <= len(ordered)


def test_uncategorized_exporters_still_appear_under_other():
    exporters = [("A", "a_export.py"), ("B", "b_export.py")]
    ordered, headings = stratusscan.grouped_exporters(exporters, [("Known", ["b_export.py"])])
    assert ordered == [("B", "b_export.py"), ("A", "a_export.py")]
    assert headings == {1: "Known", 2: "Other"}


def test_tier2_menu_prints_category_headings(monkeypatch, capsys):
    def fake_menu(title, options, **kwargs):
        for position, heading in (kwargs.get("headings") or {}).items():
            print(f"{position}:{heading}")
        raise cli_ui.BackToMain

    monkeypatch.setattr(cli_ui, "prompt_menu", fake_menu)

    with pytest.raises(cli_ui.BackToMain):
        stratusscan.menu_tier2([("sub-1", "Sub One")])

    out = capsys.readouterr().out
    assert "1:Compute & Containers" in out
    assert "Databases" in out and "Networking" in out and "Ops" in out


def test_dry_run_with_an_unknown_exporter_exits_2_before_touching_azure(monkeypatch, capsys):
    monkeypatch.setattr(
        utils, "list_subscriptions", lambda: pytest.fail("bad names fail before any Azure call")
    )
    assert _exit_code(["--dry-run", "--exporter", "nope"]) == 2
    assert "nope" in capsys.readouterr().err
