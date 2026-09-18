#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Exporter Runner

Console adapter shared by every script in scripts/. Resolves the target
subscription, calls the exporter's main(), turns its outcome into a documented
exit code and one console line, and appends the outcome to the run manifest
that stratusscan.py reads for the run report.

This module may print. utils.py may not.

Exit codes:
    0   OK        workbook written
    1   FAILED    an exception escaped main()
    2   CONFIG    no subscription targeted, bad AZURE_ENVIRONMENT, missing package
    3   EMPTY     zero resources — no workbook written
    4   PARTIAL   workbook written, but at least one scope failed (see Errors sheet)
    130 INTERRUPTED
"""

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import utils

try:
    from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
except ImportError:  # azure-core absent: main() raises ImportError, handled below
    class HttpResponseError(Exception):  # type: ignore[no-redef]
        pass

    class ClientAuthenticationError(HttpResponseError):  # type: ignore[no-redef]
        pass


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2
EXIT_EMPTY = 3
EXIT_PARTIAL = 4
EXIT_INTERRUPTED = 130

STATUS_BY_EXIT_CODE = {
    EXIT_OK: "OK",
    EXIT_FAILED: "FAILED",
    EXIT_CONFIG: "CONFIG",
    EXIT_EMPTY: "EMPTY",
    EXIT_PARTIAL: "PARTIAL",
    EXIT_INTERRUPTED: "INTERRUPTED",
}

NO_SUBSCRIPTION_MESSAGE = (
    "No subscription targeted. Set STRATUSSCAN_SUBSCRIPTION_ID, "
    "or run stratusscan.py (auto-discovers), or configure.py."
)
RBAC_ERROR_CODES = ("AuthorizationFailed", "Forbidden")
RBAC_HINT = (
    "Hint: the signed-in identity lacks read permission on this scope. "
    "Reader on the subscription covers every management-plane exporter."
)
AUTH_HINT = (
    "Hint: sign in (`az login`), or set AZURE_ENVIRONMENT if the active cloud is wrong."
)
IMPORT_HINT = "Hint: pip install the package named above, or run stratusscan.py to install dependencies."


def _log_failure(log, script_name: str, exc: BaseException, detail: str) -> None:
    """One-line record plus the traceback for the log file. The console handler
    sits at WARNING, so both stay out of the terminal — the print() is the console line."""
    log.info("Exporter %s failed: %s", script_name, detail)
    log.debug("Traceback for %s", script_name, exc_info=(type(exc), exc, exc.__traceback__))


def _exit_code_of(exc: SystemExit) -> int:
    if exc.code is None:
        return EXIT_OK
    if isinstance(exc.code, int):
        return exc.code
    return EXIT_FAILED


def _script_identity(main: Callable) -> tuple[str, str]:
    """(file name, first docstring line) of the module that defines main(), for the log header."""
    module = sys.modules.get(getattr(main, "__module__", ""))
    file = getattr(module, "__file__", None) or ""
    doc_lines = (getattr(module, "__doc__", None) or "").strip().splitlines()
    return (Path(file).name if file else "<unknown>", doc_lines[0] if doc_lines else "")


def run_exporter(main: Callable[[str, str], utils.ExportResult | None], script_name: str) -> None:
    """
    Run an exporter's main(subscription_id, subscription_name) and exit with its outcome.

    main returns utils.ExportResult, or None (treated as OK). Raising
    utils.NoResourcesFound means the primary listing was empty.
    """
    log = utils.get_logger()
    started = time.monotonic()
    sub_id, sub_name = "", ""

    def finish(code: int, *, rows: int | None = 0, filename: str | None = None,
               errors: int = 0, detail: str = "", status: str | None = None) -> None:
        utils.record_run_result(
            script=script_name,
            subscription_id=sub_id,
            subscription_name=sub_name,
            status=status or STATUS_BY_EXIT_CODE.get(code, "FAILED"),
            exit_code=code,
            rows=rows,
            file=filename,
            errors=errors,
            detail=detail,
            duration_s=round(time.monotonic() - started, 1),
        )
        log.info("Exporter %s finished: exit %d", script_name, code)
        sys.exit(code)

    sub_id, sub_name = utils.resolve_target_subscription()
    utils.setup_logging(f"{script_name}-export", subscription_id=sub_id or None)
    utils.log_script_start(*_script_identity(main))
    if not sub_id:
        print(NO_SUBSCRIPTION_MESSAGE)
        finish(EXIT_CONFIG, detail="no subscription targeted")

    try:
        result = main(sub_id, sub_name)
        if result is not None:
            result = _as_result(result)
    except utils.NoResourcesFound as exc:
        print(exc)
        finish(EXIT_EMPTY, rows=0, detail=str(exc))
    except ClientAuthenticationError as exc:
        message = utils.error_message(exc)
        detail = f"{type(exc).__name__}: {message}"
        _log_failure(log, script_name, exc, detail)
        print(f"Authentication failed: {message}")
        print(AUTH_HINT)
        finish(EXIT_FAILED, detail=detail)
    except HttpResponseError as exc:
        code = utils.error_code(exc)
        message = utils.error_message(exc)
        _log_failure(log, script_name, exc, f"{code}: {message}")
        print(f"{code}: {message}")
        if code in RBAC_ERROR_CODES:
            print(RBAC_HINT)
        finish(EXIT_FAILED, detail=f"{code}: {message}")
    except utils.AzureAccessError as exc:
        _log_failure(log, script_name, exc, str(exc))
        print(f"Azure access failed — {exc}")
        print(exc.hint)
        finish(EXIT_FAILED, detail=str(exc))
    except ValueError as exc:
        _log_failure(log, script_name, exc, str(exc))
        print(f"Configuration error: {exc}")
        finish(EXIT_CONFIG, detail=str(exc))
    except ImportError as exc:
        _log_failure(log, script_name, exc, str(exc))
        print(f"Missing dependency: {exc}")
        print(IMPORT_HINT)
        finish(EXIT_CONFIG, detail=str(exc))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        finish(EXIT_INTERRUPTED, detail="interrupted")
    except SystemExit as exc:
        # An exporter that exits itself (service unavailable in this cloud) is
        # a skip, not a result — record it so the run report shows it ran.
        code = _exit_code_of(exc)
        status = "SKIPPED" if code == EXIT_OK else None
        finish(code, rows=None, detail="exporter exited early", status=status)
    except Exception as exc:
        message = utils.error_message(exc)
        detail = f"{type(exc).__name__}: {message}"
        _log_failure(log, script_name, exc, detail)
        print(detail)
        finish(EXIT_FAILED, detail=detail)

    if result is None:
        finish(EXIT_OK, rows=None)

    error_count = len(result.errors)
    if error_count:
        where = f" — see the Errors sheet in {result.filename}" if result.filename else ""
        print(f"Completed with {error_count} error(s){where}")
        finish(EXIT_PARTIAL, rows=result.rows, filename=result.filename, errors=error_count,
               detail=f"{error_count} scope(s) failed")
    finish(EXIT_OK, rows=result.rows, filename=result.filename)


def _as_result(value: Any) -> utils.ExportResult:
    if isinstance(value, utils.ExportResult):
        return value
    raise TypeError(
        f"main() must return utils.ExportResult or None, got {type(value).__name__}"
    )
