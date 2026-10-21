"""Фоновный QThread-коллектор метрик ресурсов с буферизацией."""
from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import QThread, Signal

from resource_monitor import ProcessMetrics, query_gpu_snapshot
from stats_store import StatsStore


class StatsCollector(QThread):
    sample_ready = Signal(dict)

    # Flush interval in seconds — reduced from 60 to 15 for faster chart updates
    FLUSH_INTERVAL_S = 15.0
    # Max buffer size before forced flush (safety net, ~3 min at 2s interval)
    MAX_BUFFER_SIZE = 180

    def __init__(self, mgr, store: StatsStore, pm: ProcessMetrics,
                 interval_s: int = 2, small_gpu_mib: int = 8704):
        super().__init__()
        self.mgr = mgr
        self.store = store
        self.pm = pm
        self.interval = max(1, int(interval_s))
        self.small_gpu_mib = small_gpu_mib
        self._stopping = False
        self._last_gpu_poll = 0.0
        self._buffer: deque[dict] = deque()
        self._last_flush = time.time()

    def set_interval(self, seconds: int) -> None:
        self.interval = max(1, int(seconds))

    def stop(self) -> None:
        self._stopping = True
        self.wait(5000)

    def _flush_buffer(self) -> None:
        """Flush all buffered samples to SQLite in a single batch transaction."""
        if not self._buffer:
            return
        try:
            self.store.batch_insert_samples(list(self._buffer))
        except Exception:
            # On flush failure, fall back to individual inserts to avoid data loss
            for sample in list(self._buffer):
                try:
                    self.store.insert_sample(sample)
                except Exception:
                    pass
        self._buffer.clear()
        self._last_flush = time.time()

    def run(self) -> None:
        while not self._stopping:
            try:
                info = self.mgr.current()
                if info:
                    metrics = self.pm.get(info.pid)
                    if metrics:
                        vram = None
                        gpu_total = None
                        now = time.time()
                        if now - self._last_gpu_poll > 10.0:
                            snap = query_gpu_snapshot(self.small_gpu_mib)
                            vram = snap["procs"].get(info.pid)
                            if vram is None:
                                from resource_monitor import query_process_vram_nvml
                                vram = query_process_vram_nvml(info.pid)
                            if vram is None:
                                from resource_monitor import query_process_vram_wmi
                                vram = query_process_vram_wmi(info.pid)
                            if snap["gpus"]:
                                gpu_total = snap["gpus"][0].total_mib
                            self._last_gpu_poll = now

                        sample = {
                            "ts": now,
                            "pid": info.pid,
                            "cpu_pct": metrics["cpu_pct"],
                            "rss_mb": metrics["rss_mb"],
                            "vms_mb": metrics["vms_mb"],
                            "pagefile_mb": metrics["pagefile_mb"],
                            "vram_mib": vram,
                            "gpu_total_mib": gpu_total,
                            "status": metrics["status"],
                        }

                        # Buffer for batch DB write (every 60s)
                        self._buffer.append(sample)

                        # Live display — emit every sample unchanged
                        self.sample_ready.emit(sample)

                # Periodic flush: once per FLUSH_INTERVAL_S or when buffer is full
                now = time.time()
                if now - self._last_flush >= self.FLUSH_INTERVAL_S or len(self._buffer) >= self.MAX_BUFFER_SIZE:
                    self._flush_buffer()

                # FIX 2a: прерываемый sleep вместо msleep(interval*1000)
                for _ in range(self.interval * 20):
                    if self._stopping:
                        break
                    self.msleep(50)
            except Exception:
                for _ in range(10):
                    if self._stopping:
                        break
                    self.msleep(100)

        # Final flush on shutdown to avoid losing buffered samples
        self._flush_buffer()
