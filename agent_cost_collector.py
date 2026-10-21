"""Фоновый сборщик стоимости работы AI-агента (llama-server /metrics)."""
from __future__ import annotations

import csv
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from data_loader import compute_cost_totals
from stats_store import StatsStore

logger = logging.getLogger("bonsai.agent_cost_collector")


class AgentCostCollector(QThread):
    """Опрашивает /metrics раз в POLL_INTERVAL_S, считает стоимость,
    пишет в SQLite (таблица agent_usage) и в artifacts/agent_usage.csv.

    Запускается один раз в AppController; в Performance Mode продолжает
    работать (GUI лишь скрыт). Полностью изолирован от UI-потока.
    """
    sample_ready = Signal(dict)

    POLL_INTERVAL_S = 30.0      # задержка, чтобы не грузить систему
    REQUEST_TIMEOUT_S = 3.0

    def __init__(self, cfg, mgr, store: StatsStore, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.mgr = mgr
        self.store = store
        self._stopping = False
        self._baseline_set = False
        self._last = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
        self._csv_path = Path(cfg.data_path).parent / "agent_usage.csv"
        self._csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._csv_initialized = (
            self._csv_path.exists() and self._csv_path.stat().st_size > 0
        )

    def stop(self) -> None:
        self._stopping = True
        self.wait(5000)

    # ------------------------------------------------------------------
    def _read_api_key(self) -> str:
        p = Path(self.cfg.api_key_path)
        if not p.exists():
            return ""
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _fetch_metrics(self) -> dict | None:
        info = self.mgr.current()
        if info is None:
            return None
        url = f"http://{self.cfg.host}:{self.cfg.port}/metrics"
        req = urllib.request.Request(url)
        api_key = self._read_api_key()
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT_S) as r:
                if r.status != 200:
                    return None
                body = r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError):
            return None

        counters: dict[str, float] = {}
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) != 2:
                continue
            try:
                counters[parts[0].strip()] = float(parts[1].strip())
            except ValueError:
                continue

        # Разные версии llama.cpp — разные имена. Пробуем несколько.
        prompt = (
            counters.get("llamacpp:prompt_tokens_total")
            or counters.get("llamacpp:tokens_evaluated_total")
            or 0
        )
        completion = counters.get("llamacpp:tokens_predicted_total", 0)
        cached = counters.get("llamacpp:prompt_tokens_cached_total", 0)

        return {
            "prompt_tokens": int(prompt),
            "completion_tokens": int(completion),
            "cached_tokens": int(cached),
        }

    # ------------------------------------------------------------------
    def _compute_cost(self, deltas: dict) -> float:
        pi = float(getattr(self.cfg, "price_input_per_1m", 0.0))
        po = float(getattr(self.cfg, "price_output_per_1m", 0.0))
        pc = float(getattr(self.cfg, "price_cached_input_per_1m", 0.0))
        if pi == 0 and po == 0 and pc == 0:
            return 0.0
        # FIX P0-cost: disjoint llama.cpp counters — sum both parts, no clamp.
        totals = compute_cost_totals(
            deltas["prompt_tokens"], deltas["completion_tokens"],
            deltas["cached_tokens"], pi, po, pc)
        return sum(totals.values())

    def _append_csv(self, sample: dict) -> None:
        try:
            with open(self._csv_path, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                if not self._csv_initialized:
                    w.writerow([
                        "timestamp", "model_name",
                        "prompt_tokens", "completion_tokens", "cached_tokens",
                        "cost",
                    ])
                    self._csv_initialized = True
                w.writerow([
                    sample["ts"], sample.get("model", ""),
                    sample["prompt_tokens"], sample["completion_tokens"],
                    sample["cached_tokens"], f"{sample['cost']:.6f}",
                ])
        except OSError:
            pass

    # ------------------------------------------------------------------
    def run(self) -> None:
        # FIX: establish baseline on first successful read to avoid billing entire history.
        # If the server was already running before GUI started, we must NOT bill
        # all accumulated tokens as if they were generated during our session.
        while not self._stopping and not self._baseline_set:
            baseline = self._fetch_metrics()
            if baseline:
                self._last = baseline
                self._baseline_set = True
                break
            time.sleep(1)
        
        while not self._stopping:
            # Прерываемый sleep
            for _ in range(int(self.POLL_INTERVAL_S * 10)):
                if self._stopping:
                    break
                self.msleep(100)
            if self._stopping:
                break

            current = self._fetch_metrics()
            if current is None:
                continue

            # Рестарт сервера — счётчики обнулились, пропускаем дельту
            if (current["prompt_tokens"] < self._last["prompt_tokens"]
                    or current["completion_tokens"] < self._last["completion_tokens"]):
                self._last = current
                continue

            deltas = {
                "prompt_tokens": current["prompt_tokens"] - self._last["prompt_tokens"],
                "completion_tokens": current["completion_tokens"] - self._last["completion_tokens"],
                "cached_tokens": max(current["cached_tokens"] - self._last["cached_tokens"], 0),
            }
            self._last = current
            if not any(deltas.values()):
                continue

            info = self.mgr.current()
            model = info.model_name if info else ""
            sample = {
                "ts": time.time(),
                "prompt_tokens": deltas["prompt_tokens"],
                "completion_tokens": deltas["completion_tokens"],
                "cached_tokens": deltas["cached_tokens"],
                "cost": self._compute_cost(deltas),
                "model": model,
            }

            try:
                self.store.insert_agent_sample(sample)
            except Exception:
                logger.exception("insert_agent_sample failed")
            self._append_csv(sample)
            self.sample_ready.emit(sample)
