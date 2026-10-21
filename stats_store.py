"""SQLite WAL-хранилище для метрик и событий."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pandas as pd


class StatsStore:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS resource_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        pid INTEGER,
        cpu_pct REAL,
        rss_mb REAL,
        vms_mb REAL,
        pagefile_mb REAL,
        vram_mib INTEGER,
        gpu_total_mib INTEGER,
        status TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_samples_ts ON resource_samples(ts);
    CREATE INDEX IF NOT EXISTS idx_samples_pid_ts ON resource_samples(pid, ts);

    CREATE TABLE IF NOT EXISTS server_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        event TEXT NOT NULL,
        pid INTEGER,
        model_name TEXT,
        ctx INTEGER,
        kv_type TEXT,
        details TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_events_ts ON server_events(ts);

    CREATE TABLE IF NOT EXISTS settings_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        config_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_settings_ts ON settings_history(ts);

    CREATE TABLE IF NOT EXISTS agent_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        cached_tokens INTEGER DEFAULT 0,
        cost REAL DEFAULT 0,
        model TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_agent_ts ON agent_usage(ts);
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(self.SCHEMA)
            c.commit()

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=10.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                yield conn
            finally:
                conn.close()

    # --- writes ---
    def insert_sample(self, sample: dict) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO resource_samples
                (ts, pid, cpu_pct, rss_mb, vms_mb, pagefile_mb,
                 vram_mib, gpu_total_mib, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sample.get("ts", time.time()), sample.get("pid"),
                 sample.get("cpu_pct"), sample.get("rss_mb"),
                 sample.get("vms_mb"), sample.get("pagefile_mb"),
                 sample.get("vram_mib"), sample.get("gpu_total_mib"),
                 sample.get("status")),
            )
            c.commit()

    def batch_insert_samples(self, samples: list[dict]) -> None:
        """Batch-insert many samples in a single transaction (executemany)."""
        if not samples:
            return
        with self._conn() as c:
            c.executemany(
                """INSERT INTO resource_samples
                (ts, pid, cpu_pct, rss_mb, vms_mb, pagefile_mb,
                 vram_mib, gpu_total_mib, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (s.get("ts", time.time()), s.get("pid"),
                     s.get("cpu_pct"), s.get("rss_mb"),
                     s.get("vms_mb"), s.get("pagefile_mb"),
                     s.get("vram_mib"), s.get("gpu_total_mib"),
                     s.get("status"))
                    for s in samples
                ],
            )
            c.commit()

    def insert_event(self, event: str, pid: Optional[int] = None,
                     model_name: str = "", ctx: int = 0, kv_type: str = "",
                     details: str = "") -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO server_events
                (ts, event, pid, model_name, ctx, kv_type, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), event, pid, model_name, ctx, kv_type, details),
            )
            c.commit()

    def batch_insert_events(self, events: list[dict]) -> None:
        """Batch-insert many server events in a single transaction (executemany).

        FIX #9 (Phase B): eliminates the N+1 pattern where each insert_event()
        opened its own connection and committed. Pass a list of dicts with keys
        (event, pid, model_name, ctx, kv_type, details); ts defaults to now.
        """
        if not events:
            return
        rows = [
            (e.get("ts", time.time()), e["event"], e.get("pid"),
             e.get("model_name", ""), e.get("ctx", 0),
             e.get("kv_type", ""), e.get("details", ""))
            for e in events
        ]
        with self._conn() as c:
            c.executemany(
                """INSERT INTO server_events
                (ts, event, pid, model_name, ctx, kv_type, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            c.commit()

    def insert_settings(self, config_json: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO settings_history (ts, config_json) VALUES (?, ?)",
                (time.time(), config_json),
            )
            c.commit()

    # --- reads ---
    def get_samples(self, from_ts: float, to_ts: float,
                    pid: Optional[int] = None, limit: int = 50000) -> pd.DataFrame:
        q = "SELECT * FROM resource_samples WHERE ts >= ? AND ts <= ?"
        params: list = [from_ts, to_ts]
        if pid is not None:
            q += " AND pid = ?"
            params.append(pid)
        q += " ORDER BY ts ASC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            return pd.read_sql_query(q, c, params=params)

    def get_events(self, from_ts: float, to_ts: float,
                   limit: int = 5000) -> pd.DataFrame:
        with self._conn() as c:
            return pd.read_sql_query(
                "SELECT * FROM server_events WHERE ts >= ? AND ts <= ? "
                "ORDER BY ts ASC LIMIT ?",
                c, params=[from_ts, to_ts, limit],
            )

    def get_latest_settings(self) -> Optional[str]:
        with self._conn() as c:
            row = c.execute(
                "SELECT config_json FROM settings_history ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None

    def cleanup_older_than(self, days: int) -> int:
        cutoff = time.time() - days * 86400
        with self._conn() as c:
            n = c.execute(
                "DELETE FROM resource_samples WHERE ts < ?", (cutoff,),).rowcount
            n += c.execute(
                "DELETE FROM server_events WHERE ts < ?", (cutoff,),).rowcount
            # FIX P0-cost: agent_usage is an accounting ledger, NOT telemetry.
            # Never purge it — cost history must survive cleanup.
            c.commit()
            return n

    # --- agent usage ---
    def insert_agent_sample(self, sample: dict) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO agent_usage
                (ts, prompt_tokens, completion_tokens, cached_tokens, cost, model)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (sample.get("ts", time.time()),
                 int(sample.get("prompt_tokens", 0)),
                 int(sample.get("completion_tokens", 0)),
                 int(sample.get("cached_tokens", 0)),
                 float(sample.get("cost", 0.0)),
                 sample.get("model", "")),
            )
            c.commit()

    def get_agent_totals(self, from_ts: float, to_ts: float) -> dict:
        """Суммы токенов агента за период (для пересчёта с актуальными ценами)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(prompt_tokens),0), "
                "       COALESCE(SUM(completion_tokens),0), "
                "       COALESCE(SUM(cached_tokens),0) "
                "FROM agent_usage WHERE ts >= ? AND ts <= ?",
                (from_ts, to_ts),
            ).fetchone()
        return {
            "prompt_tokens": int(row[0]) if row else 0,
            "completion_tokens": int(row[1]) if row else 0,
            "cached_tokens": int(row[2]) if row else 0,
        }

    def get_agent_usage_df(self) -> pd.DataFrame:
        """FIX P0-3: возвращает все строки agent_usage как DataFrame.

        Колонки: ts (float), prompt_tokens, completion_tokens, cached_tokens, cost, model.
        Используется AnalyticsTab.reload() как основной источник данных вместо CSV.
        """
        with self._conn() as c:
            return pd.read_sql_query(
                "SELECT ts, prompt_tokens, completion_tokens, "
                "cached_tokens, cost, model FROM agent_usage ORDER BY ts ASC",
                c,
            )
