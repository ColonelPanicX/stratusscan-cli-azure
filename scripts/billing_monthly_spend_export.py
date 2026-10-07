#!/usr/bin/env python3
"""StratusScanCLI-Azure — Billing Monthly Spend (13 months of actual cost, one row per subscription)

Tenant-scoped: runs once and covers every subscription in the run's scope
(utils.get_scope_subscriptions), producing one tracker workbook:

    Azure Summary         last four months, one line per cloud provider
    Azure Monthly Spend   subscription x month grid with TOTAL and month-over-month rows

The month window ends at the last complete month, so a partial current month never
shows up as a spend drop. The Query API caps a custom date range, so each
subscription is queried in short windows and the months merged.
"""

import datetime
import re
import sys
from pathlib import Path
from typing import Any

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import cost_management_export
from azure.core.exceptions import HttpResponseError
from azure.core.rest import HttpRequest
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

log = utils.get_logger()

MONTHS_BACK = 13
WINDOW_MONTHS = 7
MAIN_SHEET = "Azure Monthly Spend"
SUMMARY_SHEET = "Azure Summary"
SUMMARY_MONTHS = 4
TITLE_PREFIX_KEY = "report_title_prefix"

TITLE_FILL = "FF2E5496"
HEADER_FILL = "FF1F3864"
BASE_HEADER_FILL = "FF808080"
BASE_CELL_FILL = "FFEDEDED"
BASE_CELL_FONT = "FF595959"
ZEBRA_FILL = "FFF2F5FB"
TOTAL_FILL = "FFBDD7EE"
CHANGE_FILL = "FFD9E1F2"
NOTE_FONT = "FF606060"
BORDER_COLOR = "FFAAB4C8"

WHITE = "FFFFFFFF"
BLACK = "FF000000"

CURRENCY_FORMAT = '"$"#,##0.00'
PLAIN_FORMAT = "#,##0.00"
CHANGE_FORMAT = r"\+0.0%;\-0.0%"

MonthKey = str  # YYYYMM


def month_window(today: datetime.date, count: int = MONTHS_BACK) -> list[MonthKey]:
    """The `count` complete months ending with the month before today's, oldest first."""
    index = today.year * 12 + (today.month - 1) - 1
    return [f"{(i // 12):04d}{(i % 12) + 1:02d}" for i in range(index - count + 1, index + 1)]


def month_label(key: MonthKey) -> str:
    return datetime.date(int(key[:4]), int(key[4:]), 1).strftime("%b %Y")


def _month_start(key: MonthKey) -> datetime.date:
    return datetime.date(int(key[:4]), int(key[4:]), 1)


def _month_end(key: MonthKey) -> datetime.date:
    start = _month_start(key)
    following = datetime.date(start.year + start.month // 12, start.month % 12 + 1, 1)
    return following - datetime.timedelta(days=1)


def query_windows(months: list[MonthKey], size: int = WINDOW_MONTHS) -> list[list[MonthKey]]:
    return [months[i:i + size] for i in range(0, len(months), size)]


def build_query(window: list[MonthKey]) -> dict:
    return {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {
            "from": f"{_month_start(window[0]).isoformat()}T00:00:00+00:00",
            "to": f"{_month_end(window[-1]).isoformat()}T23:59:59+00:00",
        },
        "dataset": {
            "granularity": "Monthly",
            "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
        },
    }


def _usage_month(value: Any) -> MonthKey:
    return re.sub(r"\D", "", str(value))[:6]


def _post_next_page(client, next_link: str, body: dict):
    from azure.mgmt.costmanagement.models import QueryResult

    response = client.send_request(HttpRequest("POST", next_link, json=body))
    if response.status_code == 204:
        return None
    if response.status_code != 200:
        raise HttpResponseError(response=response)
    return QueryResult(response.json())


def _accumulate(result, spend: dict[MonthKey, float], currencies: set[str]) -> None:
    columns = [getattr(c, "name", "") for c in (result.columns or [])]
    for raw in result.rows or []:
        row = dict(zip(columns, raw, strict=False))
        month = _usage_month(row.get("UsageDate"))
        if not month:
            continue
        spend[month] = spend.get(month, 0.0) + float(row.get("PreTaxCost") or row.get("Cost") or 0.0)
        if row.get("Currency"):
            currencies.add(str(row["Currency"]))


def collect_subscription_spend(
    client, subscription_id: str, months: list[MonthKey]
) -> tuple[dict[MonthKey, float], set[str]]:
    scope = f"/subscriptions/{subscription_id}"
    spend: dict[MonthKey, float] = {}
    currencies: set[str] = set()
    for window in query_windows(months):
        body = build_query(window)
        result = cost_management_export.call_with_throttle_retry(
            lambda body=body: client.query.usage(scope=scope, parameters=body), "query.usage"
        )
        while result is not None:
            _accumulate(result, spend, currencies)
            if not result.next_link:
                break
            next_link = result.next_link
            result = cost_management_export.call_with_throttle_retry(
                lambda link=next_link, body=body: _post_next_page(client, link, body),
                "query.usage(nextLink)",
            )
    return spend, currencies


def collect_spend(
    subscriptions: list[tuple[str, str]], months: list[MonthKey], errors: list
) -> tuple[list[tuple[str, dict[MonthKey, float]]], set[str]]:
    client = utils.get_azure_client("costmanagement")
    rows: list[tuple[str, dict[MonthKey, float]]] = []
    currencies: set[str] = set()
    last_failure: HttpResponseError | None = None
    for sub_id, sub_name in subscriptions:
        log.info("Querying %d months of cost for subscription %s", len(months), sub_id)
        try:
            spend, seen = collect_subscription_spend(client, sub_id, months)
        except HttpResponseError as exc:
            errors.append(utils.error_record(f"/subscriptions/{sub_id}", "query.usage", exc))
            log.warning("Cost query failed for %s: %s", sub_name, exc)
            last_failure = exc
            continue
        rows.append((sub_name, spend))
        currencies |= seen
    if not rows and last_failure is not None:
        raise last_failure
    return rows, currencies


def ordered_rows(
    rows: list[tuple[str, dict[MonthKey, float]]], months: list[MonthKey]
) -> list[tuple[str, dict[MonthKey, float]]]:
    latest = months[-1]
    return sorted(rows, key=lambda row: (-row[1].get(latest, 0.0), row[0].lower()))


def _side() -> Side:
    return Side(style="thin", color=BORDER_COLOR)


def _border() -> Border:
    return Border(left=_side(), right=_side(), top=_side(), bottom=_side())


def _fill(color: str) -> PatternFill:
    return PatternFill("solid", fgColor=color)


def _title_bar(ws, text: str, last_col: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    cell = ws.cell(row=1, column=1, value=text)
    cell.font = Font(name="Calibri", size=14, bold=True, color=WHITE)
    cell.fill = _fill(TITLE_FILL)
    cell.alignment = Alignment(horizontal="left")
    ws.row_dimensions[1].height = 24


def _header_cell(ws, column: int, text: str, fill: str = HEADER_FILL) -> None:
    cell = ws.cell(row=2, column=column, value=text)
    cell.font = Font(name="Calibri", size=11, bold=True, color=WHITE)
    cell.fill = _fill(fill)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = _border()


def _note(ws, row: int, text: str, last_col: int) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(name="Calibri", size=9, italic=True, color=NOTE_FONT)
    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)


def _money_cell(ws, row: int, column: int, value: Any, number_format: str, *, bold: bool = False,
                fill: str | None = None, color: str | None = None, italic: bool = False) -> None:
    cell = ws.cell(row=row, column=column, value=value)
    cell.font = Font(name="Calibri", size=11, bold=bold, italic=italic, color=color)
    cell.number_format = number_format
    cell.alignment = Alignment(horizontal="right")
    cell.border = _border()
    if fill:
        cell.fill = _fill(fill)


def _label_cell(ws, row: int, text: str, *, bold: bool = False, fill: str | None = None,
                left: bool = False, color: str | None = None) -> None:
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(name="Calibri", size=11, bold=bold, color=color)
    cell.border = _border()
    if left:
        cell.alignment = Alignment(horizontal="left")
    if fill:
        cell.fill = _fill(fill)


def _change_formula(current: str, previous: str) -> str:
    return f'=IF({previous}=0,"",({current}-{previous})/{previous})'


def _title(prefix: str, body: str, currency: str) -> str:
    return " ".join(part for part in (prefix.strip(), f"{body} — Actual Cost ({currency})") if part)


def _build_main_sheet(ws, rows, months, prefix: str, currency: str, number_format: str) -> int:
    last_col = len(months) + 1
    _title_bar(ws, _title(prefix, "Azure Monthly Spend by Subscription", currency), last_col)

    _header_cell(ws, 1, "Azure Subscription")
    for offset, month in enumerate(months):
        _header_cell(ws, offset + 2, month_label(month), BASE_HEADER_FILL if offset == 0 else HEADER_FILL)

    first_data = 3
    for index, (name, spend) in enumerate(rows):
        row = first_data + index
        zebra = ZEBRA_FILL if index % 2 else None
        _label_cell(ws, row, utils._guard_formula(name), fill=zebra, left=True)
        for offset, month in enumerate(months):
            if offset == 0:
                _money_cell(ws, row, 2, spend.get(month, 0.0), number_format,
                            fill=BASE_CELL_FILL, color=BASE_CELL_FONT, italic=True)
            else:
                _money_cell(ws, row, offset + 2, spend.get(month, 0.0), number_format, fill=zebra)

    last_data = first_data + len(rows) - 1
    total_row = last_data + 1
    change_row = total_row + 1
    _label_cell(ws, total_row, "TOTAL", bold=True, fill=TOTAL_FILL)
    _label_cell(ws, change_row, "Month-over-month change (%)", bold=True)
    for offset in range(len(months)):
        column = offset + 2
        letter = get_column_letter(column)
        _money_cell(ws, total_row, column, f"=SUM({letter}{first_data}:{letter}{last_data})",
                    number_format, bold=True, fill=TOTAL_FILL)
        if offset == 0:
            base = ws.cell(row=change_row, column=column, value="MoM base")
            base.font = Font(name="Calibri", size=11, italic=True, color=BASE_CELL_FONT)
            base.fill = _fill(BASE_CELL_FILL)
            base.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            base.border = _border()
        else:
            previous = get_column_letter(column - 1)
            _money_cell(ws, change_row, column,
                        _change_formula(f"{letter}{total_row}", f"{previous}{total_row}"),
                        CHANGE_FORMAT, bold=True, fill=CHANGE_FILL)

    _note(ws, change_row + 2,
          "Source: StratusScan billing-monthly-spend export (Azure Cost Management Query API, "
          f"ActualCost, monthly), one query per subscription, {len(rows)} subscription(s)",
          last_col)
    ws.column_dimensions["A"].width = 34
    for column in range(2, last_col + 1):
        ws.column_dimensions[get_column_letter(column)].width = 14
    ws.freeze_panes = "B3"
    return total_row


def _build_summary_sheet(ws, subscription_count: int, months, total_row: int, prefix: str,
                         currency: str, number_format: str) -> None:
    shown = months[-SUMMARY_MONTHS:]
    first_main_col = len(months) + 2 - len(shown)
    last_col = len(shown) + 1
    _title_bar(ws, _title(prefix, "Azure Monthly Spend — Summary", currency), last_col)

    _header_cell(ws, 1, "Cloud Service Provider")
    for offset, month in enumerate(shown):
        _header_cell(ws, offset + 2, month_label(month))

    plural = "subscription" if subscription_count == 1 else "subscriptions"
    _label_cell(ws, 3, f"Microsoft Azure ({subscription_count} {plural})", left=True, color=BLACK)
    _label_cell(ws, 4, "TOTAL CSP SPEND", bold=True, fill=TOTAL_FILL)
    _label_cell(ws, 5, "Month-over-month change (%)", bold=True)
    quoted = f"'{MAIN_SHEET}'"
    for offset in range(len(shown)):
        column = offset + 2
        letter = get_column_letter(column)
        source = get_column_letter(first_main_col + offset)
        _money_cell(ws, 3, column, f"={quoted}!{source}{total_row}", number_format)
        _money_cell(ws, 4, column, f"=SUM({letter}3:{letter}3)", number_format,
                    bold=True, fill=TOTAL_FILL)
        if offset == 0:
            previous_source = get_column_letter(first_main_col - 1)
            previous = f"{quoted}!{previous_source}{total_row}"
        else:
            previous = f"{get_column_letter(column - 1)}4"
        _money_cell(ws, 5, column, _change_formula(f"{letter}4", previous),
                    CHANGE_FORMAT, bold=True, fill=CHANGE_FILL)

    _note(ws, 7, f"Totals link to the '{MAIN_SHEET}' sheet.", last_col)
    ws.column_dimensions["A"].width = 48
    for column in range(2, last_col + 1):
        ws.column_dimensions[get_column_letter(column)].width = 14
    ws.freeze_panes = "B3"


def build_workbook(rows, months: list[MonthKey], prefix: str = "", currency: str = "USD") -> Workbook:
    number_format = CURRENCY_FORMAT if currency == "USD" else PLAIN_FORMAT
    wb = Workbook()
    summary = wb.active
    summary.title = SUMMARY_SHEET
    main = wb.create_sheet(MAIN_SHEET)
    total_row = _build_main_sheet(main, rows, months, prefix, currency, number_format)
    _build_summary_sheet(summary, len(rows), months, total_row, prefix, currency, number_format)
    return wb


def _append_errors_sheet(wb: Workbook, errors: list) -> None:
    ws = wb.create_sheet("Errors")
    ws.append(list(utils.ERROR_COLUMNS))
    for record in errors:
        ws.append([utils._guard_formula(record.get(column, "")) for column in utils.ERROR_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for letter, width in zip("ABCD", (48, 24, 28, 100), strict=False):
        ws.column_dimensions[letter].width = width


def _currency_of(currencies: set[str], errors: list) -> str:
    if not currencies:
        return "USD"
    primary = "USD" if "USD" in currencies else sorted(currencies)[0]
    if len(currencies) > 1:
        errors.append({
            "Scope": "tenant",
            "Operation": "currency check",
            "Error Code": "MixedCurrencies",
            "Message": f"Subscriptions bill in {', '.join(sorted(currencies))}; "
                       f"totals add them together without conversion.",
        })
    return primary


def _filename_label(subscriptions: list[tuple[str, str]]) -> str:
    return subscriptions[0][1] if len(subscriptions) == 1 else "ALL-SUBSCRIPTIONS"


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("costmanagement", environment):
        sys.exit(0)

    subscriptions = utils.get_scope_subscriptions(subscription_id, subscription_name)
    months = month_window(datetime.date.today())
    errors: list = []
    rows, currencies = collect_spend(subscriptions, months, errors)
    if not any(spend for _, spend in rows):
        if errors:
            raise utils.NoResourcesFound("billing data for the subscriptions that could be queried")
        raise utils.NoResourcesFound("billing data")

    currency = _currency_of(currencies, errors)
    prefix = str(utils.get_config().get(TITLE_PREFIX_KEY, "") or "")
    wb = build_workbook(ordered_rows(rows, months), months, prefix, currency)
    if errors:
        _append_errors_sheet(wb, errors)

    filename = utils.create_export_filename(
        _filename_label(subscriptions), "billing-monthly-spend", f"{len(months)}-months"
    )
    wb.save(filename)
    print(f"Exported {len(rows)} subscription row(s) × {len(months)} months → {filename}")
    log.info("Export complete: %d subscriptions, %d months", len(rows), len(months))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "billing-monthly-spend")
