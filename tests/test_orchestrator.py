"""stratusscan.py orchestration — status mapping, timeouts, run report and auto-run exit code. No subprocesses run."""

import json
import re
import subprocess
from types import SimpleNamespace

import pytest

import stratusscan
import utils

_EXPORTER = "storage_accounts_export.py"
_SUB = [("sub-1", "Sub One")]


@pytest.fixture
def manifest(monkeypatch, tmp_path):
    path = tmp_path / ".run-manifest.jsonl"
    monkeypatch.setattr(utils, "manifest_path", lambda: path)
    return path


def _fake_run(returncodes, manifest=None):
    """subprocess.run stand-in: pops the next return code, writing the manifest line the child would have."""
    calls = []

    def run(cmd, env=None, timeout=None):
        rc = returncodes.pop(0)
        calls.append({"cmd": cmd, "env": env, "timeout": timeout})
        if isinstance(rc, BaseException):
            raise rc
        if manifest is not None:
            status = stratusscan.status_for_exit_code(rc)
            record = {
                "run_id": env["STRATUSSCAN_RUN_ID"],
                "script": "storage-accounts",
                "subscription_id": env["STRATUSSCAN_SUBSCRIPTION_ID"],
                "status": status,
                "rows": 23 if rc in (0, 4) else (0 if rc == 3 else None),
                "errors": 3 if rc == 4 else 0,
                "file": "/out/x.xlsx" if rc in (0, 4) else None,
            }
            with open(manifest, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        return SimpleNamespace(returncode=rc)

    run.calls = calls
    return run


@pytest.mark.parametrize(
    "rc,status",
    [(0, "OK"), (3, "EMPTY"), (4, "PARTIAL"), (2, "CONFIG"), (1, "FAILED"), (130, "FAILED"), (-9, "FAILED")],
)
def test_status_for_exit_code(rc, status):
    assert stratusscan.status_for_exit_code(rc) == status


def test_run_id_shape():
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4}-\d{6}", stratusscan.new_run_id())


def test_run_exporter_injects_run_id_and_timeout(monkeypatch, manifest):
    fake = _fake_run([0], manifest)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setenv("STRATUSSCAN_EXPORTER_TIMEOUT", "42")

    status, rc, duration = stratusscan._run_exporter(_EXPORTER, "sub-1", "Sub One", "run-A")

    assert (status, rc) == ("OK", 0)
    assert isinstance(duration, float)
    call = fake.calls[0]
    assert call["timeout"] == 42
    assert call["env"]["STRATUSSCAN_RUN_ID"] == "run-A"
    assert call["env"]["STRATUSSCAN_SUBSCRIPTION_ID"] == "sub-1"
    assert call["env"]["STRATUSSCAN_SUBSCRIPTION_NAME"] == "Sub One"


def test_timeout_becomes_timeout_status_with_manifest_line(monkeypatch, manifest):
    fake = _fake_run([subprocess.TimeoutExpired(cmd="x", timeout=1800)])
    monkeypatch.setattr(subprocess, "run", fake)

    status, rc, _ = stratusscan._run_exporter(_EXPORTER, "sub-1", "Sub One", "run-T")

    assert (status, rc) == ("TIMEOUT", None)
    records = utils.read_run_results("run-T")
    assert [r["status"] for r in records] == ["TIMEOUT"]
    assert records[0]["script"] == "storage-accounts"


def test_missing_script_is_failed(capsys):
    status, rc, _ = stratusscan._run_exporter("nope_export.py", "sub-1", "Sub One", "run-X")
    assert (status, rc) == ("FAILED", 1)
    assert "Script not found" in capsys.readouterr().out


def test_per_exporter_lines_and_summary(monkeypatch, manifest, capsys):
    monkeypatch.setattr(subprocess, "run", _fake_run([0, 3, 4, 1], manifest))
    exporters = [("Storage Accounts", _EXPORTER)] * 4

    outcomes = stratusscan._run_all_exporters(exporters, _SUB, package_outputs=False, package_label="tier1")

    out = capsys.readouterr().out
    assert re.search(r"→ Storage Accounts\.\.\. OK \(23 rows, [\d.]+s\)", out)
    assert re.search(r"→ Storage Accounts\.\.\. EMPTY \([\d.]+s\)", out)
    assert re.search(r"→ Storage Accounts\.\.\. PARTIAL \(23 rows, 3 errors, [\d.]+s\)", out)
    assert "→ Storage Accounts... FAILED (exit 1)" in out
    assert "4 exporter run(s): 1 EMPTY, 1 FAILED, 1 OK, 1 PARTIAL" in out
    assert [o["Status"] for o in outcomes] == ["OK", "EMPTY", "PARTIAL", "FAILED"]
    assert stratusscan.has_failures(outcomes)


def test_run_report_columns_and_content(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "__file__", str(tmp_path / "utils.py"))
    outcomes = [{
        "Exporter": "Storage Accounts", "Subscription": "Sub One", "Status": "PARTIAL", "Rows": 23,
        "Errors": 3, "Duration (s)": 4.1, "File": "/out/x.xlsx", "Exit Code": 4,
    }]

    path = stratusscan.write_run_report(outcomes, "all", "run-R")

    assert path == str(tmp_path / "output" / "run-report-all-run-R.xlsx")
    pd = pytest.importorskip("pandas")
    df = pd.read_excel(path, sheet_name="Run Report")
    assert list(df.columns) == stratusscan.RUN_REPORT_COLUMNS
    assert df.iloc[0]["Status"] == "PARTIAL"
    assert int(df.iloc[0]["Errors"]) == 3
    assert stratusscan.write_run_report([], "all", "run-R") is None


def test_run_all_writes_report_and_zips_only_this_run(monkeypatch, manifest, tmp_path, capsys):
    monkeypatch.setattr(utils, "__file__", str(tmp_path / "utils.py"))
    monkeypatch.setattr(subprocess, "run", _fake_run([0], manifest))
    archived = {}
    monkeypatch.setattr(utils, "archive_outputs", lambda label, run_id=None: archived.update(label=label, run_id=run_id) or "/z.zip")

    stratusscan._run_all_exporters([("Storage Accounts", _EXPORTER)], _SUB, package_outputs=True, package_label="all")

    out = capsys.readouterr().out
    assert "Run report → " in out
    assert archived["label"] == "all"
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4}-\d{6}", archived["run_id"])
    assert "download /z.zip" in out


def test_ctrl_c_during_run_all_reports_progress_and_exits_130(monkeypatch, manifest, tmp_path, capsys):
    monkeypatch.setattr(utils, "__file__", str(tmp_path / "utils.py"))
    monkeypatch.setattr(subprocess, "run", _fake_run([0, KeyboardInterrupt()], manifest))
    exporters = [("Storage Accounts", _EXPORTER)] * 3

    with pytest.raises(SystemExit) as info:
        stratusscan._run_all_exporters(exporters, _SUB, package_outputs=True, package_label="all")

    assert info.value.code == 130
    out = capsys.readouterr().out
    assert "Interrupted" in out
    assert "1 exporter run(s): 1 OK" in out
    assert "Traceback" not in out
    assert list((tmp_path / "output").glob("run-report-all-*.xlsx"))


def test_single_exporter_across_subscriptions_reports_status_per_sub(monkeypatch, manifest, capsys):
    monkeypatch.setattr(subprocess, "run", _fake_run([0, 1], manifest))
    subs = [("sub-1", "Sub One"), ("sub-2", "Sub Two")]

    outcomes = stratusscan._run_exporter_across(_EXPORTER, "Storage Accounts", subs)

    out = capsys.readouterr().out
    assert re.search(r"→ Storage Accounts \[Sub One\]\.\.\. OK \(23 rows", out)
    assert "→ Storage Accounts [Sub Two]... FAILED (exit 1)" in out
    assert [(o["Subscription"], o["Status"]) for o in outcomes] == [("Sub One", "OK"), ("Sub Two", "FAILED")]


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["OK", "EMPTY"], 0),
        (["OK", "FAILED"], 1),
        (["OK", "PARTIAL"], 1),
        (["TIMEOUT"], 1),
        (["CONFIG"], 1),
        (["EMPTY", "EMPTY"], 0),
    ],
)
def test_auto_run_exit_code(monkeypatch, statuses, expected):
    monkeypatch.setenv("STRATUSSCAN_AUTO_RUN", "1")
    monkeypatch.setenv("STRATUSSCAN_SUBSCRIPTIONS", "sub-1")
    monkeypatch.delenv("AZURE_ENVIRONMENT", raising=False)
    outcomes = [{"Exporter": "x", "Subscription": "s", "Status": s} for s in statuses]
    monkeypatch.setattr(stratusscan, "_run_all_exporters", lambda *a, **k: outcomes)

    with pytest.raises(SystemExit) as info:
        stratusscan.main()

    assert info.value.code == expected
