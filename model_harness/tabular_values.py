"""Shared scalar semantics for CSV training, new samples and delivery examples."""

from __future__ import annotations

import inspect
import math
from typing import Any


def normalize_tabular_value(value: Any, numeric: bool) -> float | str | None:
    """Keep missing values JSON-safe; sklearn's numeric imputer casts None to NaN."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if not numeric:
        return text
    parsed = float(text)
    if not math.isfinite(parsed):
        raise ValueError("numeric features must be finite")
    return parsed


def tabular_inference_example() -> str:
    # Ship the exact normalizer used by training, without requiring this package
    # at inference time. The trusted estimator only depends on sklearn/joblib.
    return (
        "import csv\nimport math\nfrom typing import Any\nimport joblib\n\n"
        + inspect.getsource(normalize_tabular_value)
        + "\nbundle = joblib.load('model.joblib')  # trusted artifact only\n"
        "with open('one-row.csv', encoding='utf-8-sig', newline='') as handle:\n"
        "    reader = csv.DictReader(handle)\n"
        "    headers = [name.strip() for name in (reader.fieldnames or [])]\n"
        "    if not headers or any(not name for name in headers) or len(set(headers)) != len(headers):\n"
        "        raise ValueError('CSV headers must be non-empty and unique')\n"
        "    reader.fieldnames = headers\n"
        "    rows = list(reader)\n"
        "    if len(rows) != 1 or None in rows[0] or any(value is None for value in rows[0].values()):\n"
        "        raise ValueError('Provide exactly one complete CSV row')\n"
        "    row = rows[0]\n"
        "missing = [name for name in bundle['feature_columns'] if name not in row]\n"
        "if missing:\n"
        "    raise ValueError('Missing required columns: ' + ', '.join(missing))\n"
        "numeric = set(bundle['numeric_columns'])\n"
        "X = [[normalize_tabular_value(row[name], name in numeric) for name in bundle['feature_columns']]]\n"
        "print(bundle['estimator'].predict(X)[0])\n"
    )
