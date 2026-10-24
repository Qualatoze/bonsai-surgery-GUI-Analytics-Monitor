"""PS1-equivalent spill guard.

Background QThread that watches the running llama-server for two failure modes
that start-server.ps1 guards against:

  1. sysmem fallback — KV cache spilling to system RAM (sustained sysmem growth).
  2. foreign VRAM   — another process eating GPU memory, starving our server.

Emits `spilled(str)` on the main thread when a threshold is crossed so the GUI
can log / warn without blocking the watcher loop. The watcher never raises:
any per-poll failure is swallowed and the loop continues.
"""
from __future__ import annotations

import subprocess
import threading
import time

from PySide6.QtCore import QThread, Signal


class SpillGuard(QThread):
    """Watcher for sysmem fallback and foreign VRAM usage."""

    spilled = Signal(str)

    def __init__(self, controller=None, poll_s: float = 5.0) -> None:
        super().__init__()
        self._controller = controller
        self._poll_s = max(1.0, float(poll_s))
        self._stop = threading.Event()
        # Sustained sysmem growth (MiB) treated as "KV spilled to RAM".
        self.sysmem_threshold_mib = 2048
        # VRAM (MiB) attributed to processes other than our server.
        self.foreign_vram_threshold_mib = 512

    def start(self) -> None:
        if not self.isRunning():
            super().start()

    def stop(self) -> None:
        self._stop.set()
        if self.isRunning():
            self.wait(3000)

    def _read_counters(self):
        """Return (sysmem_used_mib, foreign_vram_mib). Either may be None."""
        sysmem_used_mib = None
        try:
            import psutil
            vm = psutil.virtual_memory()
            sysmem_used_mib = int(vm.used / (1024 * 1024))
        except Exception:
            pass

        foreign_vram_mib = self._read_foreign_vram()
        return sysmem_used_mib, foreign_vram_mib

    def _read_foreign_vram(self):
        """Estimate VRAM held by processes other than our llama-server.

        Parses `nvidia-smi --query-gpu=pid,memory.used` per process when
        available; falls back to 0 (no detection) on any failure so the watcher
        never dies.
        """
        try:
            own_pid = None
            if self._controller is not None:
                info = getattr(self._controller.mgr, "current", lambda: None)()
                if info is not None:
                    own_pid = info.pid

            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=pid,memory.used",
                 "--format=csv,noheader,nounits"],
                capture_output=True, timeout=5, text=True,
            ).stdout
            total_foreign = 0
            for line in out.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2:
                    continue
                try:
                    pid = int(parts[0])
                    mem = int(parts[1])
                except (ValueError, IndexError):
                    continue
                if own_pid is not None and pid == own_pid:
                    continue
                total_foreign += mem
            return total_foreign
        except Exception:
            return 0

    def run(self) -> None:
        last_sysmem = None
        while not self._stop.is_set():
            try:
                sysmem, foreign = self._read_counters()
                if sysmem is not None and last_sysmem is not None:
                    delta = sysmem - last_sysmem
                    if delta > self.sysmem_threshold_mib:
                        self.spilled.emit(
                            f"sysmem fallback: +{delta} MiB in {self._poll_s:.0f}s "
                            f"(KV likely spilled to RAM)")
                if foreign and foreign > self.foreign_vram_threshold_mib:
                    self.spilled.emit(
                        f"foreign VRAM: ~{foreign} MiB held by other processes")
                last_sysmem = sysmem
            except Exception:
                # Keep the watcher alive on transient errors.
                pass
            time.sleep(self._poll_s)
