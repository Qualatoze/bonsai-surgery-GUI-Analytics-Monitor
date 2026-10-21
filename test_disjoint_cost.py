"""Тесты нового расчёта стоимости (disjoint-счётчики llama.cpp).

llamacpp:prompt_tokens_total — только обработанные токены (без кэша),
llamacpp:prompt_tokens_cached_total — только из кэша. Счётчики disjoint,
поэтому стоимость = сумма обеих частей, без вычитания/клампинга.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


# ---------------------------------------------------------------------------
# 1. compute_cost_totals — disjoint-семантика
# ---------------------------------------------------------------------------
from data_loader import (compute_cost_totals, load_logs, resolve_usage_path)

print("\n[TEST 1] compute_cost_totals")
c = compute_cost_totals(3941, 1158, 42240, 0.2, 2.5, 0.05)
check("input = prompt/1M*pi (no subtraction)",
      abs(c["input"] - 3941 / 1e6 * 0.2) < 1e-12, f"got {c['input']}")
check("output = completion/1M*po",
      abs(c["output"] - 1158 / 1e6 * 2.5) < 1e-12, f"got {c['output']}")
check("cached = cached/1M*pc (even when cached > prompt)",
      abs(c["cached"] - 42240 / 1e6 * 0.05) < 1e-12, f"got {c['cached']}")
check("zero prices -> zero costs",
      sum(compute_cost_totals(1_000_000, 1_000_000, 1_000_000, 0, 0, 0).values()) == 0.0)


# ---------------------------------------------------------------------------
# 2. data_loader._compute_cost — CSV-путь с cached > prompt
# ---------------------------------------------------------------------------
print("\n[TEST 2] load_logs with disjoint counters (cached > prompt)")
import csv

tmp_csv = Path(tempfile.mkdtemp()) / "agent_usage.csv"
with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["timestamp", "model_name", "prompt_tokens",
                "completion_tokens", "cached_tokens", "cost"])
    # cached > prompt — типично для agent-сессий с длинным системным промптом
    w.writerow([str(1792580000), "test-model", "3941", "1158", "42240", ""])

loaded = load_logs(str(tmp_csv), None, {"input": 0.2, "output": 2.5, "cached": 0.05})
expected = 3941 / 1e6 * 0.2 + 42240 / 1e6 * 0.05 + 1158 / 1e6 * 2.5
check("cost_cny == prompt+cached+output (no clamp)",
      abs(float(loaded["cost_cny"].iloc[0]) - expected) < 1e-9,
      f"got {float(loaded['cost_cny'].iloc[0]):.6f}, expected {expected:.6f}")


# ---------------------------------------------------------------------------
# 3. resolve_usage_path — fallback на agent_usage.csv
# ---------------------------------------------------------------------------
print("\n[TEST 3] resolve_usage_path")
tmp = Path(tempfile.mkdtemp()) / "artifacts"
tmp.mkdir(parents=True, exist_ok=True)

(tmp / "usage.csv").write_text("x\n")
check("existing usage.csv returned",
      str(resolve_usage_path(str(tmp / "usage.csv"))) == str(tmp / "usage.csv"))

(tmp / "usage.csv").unlink()
(tmp / "agent_usage.csv").write_text("y\n")
check("fallback to agent_usage.csv when usage.csv missing",
      str(resolve_usage_path(str(tmp / "usage.csv"))) == str(tmp / "agent_usage.csv"))

(tmp / "agent_usage.csv").unlink()
check("no file -> None", resolve_usage_path(str(tmp / "usage.csv")) is None)
check("empty data_path -> None", resolve_usage_path("") is None)


# ---------------------------------------------------------------------------
# 4. cleanup_older_than не трогает agent_usage
# ---------------------------------------------------------------------------
print("\n[TEST 4] cleanup_older_than keeps agent_usage history")
from stats_store import StatsStore

tmp_db = Path(tempfile.mkdtemp()) / "test.db"
store = StatsStore(tmp_db)
import time as _time
now = _time.time()
# старая строка agent_usage (старее cutoff на 2 года) + свежая resource_sample
store.insert_agent_sample({"ts": now - 730 * 86400, "prompt_tokens": 100,
                           "completion_tokens": 50, "cached_tokens": 90,
                           "cost": 0.01, "model": "old-model"})
store.insert_sample({"ts": now - 730 * 86400, "pid": 1234, "cpu_pct": 1.0,
                     "rss_mb": 100.0, "vms_mb": 200.0, "pagefile_mb": 50.0,
                     "vram_mib": None, "gpu_total_mib": None, "status": "ok"})

store.cleanup_older_than(30)

df = store.get_agent_usage_df()
check("old agent_usage row survives cleanup", len(df) == 1, f"got {len(df)}")
samples = store.get_samples(now - 730 * 86400, now)
check("old resource_sample deleted", samples.empty, f"got {len(samples)} rows")


# ---------------------------------------------------------------------------
# 5. AgentCostCollector._compute_cost — та же disjoint-формула
# ---------------------------------------------------------------------------
print("\n[TEST 5] AgentCostCollector._compute_cost")
from agent_cost_collector import AgentCostCollector

class _FakeCfg:
    price_input_per_1m = 0.2
    price_output_per_1m = 2.5
    price_cached_input_per_1m = 0.05


class _FakeSelf:
    cfg = _FakeCfg()


cost = AgentCostCollector._compute_cost(_FakeSelf(), {"prompt_tokens": 3941,
                                                      "completion_tokens": 1158,
                                                      "cached_tokens": 42240})
check("collector cost == disjoint sum",
      abs(cost - (3941 / 1e6 * 0.2 + 42240 / 1e6 * 0.05 + 1158 / 1e6 * 2.5)) < 1e-9,
      f"got {cost}")

print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} tests PASSED")
if failed > 0:
    print(f"FAILED: {failed}")
    sys.exit(1)
else:
    print("ALL TESTS PASSED [OK]")
sys.exit(0)
