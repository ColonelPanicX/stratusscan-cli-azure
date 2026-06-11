"""Smoke tests for utils.py — pure helpers and registry integrity, no live Azure."""

import re

import utils


def test_get_version_returns_nonempty_string():
    version = utils.get_version()
    assert isinstance(version, str)
    assert version


def test_get_current_timestamp_is_mm_dd_yyyy():
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", utils.get_current_timestamp())


def test_is_auto_run_reads_env(monkeypatch):
    monkeypatch.delenv("STRATUSSCAN_AUTO_RUN", raising=False)
    assert utils.is_auto_run() is False
    monkeypatch.setenv("STRATUSSCAN_AUTO_RUN", "1")
    assert utils.is_auto_run() is True
    monkeypatch.setenv("STRATUSSCAN_AUTO_RUN", "0")
    assert utils.is_auto_run() is False


def test_get_auto_subscriptions_parses_csv(monkeypatch):
    monkeypatch.delenv("STRATUSSCAN_SUBSCRIPTIONS", raising=False)
    assert utils.get_auto_subscriptions() == []
    monkeypatch.setenv("STRATUSSCAN_SUBSCRIPTIONS", " sub-a , sub-b ,, sub-c ")
    assert utils.get_auto_subscriptions() == ["sub-a", "sub-b", "sub-c"]


def test_create_export_filename_shape():
    path = utils.create_export_filename("My Sub Prod", "virtual-machines", "all")
    name = path.replace("\\", "/").split("/")[-1]
    assert name.endswith(".xlsx")
    assert name.startswith("MY-SUB-PROD-")
    assert "-virtual-machines-all-export-" in name
    assert re.search(r"-export-\d{2}\.\d{2}\.\d{4}\.xlsx$", name)


def test_create_export_filename_uppercases_and_sanitizes():
    name = utils.create_export_filename("a/b:c*d", "rg", "all").replace("\\", "/").split("/")[-1]
    # path-unsafe characters collapse to hyphens, result is upper-cased
    assert name.startswith("A-B-C-D-")


def test_extract_resource_group_handles_casing_and_missing():
    assert (
        utils.extract_resource_group(
            "/subscriptions/s/resourceGroups/Prod-RG/providers/Microsoft.Compute/x/y"
        )
        == "Prod-RG"
    )
    assert (
        utils.extract_resource_group(
            "/subscriptions/s/RESOURCEGROUPS/lower/providers/p/x/y"
        )
        == "lower"
    )
    assert utils.extract_resource_group("") == ""
    assert utils.extract_resource_group(None) == ""


def test_detect_environment_defaults_to_public(monkeypatch):
    monkeypatch.delenv("AZURE_ENVIRONMENT", raising=False)
    monkeypatch.setattr(utils, "get_config", lambda: {})
    assert utils.detect_environment() == "public"


def test_detect_environment_government_from_env(monkeypatch):
    monkeypatch.setenv("AZURE_ENVIRONMENT", "AzureUSGovernment")
    monkeypatch.setattr(utils, "get_config", lambda: {})
    assert utils.detect_environment() == "government"


def test_detect_environment_from_config_when_env_absent(monkeypatch):
    monkeypatch.delenv("AZURE_ENVIRONMENT", raising=False)
    monkeypatch.setattr(utils, "get_config", lambda: {"environment": "government"})
    assert utils.detect_environment() == "government"


def test_detect_azure_cloud_reads_az_config(monkeypatch, tmp_path):
    (tmp_path / "config").write_text("[cloud]\nname = AzureUSGovernment\n")
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    assert utils.detect_azure_cloud() == "government"

    (tmp_path / "config").write_text("[cloud]\nname = AzureCloud\n")
    assert utils.detect_azure_cloud() == "public"


def test_detect_azure_cloud_returns_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))  # empty dir, no config file
    assert utils.detect_azure_cloud() is None


def test_detect_environment_autodetects_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("AZURE_ENVIRONMENT", raising=False)
    # no config.json on disk → falls through to az auto-detect
    monkeypatch.setattr(utils.Path, "exists", lambda self: False)
    monkeypatch.setattr(utils, "detect_azure_cloud", lambda: "government")
    assert utils.detect_environment() == "government"


def test_is_service_available_in_environment_contract():
    assert utils.is_service_available_in_environment("compute", "public") is True
    assert utils.is_service_available_in_environment("network", "government") is True


def test_get_azure_client_rejects_unknown_service():
    try:
        utils.get_azure_client("not-a-real-service", "sub")
    except ValueError as exc:
        assert "not-a-real-service" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown service key")


def test_client_map_entries_are_well_formed():
    for key, entry in utils._CLIENT_MAP.items():
        assert key == key.lower(), f"{key!r} must be lowercase"
        assert isinstance(entry, tuple) and len(entry) == 3, f"{key!r} must be a 3-tuple"
        module_path, class_name, needs_sub = entry
        assert module_path.startswith("azure."), f"{key!r} module path looks wrong: {module_path}"
        assert class_name and class_name[0].isupper(), f"{key!r} class name looks wrong: {class_name}"
        assert isinstance(needs_sub, bool), f"{key!r} needs_sub must be bool"
