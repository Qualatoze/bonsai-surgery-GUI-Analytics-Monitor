"""PS1-equivalent Bonsai layer proxy.

Wraps the bonsai-layer Python script as a child process. The layer sits in front
of llama-server: it listens on an inner port (BONSAI_INNER_PORT) and forwards to
the server's public port, providing slot caching / saved conversations. When
layer_enabled is False (or the script is missing) the manager is a no-op and the
server runs directly.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path


class LayerManager:
    """Starts/stops the Bonsai layer proxy subprocess."""

    def __init__(self, controller=None) -> None:
        self._controller = controller
        self._proc: "subprocess.Popen | None" = None
        self._inner_port: int = 0
        self._public_port: int = 8080
        self._avail: bool | None = None

    def is_available(self) -> bool:
        """Check if Bonsai layer proxy can run (script + deps). Cached."""
        if self._avail is not None:
            return self._avail

        cfg = getattr(self._controller, "cfg", None)
        if cfg is None or not getattr(cfg, "layer_enabled", False):
            self._avail = False
            return False

        layer_script = Path(cfg.project_root) / "bonsai surgery" / "layer" / "bonsai_layer.py"
        if not layer_script.exists():
            self._avail = False
            return False

        try:
            r = subprocess.run(
                [sys.executable, "-c", "import wasmtime"],
                capture_output=True, timeout=5, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self._avail = (r.returncode == 0)
        except Exception:
            self._avail = False

        return self._avail
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Start the layer proxy if enabled and the script exists."""
        if self.running:
            return
        cfg = getattr(self._controller, "cfg", None)
        if cfg is None or not getattr(cfg, "layer_enabled", False):
            return

        inner = int(getattr(cfg, "layer_inner_port", 0)) or (int(cfg.port) + 10000)
        public = int(cfg.port)
        layer_script = Path(cfg.project_root) / "bonsai surgery" / "layer" / "bonsai_layer.py"
        if not layer_script.exists():
            return  # no layer available -> run server directly

        env = dict(os.environ)
        env["BONSAI_INNER_PORT"] = str(inner)
        env["BONSAI_PUBLIC_PORT"] = str(public)
        self._inner_port, self._public_port = inner, public
        try:
            self._proc = subprocess.Popen(
                [sys.executable, str(layer_script)],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            )
        except Exception:
            self._proc = None

    def stop(self) -> None:
        """Stop the layer proxy (best-effort)."""
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                with contextlib.suppress(Exception):
                    self._proc.kill()
            self._proc = None
