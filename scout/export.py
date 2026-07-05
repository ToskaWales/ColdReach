import csv
import os
from typing import List

import pandas as pd

from scout.models import Business, WebsiteCheckResult

SIGNAL_COLUMNS = [
    "no_https",
    "no_viewport",
    "old_copyright",
    "no_impressum",
    "old_cms",
    "frames_or_tables",
    "single_page",
]

COLUMNS = ["name", "adresse", "telefon", "website", "status", "status_detail", "score"] + SIGNAL_COLUMNS


def build_row(business: Business, result: WebsiteCheckResult) -> dict:
    row = {
        "name": business.name,
        "adresse": business.address,
        "telefon": business.phone,
        "website": business.website,
        "status": result.status,
        "status_detail": result.error_detail or result.raw_values.get("detail"),
        "score": result.score,
    }
    for key in SIGNAL_COLUMNS:
        row[key] = result.signals.get(key)
    return row


class IncrementalCSVWriter:
    """Appends one row at a time so a crash mid-run doesn't lose prior work
    (technical-design.md Abschnitt 9)."""

    def __init__(self, path: str):
        self.path = path
        is_new = not os.path.exists(path)
        self._file = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=COLUMNS)
        if is_new:
            self._writer.writeheader()
            self._file.flush()

    def write_row(self, row: dict):
        self._writer.writerow(row)
        self._file.flush()

    def close(self):
        self._file.close()


def build_dataframe(rows: List[dict], min_score: int = 0) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    filtered = df[df["score"].isna() | (df["score"] >= min_score)]
    return filtered.sort_values(by="score", ascending=False, na_position="last")


def write_dataframe(df: pd.DataFrame, output_path: str):
    if output_path.lower().endswith(".csv"):
        df.to_csv(output_path, index=False)
    else:
        df.to_excel(output_path, index=False)


def export_results(rows: List[dict], output_path: str, min_score: int = 0) -> pd.DataFrame:
    df = build_dataframe(rows, min_score)
    write_dataframe(df, output_path)
    return df
