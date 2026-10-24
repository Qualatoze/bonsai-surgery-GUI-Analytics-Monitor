"""
Управление llama-server.exe: скан моделей, сборка аргументов, запуск/останов,
pidfile, кросс-процессный lock.

Применённые фиксы:
  #1 (pass 2): log_out/log_err как property — смена logs_dir в Tab 4 подхватывается
  #3 (pass 3): stop() на Windows — graceful CTRL_BREAK → taskkill /T /F (дерево!)
  #5 (pass 3): process_lock на POSIX — неблокирующий flock + deadline
  #6 (pass 2): start() ждёт до 1.5s и вызывает proc.wait() при раннем крахе
  #9 (pass 1): _reader_threads чистится при каждом start()

FIXES (Phase A, 2024-10):
  FIX-A1: print → logging (убирает PID-окно)
  FIX-A2: is_alive() — p.is_running() + create_time (убирает ложноположительный статус)
  FIX-A3: stop() Windows — без CTRL_BREAK, сразу taskkill /T /F с CREATE_NO_WINDOW
  FIX-A4: startupinfo — скрытие консоли дочернего процесса
  FIX-A5: wait_for_ready() — опрос /health до готовности
  FIX-A6: _build_env() — дефолты из cfg + критические env vars (.ps1)
  FIX-A7: build_args() — условные флаги + недостающие аргументы (-n, --reasoning-budget, --jinja)
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psutil

from config import AppConfig, internal_host
from resource_monitor import GpuInfo


_log = logging.getLogger("bonsai.server")


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------
@dataclass
class ModelInfo:
    path: Path
    name: str
    size_gb: float
    tags: list[str]
    is_mtp_model: bool = False
    mtp_path: Optional[Path] = None


_TAG_RE = re.compile(
    r"(PTQ\d+|PQ\d+|Q\d+_K_[MSL]|Q\d+_0|Q\d+_K|MTP|Uncensored|F16|F32)",
    re.IGNORECASE,
)


def scan_models(models_dir: str | Path, min_size_gb: float = 0.09) -> list[ModelInfo]:
    """Сканирует models/ на .gguf > min_size_gb, парсит теги, находит MTP-draft."""
    d = Path(models_dir)
    if not d.exists():
        return []

    models: list[ModelInfo] = []
    for p in sorted(d.glob("*.gguf")):
        try:
            size_gb = p.stat().st_size / (1024 ** 3)
        except OSError:
            continue
        if size_gb < min_size_gb:
            continue
        tags = sorted({m.group(1).upper() for m in _TAG_RE.finditer(p.stem)})
        is_mtp = "MTP" in tags or "-mtp-" in p.stem.lower() or "_mtp" in p.stem.lower()
        models.append(ModelInfo(p, p.stem, size_gb, tags, is_mtp_model=is_mtp))

    # Индекс MTP-draft по базовому имени
    mtp_by_base: dict[str, Path] = {}
    for m in models:
        if m.is_mtp_model:
            base = m.name.lower().replace("-mtp", "").replace("_mtp", "").strip("-_.")
            mtp_by_base[base] = m.path

    # Связываем base-модели с их MTP
    for m in models:
        if m.is_mtp_model:
            continue
        base = m.name.lower()
        if base in mtp_by_base:
            m.mtp_path = mtp_by_base[base]
            continue
        for k, v in mtp_by_base.items():
            if k and (k in base or base in k):
                m.mtp_path = v
                break

    # SM-1: priority sort — base (non-MTP) models first, then their MTP drafts;
    # within each group largest file first. Keeps the primary model above its
    # speculative-draft companion in the GUI combo.
    def _priority(m: ModelInfo) -> tuple[int, float]:
        return (0 if not m.is_mtp_model else 1, -m.size_gb)
    models.sort(key=_priority)
    return models


# ---------------------------------------------------------------------------
# Pidfile
# ---------------------------------------------------------------------------
@dataclass
class PidInfo:
    pid: int
    create_time: float
    started_at: float
    cmdline: list[str]
    model_name: str = ""
    alias: str = ""
    ctx_size: int = 0
    kv_type: str = ""


class PidStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read(self) -> Optional[PidInfo]:
        if not self.path.exists():
            return None
        try:
            return PidInfo(**json.loads(self.path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def write(self, info: PidInfo) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(info.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()

    @staticmethod
    def is_alive(info: Optional[PidInfo]) -> bool:
        """FIX-A2: p.is_running() + create_time — защита от зомби-процессов."""
        if info is None:
            return False
        try:
            p = psutil.Process(info.pid)
            # КРИТИЧЕСКИ ВАЖНО: is_running() == False для мёртвого процесса,
            # даже если Python держит Popen-handle через reader-потоки.
            if not p.is_running():
                return False
            return abs(p.create_time() - info.create_time) < 1.0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False


# ---------------------------------------------------------------------------
# Кросс-процессный lock
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def process_lock(lockfile_path: str | Path, timeout_s: float = 5.0):
    """
    FIX #5 (pass 3): на POSIX — LOCK_NB + deadline, а не блокирующий LOCK_EX.
    На Windows — msvcrt.locking(LK_NBLCK) с deadline (уже было корректно).
    """
    path = Path(lockfile_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    try:
        f.seek(0, 2)
        if f.tell() == 0:
            f.write(b"\0")
            f.flush()
        f.seek(0)

        deadline = time.monotonic() + timeout_s

        if sys.platform == "win32":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Lock timeout: {path}")
                    time.sleep(0.1)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Lock timeout: {path}")
                    time.sleep(0.1)

        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt
                f.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                with contextlib.suppress(OSError):
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


# ---------------------------------------------------------------------------
# RAM / VRAM планировщик
# ---------------------------------------------------------------------------
def compute_ram_budget(cfg: AppConfig) -> dict:
    vm = psutil.virtual_memory()
    total_gb = vm.total / (1024 ** 3)
    free_gb = vm.available / (1024 ** 3)
    if total_gb >= 48:
        prompt_cache_bytes, checkpoint_count = None, None      # дефолт llama-server
    elif total_gb >= 24:
        prompt_cache_bytes, checkpoint_count = 4 * 1024 ** 3, 32
    else:
        prompt_cache_bytes = int(free_gb * 0.5 * 1024 ** 3)
        checkpoint_count = 8
    return {
        "total_gb": total_gb,
        "free_gb": free_gb,
        "prompt_cache_bytes": prompt_cache_bytes,
        "checkpoint_count": checkpoint_count,
    }


def compute_kv_vram_cells(
    cfg: AppConfig, gpu: Optional[GpuInfo], kv_type: str = "q8_0",
    ctx_size: int = 0, model_size_gb: float = 0.0,
) -> Optional[int]:
    """
    Расчёт --kv-vram-cells на основе свободного VRAM после вычитания модели.

    Формула: (free_vram - margin - model - draft - overhead) / bytes_per_cell,
    capped at ctx_size. Если всё влезает — возвращаем 0 (сервер сам выберет all-VRAM).
    """
    if gpu is None:
        return None
    from presets import KV_BYTES_PER_TOKEN
    cell_bytes = KV_BYTES_PER_TOKEN.get(kv_type, 34816)

    # Вычитаем модель + draft head + overhead (CUDA context + рабочая память)
    model_mib = int(model_size_gb * 1024)
    draft_mib = 250 if kv_type == "q8_0" else 60   # ~Q8/Q4 draft head
    overhead_mib = 1024                              # CUDA context + working memory

    free_mib = max(gpu.free_mib - cfg.vram_margin_mib
                   - model_mib - draft_mib - overhead_mib, 0)
    if free_mib <= 0:
        return 0

    cells = (free_mib * 1024 * 1024) // cell_bytes
    # Cap: не больше контекста (иначе все KV в VRAM, tiered бессмыслен)
    if ctx_size > 0:
        cells = min(cells, ctx_size)

    # Если всё влезает — возвращаем 0, чтобы сервер сам выбрал all-VRAM режим
    # (без --kv-vram-cells). Иначе — возвращаем число, чтобы включить tiered.
    if ctx_size > 0 and cells >= ctx_size * 0.95:
        return 0

    return max(0, cells)


# ---------------------------------------------------------------------------
# ServerManager
# ---------------------------------------------------------------------------
class ServerManager:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.pid_store = PidStore(cfg.pidfile_path)
        self._stdout_buf: deque[str] = deque(maxlen=cfg.terminal_buffer_lines)
        self._stderr_buf: deque[str] = deque(maxlen=cfg.terminal_buffer_lines)
        self._reader_threads: list[threading.Thread] = []

    # FIX #1 (pass 2): пути логов резолвятся динамически из cfg.logs_dir
    @property
    def log_out(self) -> Path:
        return Path(self.cfg.logs_dir) / "llama-server.log"

    @property
    def log_err(self) -> Path:
        return Path(self.cfg.logs_dir) / "llama-server.err.log"

    # --- статус ---
    def current(self) -> Optional[PidInfo]:
        info = self.pid_store.read()
        if info and self.pid_store.is_alive(info):
            return info
        if info:
            self.pid_store.clear()
        return None

    def is_running(self) -> bool:
        return self.current() is not None

    # ------------------------------------------------------------------
    # START
    # ------------------------------------------------------------------
    def start(self, model: ModelInfo, opts: dict) -> PidInfo:
        with process_lock(self.cfg.lockfile_path):
            running = self.current()
            if running:
                raise RuntimeError(f"Сервер уже запущен (pid={running.pid})")

            exe = Path(self.cfg.llama_server_exe)
            _log.info("exe=%s exists=%s", exe, exe.exists())
            if not exe.exists():
                raise FileNotFoundError(f"llama-server.exe не найден: {exe}")

            self.cfg.ensure_dirs()
            self.log_out.write_bytes(b"")
            self.log_err.write_bytes(b"")
            self._stdout_buf.clear()
            self._stderr_buf.clear()

            args = self.build_args(model, opts)
            cmd = [str(exe), *args]
            _log.debug("cmd=%s", " ".join(cmd))

            env = self._build_env(opts)

            # FIX-A4: скрытие консоли дочернего процесса (Windows)
            creationflags = 0
            startupinfo = None
            if sys.platform == "win32":
                creationflags = (subprocess.CREATE_NEW_PROCESS_GROUP
                                 | subprocess.CREATE_NO_WINDOW)
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, env=env,
                creationflags=creationflags,
                startupinfo=startupinfo,
                text=False, bufsize=0,
            )
            _log.info("spawned pid=%s", proc.pid)

            # FIX #9 (pass 1): чистим завершённые reader-threads перед стартом новых
            self._reader_threads = [t for t in self._reader_threads if t.is_alive()]
            self._spawn_reader(proc.stdout, self._stdout_buf, self.log_out, "stdout")
            self._spawn_reader(proc.stderr, self._stderr_buf, self.log_err, "stderr")

            # FIX #6 (pass 2): ждём до 1.5s — ловим port-busy и немедленный краш
            deadline = time.time() + 1.5
            while time.time() < deadline:
                if proc.poll() is not None:
                    self._join_readers(timeout=0.5)
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        proc.wait(timeout=2)
                    raise RuntimeError(
                        f"Процесс завершился на старте (код {proc.returncode}).\n"
                        f"--- stderr ---\n{self.tail_stderr(80) or '(пусто)'}\n"
                        f"--- stdout ---\n{self.tail_stdout(80) or '(пусто)'}"
                    )
                time.sleep(0.1)

            try:
                ct = psutil.Process(proc.pid).create_time()
            except psutil.NoSuchProcess:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=2)
                raise RuntimeError(
                    f"Процесс исчез сразу после старта.\n{self.tail_stderr(80)}")

            _log.info("process alive, create_time=%s", ct)
            info = PidInfo(
                pid=proc.pid, create_time=ct, started_at=time.time(),
                cmdline=cmd, model_name=model.name,
                alias="bonsai-2-27b",
                ctx_size=int(opts.get("ctx", 0)),
                kv_type=str(opts.get("kv_type", "")),
            )
            self.pid_store.write(info)
            return info

    # ------------------------------------------------------------------
    # STOP
    # ------------------------------------------------------------------
    def stop(self, timeout_s: float = 10.0) -> bool:
        """FIX-A3: Windows — без CTRL_BREAK (не доставляется при CREATE_NO_WINDOW),
        сразу taskkill /T /F с CREATE_NO_WINDOW."""
        info = self.current()
        if not info:
            return False

        if sys.platform == "win32":
            # У дочернего процесса нет консоли ⇒ CTRL_BREAK_EVENT не доставляется.
            # Сразу forceful tree-kill через taskkill.
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(info.pid), "/T", "/F"],
                    capture_output=True, timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                _log.info("taskkill pid=%s rc=%s", info.pid, result.returncode)
            except (subprocess.SubprocessError, OSError) as exc:
                _log.error("taskkill failed: %s", exc)

            # Дождёмся фактического завершения процесса
            try:
                psutil.Process(info.pid).wait(timeout=timeout_s)
            except psutil.TimeoutExpired:
                _log.error("pid=%s survived taskkill after %.0fs", info.pid, timeout_s)
                return False
            except psutil.NoSuchProcess:
                pass
        else:
            # POSIX — без изменений
            try:
                p = psutil.Process(info.pid)
                p.terminate()
                try:
                    p.wait(timeout=timeout_s)
                except psutil.TimeoutExpired:
                    self._kill_tree(info.pid)
                    with contextlib.suppress(psutil.NoSuchProcess):
                        p.wait(timeout=timeout_s)
            except psutil.NoSuchProcess:
                pass

        self.pid_store.clear()
        return True

    def _kill_tree(self, pid: int) -> None:
        """POSIX-вариант дерева (Windows всегда идёт через taskkill выше)."""
        with contextlib.suppress(psutil.NoSuchProcess):
            p = psutil.Process(pid)
            for child in p.children(recursive=True):
                with contextlib.suppress(psutil.NoSuchProcess):
                    child.kill()
            with contextlib.suppress(psutil.NoSuchProcess):
                p.kill()

    # ------------------------------------------------------------------
    # WAIT FOR READY (FIX-A5)
    # ------------------------------------------------------------------
    def wait_for_ready(self, timeout_s: float = 180.0, poll_s: float = 1.0) -> bool:
        """Опрос /health до готовности. Вызывать из worker-потока, не из UI."""
        info = self.current()
        if not info:
            return False
        url = f"http://{internal_host(self.cfg)}:{self.cfg.port}/health"
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not self.pid_store.is_alive(info):
                _log.error("server died during startup; stderr=%s",
                           (self.tail_stderr(40) or "").strip())
                return False
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        _log.info("Server ready")
                        return True
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(poll_s)
        _log.error("Server not ready in %.0fs", timeout_s)
        return False

    # ------------------------------------------------------------------
    # Аргументы
    # ------------------------------------------------------------------
    def build_args(self, model: ModelInfo, opts: dict) -> list[str]:
        """Build llama-server CLI arguments from launch options.

        FIX-A7: условные флаги (проверка поддержки через --help),
        добавление недостающих аргументов из .ps1 (-n, --reasoning-budget, --jinja).
        """
        ctx = int(opts.get("ctx", self.cfg.default_context_length))
        kv = str(opts.get("kv_type", self.cfg.default_kv_cache_type))
        use_mtp = bool(opts.get("use_mtp")) and (model.mtp_path is not None or model.is_mtp_model)

        # SM-4: honor the listen host/port prepared by LaunchTab (layer proxy mode).
        listen_host = str(opts.get("_listen_host") or self.cfg.host)
        listen_port = int(opts.get("_listen_port") or self.cfg.port)
        args: list[str] = [
            "--model", str(model.path),
            "--alias", "bonsai-2-27b",
            "--host", listen_host,
            "--port", str(listen_port),
            "--ctx-size", str(ctx),
            "--cache-type-k", kv,
            "--cache-type-v", kv,
        ]

        # --- KV / checkpoint tuning ---
        # Guard on binary support (PS1 gates the same args via $HasTier/$HasHarness).
        if (cells := opts.get("kv_vram_cells")) \
           and self._binary_supports("--kv-vram-cells"):
            args += ["--kv-vram-cells", str(int(cells))]

        # --- MTP speculative decoding (PrismML fork) ---
        if use_mtp:
            lookup_n = int(opts.get("lookup_n", 0))
            spec_type = "ngram-mod,draft-mtp" if lookup_n > 0 else "draft-mtp"
            args += ["--spec-type", spec_type]

            # N-MAX = сколько драфтов на шаг (PS1: 2 для 12GB, 1 для 8GB)
            spec_n_max = int(opts.get("spec_n_max", 2))
            args += ["--spec-draft-n-max", str(spec_n_max)]

            # SM-3a: draft uses the same KV type as the main model (PS1 parity).
            draft_kv = kv
            args += ["-ctkd", draft_kv, "-ctvd", draft_kv]

            # Draft window. PS1 uses --spec-draft-window whenever the engine has
            # the tiered-KV runtime (independent of kv_vram_cells). The
            # --spec-draft-n-max-tail only matters when the VRAM line splits KV
            # (kv_vram_cells > 0). --spec-draft-depth-max is the legacy fallback.
            draft_window = int(opts.get("draft_window", self.cfg.draft_window or 16384))
            if self._binary_supports("--spec-draft-window"):
                args += ["--spec-draft-window", str(draft_window)]
                if opts.get("kv_vram_cells"):
                    spec_n_max_tail = int(opts.get("spec_deep", 4))
                    args += ["--spec-draft-n-max-tail", str(spec_n_max_tail)]
            else:
                depth_max = int(opts.get("spec_depth", self.cfg.spec_depth or 24576))
                args += ["--spec-draft-depth-max", str(depth_max)]

            # Ngram lookup (from .ps1)
            if lookup_n > 0:
                args += ["--spec-lookup-n-max", str(lookup_n)]

        # --- Sampling / generation params (PS1 defaults) ---
        temp = float(opts.get("temp", 1.0))
        top_p = float(opts.get("top_p", 0.95))
        top_k = int(opts.get("top_k", 20))
        args += ["--temp", str(temp), "--top-p", str(top_p), "--top-k", str(top_k)]
        # SM-3b: PS1 emits --repeat-penalty only when the user set a non-default value.
        rp = opts.get("repeat_penalty")
        if rp is not None and float(rp) != 1.0:
            args += ["--repeat-penalty", str(float(rp))]

        # --- Architecture / GPU layer mapping ---
        ngl = int(opts.get("ngl", self.cfg.ngl))
        args += ["-ngl", str(ngl)]

        # --- Attention / FA tuning ---
        batch = int(opts.get("batch_size", 0)) or self.cfg.batch_size
        if not batch:
            # PS1 sends -b 2048 for every card; the user can still override.
            batch = 2048
        args += ["-b", str(batch)]
        args += ["-fa", "on", "-np", "1"]
        # --- Physical batch size (from .ps1) ---
        user_ubatch = int(opts.get("ubatch") or 0)
        if user_ubatch > 0:
            ubatch = user_ubatch
        else:
            gpu_vram = opts.get("_gpu_vram_mib", 0)
            is_small = (not gpu_vram or gpu_vram <= 8704)
            use_mtp = bool(opts.get("use_mtp"))
            if is_small and not use_mtp:
                ubatch = 1024
            elif is_small:
                ubatch = 256
            elif gpu_vram > 0 and gpu_vram <= 12288:
                ubatch = 256
            else:
                ubatch = 512
        args += ["-ub", str(ubatch)]

        # --- Backend sampling (FIX-A7: условный флаг) ---
        if opts.get("backend_sampling"):
            args.append("--backend-sampling")

        # --- Reasoning effort / think mode (FIX-A7: условный + недостающие аргументы) ---
        effort = str(opts.get("effort", self.cfg.effort))
        harness_proof = bool(opts.get("harness_proof", self.cfg.harness_proof))

        # PS1 only sends --reasoning-effort-allow under harness_proof; the default
        # effort is already applied through LLAMA_ARG_CHAT_TEMPLATE_KWARGS below.
        if effort in ("low", "medium", "high") and harness_proof \
           and self._binary_supports("--reasoning-effort-allow"):
            args += ["--reasoning-effort-allow", f"medium,{effort}"]

        # PS1 logic: --reasoning-budget-message is ALWAYS passed (injects the
        # message before </think> when the budget trips). The
        # --reasoning-max-tokens-floor is part of harness_proof only.
        think_budget = int(opts.get("think_budget", self.cfg.think_budget))
        n_predict = max(24576, think_budget + 4096)
        args += ["--reasoning-budget", str(think_budget), "-n", str(n_predict)]

        if think_budget >= 0:
            msg = opts.get("reasoning_budget_message", "Now produce the complete answer.")
            if msg and self._binary_supports("--reasoning-budget-message"):
                args += ["--reasoning-budget-message", str(msg)]

        if harness_proof:
            fallback = str(opts.get("reasoning_effort_fallback", "medium"))
            if self._binary_supports("--reasoning-effort-fallback"):
                args += ["--reasoning-effort-fallback", fallback]
            if think_budget >= 0 and self._binary_supports("--reasoning-max-tokens-floor"):
                args += ["--reasoning-max-tokens-floor", str(think_budget + 4096)]

        args.append("--jinja")

        # --- Cache RAM / ctx checkpoints ---
        if opts.get("ram_budget_cache") and self._binary_supports("--cache-ram"):
            args += ["--cache-ram", str(int(opts["ram_budget_cache"]))]
        if opts.get("ram_budget_ckpts") and self._binary_supports("--ctx-checkpoints"):
            args += ["--ctx-checkpoints", str(int(opts["ram_budget_ckpts"]))]

        # --- Always-on server args (from start-server.ps1) ---
        # FIX-A7: --fit off — только если бинарник поддерживает (проверка через --help)
        if self._binary_supports("--fit"):
            args += ["--fit", "off"]
        args += ["--prio", "2", "--poll", "100", "--metrics"]

        # SM-3c: multimodal (mmproj) + slot-save-path (PS1 parity).
        mmproj = str(opts.get("mmproj_path") or self.cfg.mmproj_path or "").strip()
        if mmproj and Path(mmproj).is_file():
            args += ["--mmproj", mmproj]
            if not getattr(self.cfg, "mmproj_gpu", False):
                args.append("--no-mmproj-offload")
        slot_save = str(opts.get("slot_save_path") or self.cfg.slot_save_path or "").strip()
        if slot_save:
            args += ["--slot-save-path", slot_save]

        # --- API key (opt-in; matches start-server.ps1 default of no auth) ---
        # Priority: opts.api_key_value (from Advanced Settings UI)
        #          → api_key_path file (fallback for advanced users)
        #          → no --api-key (open server, any Bearer accepted)
        if opts.get("api_key_enabled"):
            api_key = str(opts.get("api_key_value") or "").strip()
            if not api_key:
                api_key = self._read_api_key() or ""
            if api_key:
                args += ["--api-key", api_key]

        # --- Extra raw args (last, so user can override) ---
        import shlex
        if (extra := str(opts.get("extra_args", "")).strip()):
            try:
                args += shlex.split(extra)
            except ValueError:
                args += extra.split()

        return args

    def _binary_supports(self, flag: str) -> bool:
        """FIX-A7: быстрая проверка поддержки флага через --help (cached)."""
        exe = Path(self.cfg.llama_server_exe)
        if not exe.exists():
            return False
        
        # Cache --help output per binary path to avoid spawning every start()
        cache_key = str(exe.resolve())
        if not hasattr(self, "_help_cache"):
            self._help_cache: dict[str, str] = {}
        if cache_key not in self._help_cache:
            try:
                result = subprocess.run(
                    [str(exe), "--help"],
                    capture_output=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                self._help_cache[cache_key] = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            except Exception:
                return False
        
        return flag in self._help_cache.get(cache_key, "")

    def _build_env(self, opts: dict) -> dict[str, str]:
        """Build environment variables for BONSAI_* / GGML_CUDA_* settings.

        SM-2/SM-2b: delegate to bonsai_env.prepare_launch — the single source of
        truth for PS1-equivalent env decisions (capability detection, auto-fills,
        stale-env cleanup). Prefer the plan already prepared by LaunchTab
        (_prepared_env); otherwise prepare here as a fallback.
        """
        if opts.get("_prepared_env"):
            return dict(opts["_prepared_env"])
        try:
            import bonsai_env
        except ImportError:
            return {}
        plan = bonsai_env.prepare_launch(
            opts, self.cfg,
            gpu_vram_mib=int(opts.get("_gpu_vram_mib", 0) or 0),
            gpu_free_mib=int(opts.get("_gpu_free_mib", 0) or 0),
            gpu_name=str(opts.get("_gpu_name", "") or ""),
            model_path=str(opts.get("model_path", "") or ""),
            model_size_gb=float(opts.get("_model_size_gb", 0.0) or 0.0),
            model_has_mtp=bool(opts.get("use_mtp")),
        )
        return plan.env

    def _read_api_key(self) -> Optional[str]:
        p = Path(self.cfg.api_key_path)
        if not p.exists():
            return None
        try:
            return p.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Reader-потоки и логи
    # ------------------------------------------------------------------
    def _spawn_reader(
        self, pipe, buf: deque[str], log_path: Path, name: str,
    ) -> None:
        """Фоновый дренажер pipe → файл + deque. Без этого stderr блокирует сервер."""
        if pipe is None:
            return

        def _reader() -> None:
            fh = None
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                fh = open(log_path, "ab", buffering=0)
                for raw in iter(pipe.readline, b""):
                    with contextlib.suppress(OSError):
                        fh.write(raw)
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line:
                        buf.append(line)
            except (ValueError, OSError):
                pass
            finally:
                if fh:
                    fh.close()

        t = threading.Thread(target=_reader, name=f"llama-{name}", daemon=True)
        t.start()
        self._reader_threads.append(t)

    def _join_readers(self, timeout: float = 0.5) -> None:
        end = time.time() + timeout
        for t in self._reader_threads:
            remaining = end - time.time()
            if remaining <= 0:
                break
            t.join(timeout=remaining)

    @staticmethod
    def _tail_file(path: Path, n: int) -> str:
        if not path.exists():
            return ""
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 64 * 1024))
                data = f.read()
            return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-n:])
        except OSError:
            return ""

    def tail_stdout(self, n: int = 200) -> str:
        return self._tail_file(self.log_out, n)

    def tail_stderr(self, n: int = 200) -> str:
        return self._tail_file(self.log_err, n)

    def combined_log(self, n: int = 500) -> str:
        return f"--- stdout ---\n{self.tail_stdout(n)}\n\n--- stderr ---\n{self.tail_stderr(n)}"
