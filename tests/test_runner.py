"""runner.run_exporter — exit codes, console shapes and manifest lines for every outcome. No live Azure."""

import io
import json
import logging
from types import SimpleNamespace

import pytest

import runner
import utils


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Manifest under tmp_path; the real console log handler (WARNING, stdout) redirected to a buffer."""
    manifest = tmp_path / ".run-manifest.jsonl"
    monkeypatch.setattr(utils, "manifest_path", lambda: manifest)
    monkeypatch.setattr(utils, "resolve_target_subscription", lambda: ("sub-1", "Sub One"))
    monkeypatch.setenv("STRATUSSCAN_RUN_ID", "t-run")
    console = io.StringIO()
    log = utils.setup_logging("widgets", log_to_file=False)
    for handler in log.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(console)
    logging_calls = []
    # run_exporter configures logging itself now; record the call instead of letting it
    # replace the buffered handler and write a real log file under logs/
    monkeypatch.setattr(
        utils, "setup_logging", lambda *a, **k: logging_calls.append((a, k)) or log
    )
    yield SimpleNamespace(manifest=manifest, console=console, logging_calls=logging_calls)
    log.handlers = []


def test_harness_console_buffer_receives_warnings(harness):
    utils.get_logger().warning("visible-marker")
    assert "visible-marker" in harness.console.getvalue()


def _records(harness):
    return [json.loads(line) for line in harness.manifest.read_text(encoding="utf-8").splitlines() if line]


def _run(main, harness, capsys):
    """Return (exit code, everything the operator would see on the terminal)."""
    with pytest.raises(SystemExit) as info:
        runner.run_exporter(main, "widgets")
    return info.value.code, capsys.readouterr().out + harness.console.getvalue()


def _http_error(code, message="The client does not have authorization.\nSecond line."):
    exceptions = pytest.importorskip("azure.core.exceptions")
    error = exceptions.HttpResponseError(message=message)
    error.error = SimpleNamespace(code=code)
    return error


def test_ok_exit_0_and_manifest_line(harness, capsys):
    def main(sub_id, sub_name):
        assert (sub_id, sub_name) == ("sub-1", "Sub One")
        return utils.ExportResult(rows=3, filename="/out/x.xlsx")

    code, out = _run(main, harness, capsys)
    assert code == 0
    assert out == ""
    (record,) = _records(harness)
    assert record["run_id"] == "t-run"
    assert record["script"] == "widgets"
    assert record["subscription_id"] == "sub-1"
    assert record["subscription_name"] == "Sub One"
    assert record["status"] == "OK"
    assert record["rows"] == 3
    assert record["file"] == "/out/x.xlsx"
    assert record["errors"] == 0
    assert isinstance(record["duration_s"], float)
    assert record["timestamp"]


def test_none_return_is_ok_for_backward_compat(harness, capsys):
    code, _ = _run(lambda sub_id, sub_name: None, harness, capsys)
    assert code == 0
    assert _records(harness)[0]["status"] == "OK"


def test_no_resources_found_exit_3_with_message(harness, capsys):
    def main(sub_id, sub_name):
        raise utils.NoResourcesFound("storage accounts")

    code, out = _run(main, harness, capsys)
    assert code == 3
    assert out.strip() == "No storage accounts found."
    record = _records(harness)[0]
    assert record["status"] == "EMPTY"
    assert record["rows"] == 0
    assert record["file"] is None


def test_partial_exit_4_when_errors_present(harness, capsys):
    errors = [utils.error_record("acct1", "blob_containers.list", RuntimeError("x"))]

    def main(sub_id, sub_name):
        return utils.ExportResult(rows=5, filename="/out/y.xlsx", errors=errors)

    code, out = _run(main, harness, capsys)
    assert code == 4
    assert out.strip() == "Completed with 1 error(s) — see the Errors sheet in /out/y.xlsx"
    record = _records(harness)[0]
    assert record["status"] == "PARTIAL"
    assert record["errors"] == 1
    assert record["rows"] == 5


def test_http_error_exit_1_one_line_with_rbac_hint_no_traceback(harness, capsys):
    error = _http_error("AuthorizationFailed")

    def main(sub_id, sub_name):
        raise error

    code, out = _run(main, harness, capsys)
    assert code == 1
    assert out.strip().splitlines() == [
        "AuthorizationFailed: The client does not have authorization.",
        runner.RBAC_HINT,
    ]
    assert "Traceback" not in out
    assert _records(harness)[0]["status"] == "FAILED"
    assert _records(harness)[0]["detail"].startswith("AuthorizationFailed:")


def test_http_error_without_rbac_code_has_no_hint(harness, capsys):
    error = _http_error("ResourceNotFound", "Not here.")

    def main(sub_id, sub_name):
        raise error

    code, out = _run(main, harness, capsys)
    assert code == 1
    assert out.strip() == "ResourceNotFound: Not here."


def test_client_authentication_error_exit_1_with_sign_in_hint(harness, capsys):
    exceptions = pytest.importorskip("azure.core.exceptions")
    error = exceptions.ClientAuthenticationError(
        message="DefaultAzureCredential failed\n\tAzureCliCredential: az login"
    )

    def main(sub_id, sub_name):
        raise error

    code, out = _run(main, harness, capsys)
    assert code == 1
    assert out.strip().splitlines() == [
        "Authentication failed: DefaultAzureCredential failed",
        runner.AUTH_HINT,
    ]


def test_azure_access_error_exit_1_with_hint(harness, capsys):
    error = utils.AzureAccessError(RuntimeError("no network"), "public")

    def main(sub_id, sub_name):
        raise error

    code, out = _run(main, harness, capsys)
    assert code == 1
    assert out.strip().splitlines() == [
        "Azure access failed — RuntimeError: no network",
        error.hint,
    ]


def test_value_error_from_environment_detection_exit_2(harness, capsys):
    def main(sub_id, sub_name):
        raise ValueError("AZURE_ENVIRONMENT='mars' is not a recognized Azure cloud.")

    code, out = _run(main, harness, capsys)
    assert code == 2
    assert out.strip() == "Configuration error: AZURE_ENVIRONMENT='mars' is not a recognized Azure cloud."
    assert _records(harness)[0]["status"] == "CONFIG"


def test_import_error_exit_2_with_pip_hint(harness, capsys):
    def main(sub_id, sub_name):
        raise ImportError("Missing package: pip install azure-mgmt-widgets")

    code, out = _run(main, harness, capsys)
    assert code == 2
    assert out.strip().splitlines() == [
        "Missing dependency: Missing package: pip install azure-mgmt-widgets",
        runner.IMPORT_HINT,
    ]


def test_keyboard_interrupt_exit_130(harness, capsys):
    def main(sub_id, sub_name):
        raise KeyboardInterrupt

    code, out = _run(main, harness, capsys)
    assert code == 130
    assert out.strip() == "Interrupted."
    assert _records(harness)[0]["status"] == "INTERRUPTED"


def test_unexpected_exception_exit_1_one_line(harness, capsys):
    def main(sub_id, sub_name):
        raise RuntimeError("boom\nmore detail")

    code, out = _run(main, harness, capsys)
    assert code == 1
    assert out.strip() == "RuntimeError: boom"
    assert _records(harness)[0]["detail"] == "RuntimeError: boom"


def test_traceback_goes_to_the_file_log_only(harness, capsys, tmp_path):
    log_file = tmp_path / "widgets.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    utils.get_logger().addHandler(file_handler)

    def main(sub_id, sub_name):
        raise RuntimeError("boom")

    code, out = _run(main, harness, capsys)
    file_handler.close()
    assert code == 1
    assert "Traceback" not in out
    logged = log_file.read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in logged
    assert "RuntimeError: boom" in logged


def test_no_subscription_exit_2_without_calling_main(harness, capsys, monkeypatch):
    monkeypatch.setattr(utils, "resolve_target_subscription", lambda: ("", ""))
    called = []

    code, out = _run(lambda *a: called.append(a), harness, capsys)
    assert code == 2
    assert out.strip() == runner.NO_SUBSCRIPTION_MESSAGE
    assert "configure.py first" not in out
    assert called == []
    assert _records(harness)[0]["status"] == "CONFIG"


def test_exporter_that_exits_itself_is_recorded_as_skipped(harness, capsys):
    def main(sub_id, sub_name):
        raise SystemExit(0)

    code, _ = _run(main, harness, capsys)
    assert code == 0
    assert _records(harness)[0]["status"] == "SKIPPED"


def test_wrong_return_type_is_a_failure(harness, capsys):
    code, out = _run(lambda sub_id, sub_name: {"rows": 1}, harness, capsys)
    assert code == 1
    assert out.startswith("TypeError:")
    assert "Traceback" not in out


def test_manifest_line_written_for_every_outcome(harness):
    outcomes = [
        lambda s, n: utils.ExportResult(rows=1, filename="/a.xlsx"),
        lambda s, n: (_ for _ in ()).throw(utils.NoResourcesFound("things")),
        lambda s, n: (_ for _ in ()).throw(RuntimeError("x")),
    ]
    for main in outcomes:
        with pytest.raises(SystemExit):
            runner.run_exporter(main, "widgets")
    assert [r["status"] for r in _records(harness)] == ["OK", "EMPTY", "FAILED"]


def test_runner_configures_logging_with_resolved_subscription(harness, capsys):
    def main(sub_id, sub_name):
        return utils.ExportResult(rows=1, filename="/out/z.xlsx")

    _run(main, harness, capsys)
    ((args, kwargs),) = harness.logging_calls
    assert args == ("widgets-export",)
    assert kwargs == {"subscription_id": "sub-1"}


def test_script_identity_uses_defining_module_file_and_docstring():
    file, description = runner._script_identity(runner.run_exporter)
    assert file == "runner.py"
    assert description == "StratusScanCLI-Azure — Exporter Runner"
