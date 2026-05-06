"""
sslib.output — Output paths, filename conventions, and Excel writers.

In Azure Cloud Shell, default output goes to ~/clouddrive/stratusscan-azure/output/
so files survive session timeouts. Outside Cloud Shell, uses the project-local
output/ directory.
"""

import datetime
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def is_cloud_shell() -> bool:
    """
    Detect Azure Cloud Shell.

    Cloud Shell sets ACC_CLOUD and AZURE_HTTP_USER_AGENT in the environment.
    """
    return "ACC_CLOUD" in os.environ or "cloud-shell" in os.environ.get(
        "AZURE_HTTP_USER_AGENT", ""
    ).lower()


def get_output_dir() -> Path:
    """
    Resolve the output directory.

    Cloud Shell:  ~/clouddrive/stratusscan-azure/output/  (persistent across sessions)
    Otherwise:    <project_root>/output/
    """
    if is_cloud_shell():
        clouddrive = Path.home() / "clouddrive"
        if clouddrive.exists():
            d = clouddrive / "stratusscan-azure" / "output"
            d.mkdir(parents=True, exist_ok=True)
            return d

    d = Path(__file__).parent.parent / "output"
    d.mkdir(exist_ok=True)
    return d


def make_filename(scope_label: str, resource_type: str, suffix: str = "") -> str:
    """
    Build a standardized export filename.

        {SCOPE}-{resource-type}-{suffix}-export-{MM.DD.YYYY}.xlsx

    Same-day collisions get -v2, -v3, etc.
    """
    date = datetime.datetime.now().strftime("%m.%d.%Y")
    label = scope_label.replace(" ", "-").replace("/", "-")
    if suffix:
        base = f"{label}-{resource_type}-{suffix}-export-{date}.xlsx"
    else:
        base = f"{label}-{resource_type}-export-{date}.xlsx"

    output_dir = get_output_dir()
    candidate = base
    version = 2
    while (output_dir / candidate).exists():
        stem = base[: -len(".xlsx")]
        candidate = f"{stem}-v{version}.xlsx"
        version += 1
    return candidate


def snapshot_metadata(
    config: Dict[str, Any],
    cloud: Dict[str, str],
    sub_count: Optional[int] = None,
    exporter: Optional[str] = None,
):
    """
    Build a metadata DataFrame describing when/where this snapshot was taken.

    Prepend this as the first sheet of every exporter so the xlsx is
    self-describing (filename only carries date, not time or scope context).
    """
    import pandas as pd

    scope = (config or {}).get("default_scope", {}) or {}
    mode = scope.get("mode", "all")
    scope_value = f"{mode} ({sub_count} subscriptions)" if sub_count is not None else mode

    captured_at = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    rows = [
        {"Field": "Captured At (UTC)", "Value": captured_at},
        {"Field": "Tenant Name", "Value": (config or {}).get("tenant_name", "")},
        {"Field": "Active Cloud", "Value": cloud.get("name", "")},
        {"Field": "Subscription Scope", "Value": scope_value},
        {"Field": "Exporter", "Value": exporter or Path(sys.argv[0]).name},
    ]
    return pd.DataFrame(rows)


def _adjust_column_widths(worksheet, df) -> None:
    from openpyxl.utils import get_column_letter

    for i, column in enumerate(df.columns):
        col_label = str(column)
        try:
            # fillna("") first — pandas 3.x with PyArrow string dtype preserves
            # NaN (float) through astype(str), which then breaks .map(len).
            max_len = df[column].fillna("").astype(str).map(len).max()
            if max_len != max_len:  # NaN check (still possible for empty cols)
                max_len = 0
            width = max(int(max_len), len(col_label)) + 2
        except (ValueError, AttributeError, TypeError):
            width = len(col_label) + 2
        width = min(width, 50)
        worksheet.column_dimensions[get_column_letter(i + 1)].width = width


def save_dataframes(dfs: Dict[str, Any], filename: str) -> Optional[Path]:
    """
    Write a {sheet_name: DataFrame} dict to a multi-sheet xlsx in the output dir.

    Sheet names are truncated to 31 characters (Excel limit).
    """
    import pandas as pd  # noqa: F401  (informs the user if pandas is missing)

    if not dfs:
        logger.warning("No data to write — skipping %s", filename)
        return None

    path = get_output_dir() / filename

    try:
        import pandas as pd

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for sheet, df in dfs.items():
                safe_sheet = (sheet or "Data")[:31]
                df.to_excel(writer, sheet_name=safe_sheet, index=False)
                if not df.empty:
                    try:
                        _adjust_column_widths(writer.sheets[safe_sheet], df)
                    except Exception as e:
                        logger.warning("Column width adjust failed for %s: %s", safe_sheet, e)
        logger.info("Wrote %s", path)
        return path
    except Exception as e:
        logger.error("Failed to write Excel file %s: %s", path, e)
        return None
