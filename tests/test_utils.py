"""Smoke tests for utils.py — pure helpers and registry integrity, no live Azure."""

import enum
import re

import pytest

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


def test_archive_outputs_includes_optional_label(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "sample.xlsx").write_text("xlsx")
    monkeypatch.setattr(utils, "__file__", str(tmp_path / "utils.py"))
    monkeypatch.setattr(utils, "get_current_timestamp", lambda: "06.15.2026")

    zip_path = utils.archive_outputs("tier1")

    assert zip_path is not None
    assert zip_path.replace("\\", "/").endswith("/output/exports-tier1-06.15.2026.zip")


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


class _StrEnum(str, enum.Enum):
    INBOUND = "Inbound"


class _PlainEnum(enum.Enum):
    STANDARD = "Standard"
    COUNT = 3


def _read_rows(path, sheet):
    from openpyxl import load_workbook

    return [[c.value for c in row] for row in load_workbook(path)[sheet].iter_rows(min_row=2)]


def test_s_normalizes_none_enum_and_scalars():
    assert utils.s(None) == ""
    assert utils.s(_StrEnum.INBOUND) == "Inbound"
    assert utils.s(_PlainEnum.STANDARD) == "Standard"
    assert utils.s(_PlainEnum.COUNT) == "3"
    assert utils.s("plain") == "plain"
    assert utils.s(0) == "0"
    assert utils.s(False) == "False"


def test_s_never_renders_the_enum_class_name():
    assert "INBOUND" not in utils.s(_StrEnum.INBOUND)
    assert "_StrEnum" not in utils.s(_StrEnum.INBOUND)


def test_save_dataframe_to_excel_writes_enum_values_and_blank_none(tmp_path):
    import pandas as pd

    df = pd.DataFrame(
        [
            {"Direction": _StrEnum.INBOUND, "Tier": _PlainEnum.STANDARD, "Note": None, "Count": 2},
            {"Direction": "Outbound", "Tier": _PlainEnum.STANDARD, "Note": "x", "Count": 0},
        ]
    )
    path = str(tmp_path / "single.xlsx")

    utils.save_dataframe_to_excel(df, path)

    assert _read_rows(path, "Export") == [
        ["Inbound", "Standard", None, 2],
        ["Outbound", "Standard", "x", 0],
    ]


def test_save_dataframe_to_excel_does_not_mutate_the_callers_dataframe(tmp_path):
    import pandas as pd

    df = pd.DataFrame([{"Direction": _StrEnum.INBOUND}])

    utils.save_dataframe_to_excel(df, str(tmp_path / "keep.xlsx"))

    assert df["Direction"].iloc[0] is _StrEnum.INBOUND


def test_save_multiple_dataframes_to_excel_normalizes_every_sheet(tmp_path):
    import pandas as pd

    path = str(tmp_path / "multi.xlsx")

    utils.save_multiple_dataframes_to_excel(
        {
            "NSGs": pd.DataFrame([{"Direction": _StrEnum.INBOUND, "Rules": 4}]),
            "Rules": pd.DataFrame([{"Access": _PlainEnum.STANDARD, "Note": None}]),
        },
        path,
    )

    assert _read_rows(path, "NSGs") == [["Inbound", 4]]
    assert _read_rows(path, "Rules") == [["Standard", None]]


def test_get_azure_client_reports_renamed_class_as_import_error(monkeypatch):
    monkeypatch.setitem(utils._CLIENT_MAP, "subscription", ("json", "NoSuchClient", False))

    with pytest.raises(ImportError, match="NoSuchClient.*pyproject.toml"):
        utils.get_azure_client("subscription")


def test_get_azure_client_pip_hint_uses_distribution_name_for_nested_modules(monkeypatch):
    monkeypatch.setitem(
        utils._CLIENT_MAP, "resource", ("azure.mgmt.doesnotexist.resources", "Client", True)
    )

    with pytest.raises(ImportError, match=r"^Missing package: pip install azure-mgmt-doesnotexist$"):
        utils.get_azure_client("resource", "sub-id")
