"""Billing monthly spend exporter — month window, query shape, workbook layout. Fake Cost Management client, no live Azure."""

import datetime
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

openpyxl = pytest.importorskip("openpyxl")
azure_core = pytest.importorskip("azure.core.exceptions")

import billing_monthly_spend_export as billing  # noqa: E402

import utils  # noqa: E402

MONTHS = billing.month_window(datetime.date(2026, 9, 15))


def _in_latest_window(rows):
    """Cost Management answers each date window separately: only the window holding the latest month has this spend."""
    latest = billing.query_windows(MONTHS)[-1]
    start = f"{latest[0][:4]}-{latest[0][4:]}"

    def answer(body):
        return _result(rows) if body["timePeriod"]["from"].startswith(start) else _result([])

    return answer


def _result(rows, next_link=None, currency=True):
    names = ["PreTaxCost", "UsageDate"] + (["Currency"] if currency else [])
    return SimpleNamespace(columns=[SimpleNamespace(name=n) for n in names], rows=rows, next_link=next_link)


class _FakeCostClient:
    """query.usage answers per subscription scope; a callable answer sees the request body."""

    def __init__(self, answers, pages=()):
        self._answers = answers
        self._pages = list(pages)
        self.usage_calls = []
        self.requests = []
        self.query = SimpleNamespace(usage=self._usage)

    def _usage(self, scope, parameters):
        self.usage_calls.append((scope, parameters))
        answer = self._answers[scope]
        answer = answer(parameters) if callable(answer) else answer
        if isinstance(answer, Exception):
            raise answer
        return answer

    def send_request(self, request, **kwargs):
        self.requests.append(request)
        return self._pages.pop(0)


class _Page:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _denied():
    return azure_core.HttpResponseError(message="AuthorizationFailed")


# --- month window and query shape ------------------------------------------------


def test_month_window_ends_at_the_last_complete_month():
    window = billing.month_window(datetime.date(2026, 10, 7))
    assert len(window) == 13
    assert (window[0], window[-1]) == ("202509", "202609")


def test_month_window_crosses_a_year_boundary():
    window = billing.month_window(datetime.date(2026, 1, 15))
    assert (window[0], window[-1]) == ("202412", "202512")
    assert window == sorted(window) and len(set(window)) == 13


def test_thirteen_months_are_queried_in_windows_below_the_twelve_month_cap():
    windows = billing.query_windows(MONTHS)
    assert [len(w) for w in windows] == [7, 6]
    assert [m for w in windows for m in w] == MONTHS


def test_query_asks_for_monthly_actual_cost_over_whole_calendar_months():
    body = billing.build_query(["202601", "202602"])
    assert body["type"] == "ActualCost"
    assert body["timeframe"] == "Custom"
    assert body["timePeriod"] == {"from": "2026-01-01T00:00:00+00:00", "to": "2026-02-28T23:59:59+00:00"}
    assert body["dataset"]["granularity"] == "Monthly"
    assert body["dataset"]["aggregation"] == {"totalCost": {"name": "PreTaxCost", "function": "Sum"}}
    assert "grouping" not in body["dataset"]


def test_query_end_date_honors_leap_years():
    assert billing.build_query(["202402"])["timePeriod"]["to"].startswith("2024-02-29")


# --- collection ------------------------------------------------------------------


def test_spend_from_every_window_is_merged_by_month():
    window_one, window_two = billing.query_windows(MONTHS)

    def answer(body):
        first = body["timePeriod"]["from"][:7].replace("-", "")
        month = window_one[0] if first == window_one[0] else window_two[0]
        return _result([[10.0, int(month + "01"), "USD"], [2.5, int(month + "01"), "USD"]])

    client = _FakeCostClient({"/subscriptions/s1": answer})
    spend, currencies = billing.collect_subscription_spend(client, "s1", MONTHS)

    assert spend == {window_one[0]: 12.5, window_two[0]: 12.5}
    assert currencies == {"USD"}
    assert len(client.usage_calls) == 2


def test_usage_date_is_read_from_ints_and_iso_strings():
    client = _FakeCostClient({"/subscriptions/s1": _result([[1.0, 20260801, "USD"], [2.0, "2026-08-01T00:00:00", "USD"]])})
    spend, _ = billing.collect_subscription_spend(client, "s1", ["202608"])
    assert spend == {"202608": 3.0}


def test_next_link_pages_are_re_posted_with_the_same_body():
    pytest.importorskip("azure.mgmt.costmanagement.models")
    page = {"properties": {
        "columns": [{"name": "PreTaxCost", "type": "Number"}, {"name": "UsageDate", "type": "Number"}],
        "rows": [[4.0, 20260801]], "nextLink": None,
    }}
    client = _FakeCostClient(
        {"/subscriptions/s1": _result([[1.0, 20260801, "USD"]], next_link="https://management.azure.com/next")},
        pages=[_Page(page)],
    )
    spend, _ = billing.collect_subscription_spend(client, "s1", ["202608"])

    assert spend == {"202608": 5.0}
    (request,) = client.requests
    assert request.method == "POST" and request.url == "https://management.azure.com/next"
    assert json.loads(request.content) == client.usage_calls[0][1]


def test_a_204_window_contributes_no_spend():
    client = _FakeCostClient({"/subscriptions/s1": None})
    assert billing.collect_subscription_spend(client, "s1", MONTHS) == ({}, set())


def test_a_denied_subscription_is_recorded_and_the_rest_still_export(monkeypatch):
    client = _FakeCostClient({
        "/subscriptions/ok": _result([[5.0, int(MONTHS[-1] + "01"), "USD"]]),
        "/subscriptions/denied": _denied(),
    })
    monkeypatch.setattr(utils, "get_azure_client", lambda *a, **k: client)
    errors = []

    rows, currencies = billing.collect_spend([("denied", "Denied"), ("ok", "Ok")], MONTHS, errors)

    assert [name for name, _ in rows] == ["Ok"]
    assert [e["Scope"] for e in errors] == ["/subscriptions/denied"]
    assert currencies == {"USD"}


def test_every_subscription_denied_fails_the_run_instead_of_reporting_empty(monkeypatch):
    client = _FakeCostClient({"/subscriptions/a": _denied(), "/subscriptions/b": _denied()})
    monkeypatch.setattr(utils, "get_azure_client", lambda *a, **k: client)
    errors = []

    with pytest.raises(azure_core.HttpResponseError):
        billing.collect_spend([("a", "A"), ("b", "B")], MONTHS, errors)
    assert len(errors) == 2


def test_rows_are_ordered_by_latest_month_descending_then_name():
    latest = MONTHS[-1]
    rows = [("small", {latest: 1.0}), ("zeta", {latest: 5.0}), ("alpha", {latest: 5.0}), ("big", {latest: 50.0})]
    assert [n for n, _ in billing.ordered_rows(rows, MONTHS)] == ["big", "alpha", "zeta", "small"]


# --- workbook layout -------------------------------------------------------------


def _workbook(count=3, prefix="FCC", currency="USD"):
    rows = [(f"SUB-{i}", {m: float(i + 1) for m in MONTHS}) for i in range(count)]
    return billing.build_workbook(billing.ordered_rows(rows, MONTHS), MONTHS, prefix, currency)


def test_workbook_has_summary_then_monthly_sheet():
    assert _workbook().sheetnames == ["Azure Summary", "Azure Monthly Spend"]


def test_monthly_sheet_layout_matches_the_tracker_template():
    ws = _workbook(count=3)["Azure Monthly Spend"]
    assert ws["A1"].value == "FCC Azure Monthly Spend by Subscription — Actual Cost (USD)"
    assert {str(r) for r in ws.merged_cells.ranges} == {"A1:N1", "A9:N9"}
    assert ws["A2"].value == "Azure Subscription"
    assert [ws.cell(row=2, column=c).value for c in (2, 14)] == ["Aug 2025", "Aug 2026"]
    assert ws["B2"].fill.fgColor.rgb == "FF808080" and ws["C2"].fill.fgColor.rgb == "FF1F3864"
    assert ws["B3"].fill.fgColor.rgb == "FFEDEDED" and ws["B3"].font.i
    assert ws["A4"].fill.fgColor.rgb == "FFF2F5FB" and ws["A3"].fill.fill_type is None
    assert ws["A6"].value == "TOTAL" and ws["C6"].value == "=SUM(C3:C5)"
    assert ws["B7"].value == "MoM base"
    assert ws["C7"].value == '=IF(B6=0,"",(C6-B6)/B6)'
    assert ws["C7"].number_format == r"\+0.0%;\-0.0%"
    assert ws["C3"].number_format == '"$"#,##0.00'
    assert ws["A9"].value.startswith("Source: StratusScan billing-monthly-spend export")
    assert ws.freeze_panes == "B3"
    assert (ws.column_dimensions["A"].width, ws.column_dimensions["B"].width) == (34, 14)


def test_largest_subscription_is_listed_first():
    ws = _workbook(count=3)["Azure Monthly Spend"]
    assert [ws[f"A{r}"].value for r in (3, 4, 5)] == ["SUB-2", "SUB-1", "SUB-0"]


def test_summary_sheet_links_the_last_four_months_to_the_monthly_totals():
    ws = _workbook(count=3)["Azure Summary"]
    assert ws["A1"].value == "FCC Azure Monthly Spend — Summary — Actual Cost (USD)"
    assert [ws.cell(row=2, column=c).value for c in (2, 5)] == ["May 2026", "Aug 2026"]
    assert ws["A3"].value == "Microsoft Azure (3 subscriptions)"
    assert [ws.cell(row=3, column=c).value for c in (2, 5)] == ["='Azure Monthly Spend'!K6", "='Azure Monthly Spend'!N6"]
    assert ws["B4"].value == "=SUM(B3:B3)"
    assert ws["B5"].value == "=IF('Azure Monthly Spend'!J6=0,\"\",(B4-'Azure Monthly Spend'!J6)/'Azure Monthly Spend'!J6)"
    assert ws["C5"].value == '=IF(B4=0,"",(C4-B4)/B4)'
    assert (ws.column_dimensions["A"].width, ws.freeze_panes) == (48, "B3")


def test_summary_names_a_single_subscription_in_the_singular():
    assert _workbook(count=1)["Azure Summary"]["A3"].value == "Microsoft Azure (1 subscription)"


def test_title_has_no_stray_space_without_a_prefix():
    assert _workbook(prefix="")["Azure Monthly Spend"]["A1"].value.startswith("Azure Monthly Spend by Subscription")


def test_non_usd_workbooks_do_not_claim_dollars():
    ws = _workbook(currency="EUR")["Azure Monthly Spend"]
    assert "(EUR)" in ws["A1"].value and "$" not in ws["C3"].number_format


def test_subscription_names_that_look_like_formulas_are_neutralized():
    rows = [("=HYPERLINK(\"http://x\")", dict.fromkeys(MONTHS, 1.0))]
    ws = billing.build_workbook(rows, MONTHS)["Azure Monthly Spend"]
    assert ws["A3"].value.startswith("'=")


# --- end to end ------------------------------------------------------------------


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    monkeypatch.setenv(utils.OUTPUT_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(utils, "detect_environment", lambda: "public")
    monkeypatch.setattr(billing, "month_window", lambda today, count=13: MONTHS)
    monkeypatch.setattr(utils, "get_config", lambda: {billing.TITLE_PREFIX_KEY: "FCC"})

    def run(answers, subscriptions):
        monkeypatch.setattr(utils, "get_azure_client", lambda *a, **k: _FakeCostClient(answers))
        monkeypatch.setenv(utils.SCOPE_SUBSCRIPTIONS_ENV, utils.encode_scope_subscriptions(subscriptions))
        return billing.main(subscriptions[0][0], subscriptions[0][1])

    return run


def test_main_writes_one_workbook_covering_every_subscription_in_scope(run_main):
    latest = int(MONTHS[-1] + "01")
    result = run_main(
        {
            "/subscriptions/a": _in_latest_window([[10.0, latest, "USD"]]),
            "/subscriptions/b": _in_latest_window([[30.0, latest, "USD"]]),
        },
        [("a", "Alpha"), ("b", "Beta")],
    )

    assert result.rows == 2 and result.errors == []
    assert Path(result.filename).name.startswith("ALL-SUBSCRIPTIONS-billing-monthly-spend-13-months-export-")
    ws = openpyxl.load_workbook(result.filename)["Azure Monthly Spend"]
    assert [ws["A3"].value, ws["N3"].value, ws["A4"].value, ws["N4"].value] == ["Beta", 30.0, "Alpha", 10.0]
    assert ws["A1"].value.startswith("FCC ")


def test_main_with_one_subscription_names_the_file_after_it(run_main):
    result = run_main({"/subscriptions/a": _result([[1.0, int(MONTHS[-1] + "01"), "USD"]])}, [("a", "Alpha Sub")])
    assert Path(result.filename).name.startswith("ALPHA-SUB-billing-monthly-spend-")


def test_main_adds_an_errors_sheet_when_a_subscription_is_denied(run_main):
    result = run_main(
        {"/subscriptions/a": _result([[1.0, int(MONTHS[-1] + "01"), "USD"]]), "/subscriptions/b": _denied()},
        [("a", "Alpha"), ("b", "Beta")],
    )

    assert len(result.errors) == 1
    wb = openpyxl.load_workbook(result.filename)
    assert wb.sheetnames[-1] == "Errors"
    assert wb["Errors"]["A2"].value == "/subscriptions/b"


def test_main_flags_mixed_currencies_instead_of_summing_them_silently(run_main):
    latest = int(MONTHS[-1] + "01")
    result = run_main(
        {"/subscriptions/a": _result([[1.0, latest, "USD"]]), "/subscriptions/b": _result([[1.0, latest, "EUR"]])},
        [("a", "A"), ("b", "B")],
    )
    assert [e["Error Code"] for e in result.errors] == ["MixedCurrencies"]


def test_main_with_no_spend_anywhere_is_empty_and_writes_nothing(run_main, tmp_path):
    with pytest.raises(utils.NoResourcesFound):
        run_main({"/subscriptions/a": _result([])}, [("a", "Alpha")])
    assert list(tmp_path.glob("*.xlsx")) == []


def test_run_directly_covers_only_the_targeted_subscription(monkeypatch):
    monkeypatch.delenv(utils.SCOPE_SUBSCRIPTIONS_ENV, raising=False)
    assert utils.get_scope_subscriptions("s1", "One") == [("s1", "One")]


def test_scope_subscriptions_round_trip_and_ignore_garbage(monkeypatch):
    pairs = [("s1", "One"), ("s2", "Two")]
    monkeypatch.setenv(utils.SCOPE_SUBSCRIPTIONS_ENV, utils.encode_scope_subscriptions(pairs))
    assert utils.get_scope_subscriptions("x", "X") == pairs
    monkeypatch.setenv(utils.SCOPE_SUBSCRIPTIONS_ENV, "not json")
    assert utils.get_scope_subscriptions("x", "X") == [("x", "X")]
