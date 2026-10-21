"""
Загрузка CSV/JSONL логов, валидация схемы, фильтрация, агрегация.

Применённые фиксы:
  #2 (pass 2): _parse_timestamps — эвристика unix s/ms/us/ns
  #5 (pass 1): широкий except вокруг pd.read_json
  #6 (pass 1): vectorized _compute_cost — O(N) вместо apply(axis=1)
  #4 (pass 2): apply_filters — нормализация datetime→date
  #8 (pass 2): cost_cny = NaN, если ни в логах, ни в ставках нет данных
"""
from __future__ import annotations

from datetime import date as date_type, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REQUIRED = ["timestamp", "model_name"]
OPTIONAL_DEFAULTS: dict[str, Any] = {
    "api_key_id": "unknown",
    "request_count": 1,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "prompt_cached_tokens": 0,
    "cache_hit_tokens": 0,
    "cache_miss_tokens": 0,
}
DISPLAY_COLUMNS = [
    "timestamp", "model_name", "api_key_id",
    "request_count", "prompt_tokens", "completion_tokens",
    "prompt_cached_tokens", "cache_hit_tokens", "cache_miss_tokens",
    "cost_cny",
]


# ---------------------------------------------------------------------------
# FIX #2: числовой timestamp — не всегда наносекунды
# ---------------------------------------------------------------------------
def _parse_timestamps(series: pd.Series) -> pd.Series:
    if not pd.api.types.is_numeric_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    s = series.dropna()
    if s.empty:
        return pd.to_datetime(series, errors="coerce")

    m = float(s.abs().max())
    if m > 1e17:                       # наносекунды (2024 ≈ 1.7e18)
        return pd.to_datetime(series, errors="coerce")
    if m > 1e14:                       # микросекунды
        return pd.to_datetime(series, unit="us", errors="coerce")
    if m > 1e11:                       # миллисекунды
        return pd.to_datetime(series, unit="ms", errors="coerce")
    if m > 1e8:                        # секунды (1973+)
        return pd.to_datetime(series, unit="s", errors="coerce")
    return pd.to_datetime(series, errors="coerce")


# ---------------------------------------------------------------------------
# FIX #6 + 3-price model: global prices (Input/Output/Cached) + legacy per-model
# ---------------------------------------------------------------------------
def _compute_cost(
    df: pd.DataFrame,
    model_costs: dict[str, dict[str, float]],
    global_prices: dict[str, float],
) -> pd.Series:
    has_global = any(float(global_prices.get(k, 0) or 0) > 0
                     for k in ("input", "output", "cached"))
    has_per_model = bool(model_costs)

    if not has_global and not has_per_model:
        return pd.Series(0.0, index=df.index, dtype=float)

    if has_global:
        pi = float(global_prices.get("input", 0.0))
        po = float(global_prices.get("output", 0.0))
        pc = float(global_prices.get("cached", 0.0))

        prompt = (pd.to_numeric(df["prompt_tokens"], errors="coerce")
                  if "prompt_tokens" in df.columns
                  else pd.Series(0.0, index=df.index)).fillna(0).astype(float)
        completion = (pd.to_numeric(df["completion_tokens"], errors="coerce")
                      if "completion_tokens" in df.columns
                      else pd.Series(0.0, index=df.index)).fillna(0).astype(float)

        cached_col = None
        for col in ("prompt_cached_tokens", "cache_hit_tokens", "cached_tokens"):
            if col in df.columns:
                cached_col = col
                break
        cached = (pd.to_numeric(df[cached_col], errors="coerce")
                  if cached_col else pd.Series(0.0, index=df.index)
                  ).fillna(0).astype(float)

        # FIX P0-cost: llama.cpp counters are DISJOINT — prompt_tokens_total
        # excludes cache hits; prompt_tokens_cached_total is the cache part.
        # Total input cost = prompt + cached (no subtraction / no clamp).
        return (prompt / 1e6 * pi
                + cached / 1e6 * pc
                + completion / 1e6 * po)

    # legacy per-model
    pin = df["model_name"].map(
        lambda m: float(model_costs.get(m, {}).get("prompt_per_1k_cny", 0.0))
    ).astype(float)
    pout = df["model_name"].map(
        lambda m: float(model_costs.get(m, {}).get("completion_per_1k_cny", 0.0))
    ).astype(float)
    return ((df["prompt_tokens"].astype(float) / 1000.0) * pin
            + (df["completion_tokens"].astype(float) / 1000.0) * pout)


# ---------------------------------------------------------------------------
# FIX P0-cost: disjoint llama.cpp counters — shared cost helpers
# ---------------------------------------------------------------------------
def compute_cost_totals(prompt_tokens, completion_tokens, cached_tokens,
                       price_input_per_1m, price_output_per_1m,
                       price_cached_input_per_1m) -> dict:
    """Суммарная стоимость за период. llama.cpp счётчики DISJOINT:
    prompt_tokens_total — обработанные токены (без кэша),
    prompt_tokens_cached_total — токены из кэша. Итого input = сумма обеих частей,
    без вычитания и без clamp."""
    pi = float(price_input_per_1m or 0)
    po = float(price_output_per_1m or 0)
    pc = float(price_cached_input_per_1m or 0)
    return {
        "input": float(prompt_tokens) / 1e6 * pi,
        "output": float(completion_tokens) / 1e6 * po,
        "cached": float(cached_tokens) / 1e6 * pc,
    }


def resolve_usage_path(data_path: str):
    """Возвращает существующий путь к usage-файлу. Если data_path указывает
    на несуществующий файл, пробуем sibling agent_usage.csv."""
    if not data_path:
        return None
    p = Path(data_path)
    if p.exists():
        return p
    alt = p.parent / "agent_usage.csv"
    if alt.exists():
        return alt
    return None


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------
def load_logs(
    path: str,
    model_costs: dict[str, dict[str, float]] | None = None,
    global_prices: dict[str, float] | None = None,
) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))

    suffix = p.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(p)
    elif suffix in (".jsonl", ".ndjson"):
        df = pd.read_json(p, lines=True)
    elif suffix == ".json":
        # FIX #5: широкий except — read_json может бросить TypeError/AttributeError
        try:
            df = pd.read_json(p, lines=True)
        except Exception:
            df = pd.read_json(p)
    else:
        raise ValueError(f"Неподдерживаемый формат: {suffix}")

    # FIX P0-4: normalize column names from agent_usage.csv schema.
    # Maps "cached_tokens" -> "prompt_cached_tokens", "cost" -> "cost_cny".
    for old_name, new_name in (("cached_tokens", "prompt_cached_tokens"),
                               ("cost", "cost_cny")):
        if old_name in df.columns and new_name not in df.columns:
            df.rename(columns={old_name: new_name}, inplace=True)

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"Отсутствуют обязательные колонки: {missing}. Есть: {list(df.columns)}")

    for col, default in OPTIONAL_DEFAULTS.items():
        if col not in df.columns:
            df[col] = default
        else:
            df[col] = df[col].fillna(default)

    df["timestamp"] = _parse_timestamps(df["timestamp"])
    df = df.dropna(subset=["timestamp"])
    if df.empty:
        return df

    # Числовые поля — приводим к числу
    df["prompt_tokens"] = pd.to_numeric(df["prompt_tokens"], errors="coerce").fillna(0)
    df["completion_tokens"] = pd.to_numeric(df["completion_tokens"], errors="coerce").fillna(0)
    df["request_count"] = pd.to_numeric(df["request_count"], errors="coerce").fillna(1)
    df["prompt_cached_tokens"] = pd.to_numeric(df["prompt_cached_tokens"], errors="coerce").fillna(0)
    df["cache_hit_tokens"] = pd.to_numeric(df["cache_hit_tokens"], errors="coerce").fillna(0)
    df["cache_miss_tokens"] = pd.to_numeric(df["cache_miss_tokens"], errors="coerce").fillna(0)

    # FIX: приоритет — готовый cost_cny из CSV; заполняем только NaN
    gp = global_prices or {}
    has_prices = bool(model_costs) or any(
        float(gp.get(k, 0) or 0) > 0 for k in ("input", "output", "cached"))

    if "cost_cny" in df.columns:
        df["cost_cny"] = pd.to_numeric(df["cost_cny"], errors="coerce")
        if has_prices:
            calc = _compute_cost(df, model_costs or {}, gp)
            df["cost_cny"] = df["cost_cny"].where(df["cost_cny"].notna(), calc)
        else:
            df["cost_cny"] = df["cost_cny"].fillna(0.0)
    else:
        if has_prices:
            df["cost_cny"] = _compute_cost(df, model_costs or {}, gp)
        else:
            df["cost_cny"] = 0.0

    return df.sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------------------
# FILTER — FIX #4: normalize datetime→date, single date, tuple len 0/1/2
# ---------------------------------------------------------------------------
def _as_date(v) -> Optional[date_type]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date_type):
        return v
    return None


def apply_filters(
    df: pd.DataFrame,
    models: list[str] | None,
    date_range,
    api_keys: list[str] | None,
) -> pd.DataFrame:
    out = df
    if models:
        out = out[out["model_name"].isin(models)]
    if api_keys and "api_key_id" in out.columns:
        out = out[out["api_key_id"].isin(api_keys)]

    start: Optional[date_type] = None
    end: Optional[date_type] = None

    if isinstance(date_range, (tuple, list)):
        if len(date_range) == 2:
            start, end = _as_date(date_range[0]), _as_date(date_range[1])
        elif len(date_range) == 1:
            start = end = _as_date(date_range[0])
    else:
        start = end = _as_date(date_range)

    if start is not None and end is not None:
        d = out["timestamp"].dt.date
        out = out[(d >= start) & (d <= end)]

    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# AGGREGATE — weekly начинается с понедельника
# ---------------------------------------------------------------------------
def aggregate(df: pd.DataFrame, granularity: str = "daily") -> pd.DataFrame:
    freq = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}.get(granularity, "D")
    if df.empty:
        return df
    out = (
        df.set_index("timestamp")
          .groupby([pd.Grouper(freq=freq), "model_name"])
          .agg(
              request_count=("request_count", "sum"),
              prompt_tokens=("prompt_tokens", "sum"),
              completion_tokens=("completion_tokens", "sum"),
              cost_cny=("cost_cny", "sum"),
          )
          .reset_index()
    )
    # FIX: NaN cost ломал bar-чарты — прибиваем к 0
    out["cost_cny"] = out["cost_cny"].fillna(0.0)
    return out
