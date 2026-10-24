"""
Конфигурация приложения: пути, порты, ставки токенов, UI.

Применённые фиксы из дебаг-проходов:
  #2 (pass 3): полная валидация типов в from_dict — устойчивость к битому settings.json
  #7 (pass 2): атомарная запись settings.json (tmp + os.replace)
  + защита от settings.json не-объекта в load_config
"""
from __future__ import annotations

import json
import os
import sys
import ipaddress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _frozen_root() -> Path:
    """Return the application root directory.

    When running as a PyInstaller frozen executable, __file__ points inside
    _internal/ (or similar), so we fall back to the exe's parent directory.
    This keeps settings.json and artifacts/ next to the .exe.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROJECT_ROOT = _frozen_root()


def _find_llama_exe(project_root: Path) -> Path:
    """Переносимый поиск llama-server.exe относительно корня приложения.

    Проверяет типовые расположения (текущая структура + будущая, где скомпилированный
    exe лежит в одной папке с bonsai). Возвращает первый найденный файл, иначе —
    дефолтный путь (может не существовать; пользователь задаст его в настройках).
    """
    root = Path(project_root).resolve()
    candidates = [
        root / "llama-server.exe",
        root / "bin" / "llama-server.exe",
        root / "bonsai surgery" / "bin" / "llama-server.exe",
        root.parent / "bonsai surgery" / "bin" / "llama-server.exe",
        root.parent / "bin" / "llama-server.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return root / "llama-server.exe"


DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "settings.json"
DEFAULT_MODELS_DIR    = PROJECT_ROOT / "modules"
DEFAULT_LLAMA_EXE     = _find_llama_exe(PROJECT_ROOT)
DEFAULT_API_KEY_PATH  = PROJECT_ROOT / "artifacts" / "api_key.txt"
DEFAULT_DATA_PATH     = PROJECT_ROOT / "artifacts" / "usage.csv"
DEFAULT_LOGS_DIR      = PROJECT_ROOT / "artifacts" / "logs"
DEFAULT_PIDFILE       = PROJECT_ROOT / "artifacts" / "server.pid"
DEFAULT_LOCKFILE      = PROJECT_ROOT / "artifacts" / "server.lock"


# ---------------------------------------------------------------------------
# Ставка токенов для одной модели
# ---------------------------------------------------------------------------
@dataclass
class ModelCost:
    prompt_per_1k_cny: float = 0.0
    completion_per_1k_cny: float = 0.0


# ---------------------------------------------------------------------------
# Preset (user-defined or built-in launch configuration)
# ---------------------------------------------------------------------------
@dataclass
class Preset:
    name: str          # "Very Fast", "Fast", ... or user-entered name
    tier: str          # "very_fast" | "fast" | "mid" | "slow" | "very_slow" | "custom"
    context_length: int = 32768
    kv_cache_type: str = "q4_0"
    ngl: int = 200
    batch_size: int = 0
    spec_depth: int = 24576
    draft_window: int = 16384
    spec_deep: int = 4
    temp: float = 0.6
    top_p: float = 0.95
    repeat_penalty: float = 1.1
    top_k: int = 20
    effort: str = "medium"
    think: bool = True
    backend_sampling: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Preset":
        if not isinstance(d, dict):
            return cls(name="Unknown", tier="custom")
        known = set(cls.__dataclass_fields__)
        kwargs = {k: v for k, v in d.items() if k in known}
        try:
            return cls(**kwargs)
        except (TypeError, ValueError, KeyError):
            return cls(name=d.get("name", "Unknown"), tier="custom")


# ---------------------------------------------------------------------------
# Конфиг приложения
# ---------------------------------------------------------------------------
@dataclass
class AppConfig:
    # --- пути ---
    project_root: str = str(PROJECT_ROOT)
    models_dir: str = str(DEFAULT_MODELS_DIR)
    llama_server_exe: str = str(DEFAULT_LLAMA_EXE)
    api_key_path: str = str(DEFAULT_API_KEY_PATH)
    data_path: str = str(DEFAULT_DATA_PATH)
    settings_path: str = str(DEFAULT_SETTINGS_PATH)
    pidfile_path: str = str(DEFAULT_PIDFILE)
    lockfile_path: str = str(DEFAULT_LOCKFILE)
    logs_dir: str = str(DEFAULT_LOGS_DIR)

    # --- сервер ---
    # M3: PS1 binds to 0.0.0.0 for LAN access (cloudflared tunnels)
    host: str = "0.0.0.0"
    port: int = 8080
    api_endpoint: str = "http://localhost:8080/v1"
    # --- API key auth (opt-in; matches start-server.ps1 default of no --api-key) ---
    api_key_enabled: bool = False        # OFF → open server, any Bearer accepted
    api_key_value: str = ""              # actual key (empty → fallback to api_key_path file)

    # --- GPU / VRAM ---
    small_gpu_threshold_mib: int = 8704   # 8GB карты: 8192 MiB + запас
    vram_margin_mib: int = 1300
    model_min_size_gb: float = 0.09       # принимать .gguf от ~100 МБ

    # --- KV / context ---
    default_context_length: int = 32768
    default_kv_cache_type: str = "q8_0"

    # --- монитор ---
    refresh_interval_s: int = 2
    terminal_buffer_lines: int = 2000

    # --- графики ---
    chart_granularity: str = "daily"      # daily | weekly | monthly
    accent_color: str = "#6C5CE7"

    # --- ставки по моделям: {model_name: {"prompt_per_1k_cny":.., "completion_per_1k_cny":..}} ---
    model_costs: dict[str, dict[str, float]] = field(default_factory=dict)

    # --- статистика (SQLite) ---
    stats_db_path: str = str(PROJECT_ROOT / "artifacts" / "stats.db")
    stats_retention_days: int = 30
    sample_interval_s: int = 10

    # --- last used launch settings (persisted for auto-restore) ---
    last_selected_model_path: str = ""
    last_context_length: int = 32768
    last_kv_cache_type: str = "q8_0"

    # --- advanced server settings (mapped to BONSAI_* env vars and llama-server args) ---
    spec_depth: int = 24576              # --spec-draft-n-max-tail / BONSAI_SPEC_DEPTH
    ubatch: int = 0                      # 0 = auto, LLAMA_MTP_DRAFT_UBATCH
    shared_pool: bool = False            # GGML_CUDA_SHARED_POOL / BONSAI_SHARED_POOL
    prefill_f16: int = 0                 # 0 = auto, GGML_CUDA_FA_PREFILL_F16
    fa_chunk: int = 0                    # 0 = auto, GGML_CUDA_FA_CHUNK
    ckpt_every: int = 8192               # --checkpoint-every-nt / BONSAI_CKPT_EVERY (0 = off)
    kv_vram_cells: int = 0                # 0 = auto, BONSAI_KV_VRAM_CELLS
    stage_cells: int = 81920              # GGML_CUDA_KV_TIER_STAGING_FRAC / BONSAI_STAGE_CELLS
    ram_budget_cache_mib: int = 0         # 0 = auto, --cache-ram
    ram_budget_ckpts: int = 0             # 0 = auto, --ctx-checkpoints
    think: bool = True                   # BONSAI_THINK
    effort: str = "medium"               # low | medium | high, --reasoning-effort-allow
    think_budget: int = 20480            # BONSAI_THINK_BUDGET
    harness_proof: bool = False          # BONSAI_HARNESS_PROOF
    backend_sampling: bool = False       # BONSAI_BS / --backend-sampling
    kq_mask_packed: bool = False         # LLAMA_ARG_KQ_MASK_PACKED / --kq-mask-packed
    draft_window: int = 16384            # --spec-draft-window
    spec_deep: int = 4                   # BONSAI_SPEC_DEEP (1 for small, 4 for large)
    pool_mib: int = 0                    # 0 = auto, GGML_CUDA_SHARED_POOL / BONSAI_POOL_MIB
    temp: float = 0.6                    # --temp
    top_p: float = 0.95                  # --top-p
    repeat_penalty: float = 1.1          # --repeat-penalty
    top_k: int = 20                      # --top-k
    batch_size: int = 0                  # 0 = auto, -b
    ngl: int = 200                       # -ngl

    # --- currency & pricing ---
    currency: str = "CNY"                # CNY | USD | RUB | EUR
    # Global token prices (per 1M tokens). Used in Analytics.
    price_input_per_1m: float = 0.0      # non-cached input
    price_output_per_1m: float = 0.0     # output
    price_cached_input_per_1m: float = 0.0  # cached input
    # Legacy (mapped to input price on load)
    price_per_1m: float = 0.0

    # --- UI ---
    language: str = "en"                 # en | ru | cn
    start_in_performance_mode: bool = False
    show_tray_notifications: bool = True

    # --- last launch config (auto-saved on start, auto-applied on next GUI start) ---
    last_launch: dict = field(default_factory=dict)

    # --- presets (up to 3 user-defined) ---
    user_presets: list[dict] = field(default_factory=list)

    # --- theme ---
    theme_name: str = "one_dark"         # dracula | solarized_dark | solarized_light | nord | monokai | one_dark | github_dark | tokyo_night

    # --- PS1 parity (start-server.ps1) ---
    mmproj_path: str = ""                # multimodal projection .gguf path (blank = off)
    mmproj_gpu: bool = False             # offload mmproj to GPU
    slot_save_path: str = ""             # --slot-save-path (saved conversations / slots)
    layer_enabled: bool = False          # Bonsai layer proxy on/off
    layer_inner_port: int = 0            # inner port for the layer proxy (0 = auto)
    effort_mode: str = "medium"          # low | medium | high | xhigh
    force_8gb: int = -1                  # -1 auto, 0 off, 1 force-8GB-card
    sparse_mode: int = -1                # -1 auto, 0 off, 1 on (sparse FA)
    rs_replay_mode: int = -1             # -1 auto, 0 off, 1 on (RS_REPLAY rollback)

    # --- advanced server opts (полный dict из AdvancedSettingsDialog; переживает перезапуск) ---
    advanced_opts: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------
    def validate(self) -> list[str]:
        """Валидация конфигурации перед сохранением. Возвращает список ошибок (пустой = OK)."""
        errors: list[str] = []

        # --- Path fields: non-empty, no null bytes ---
        path_fields = (
            "project_root", "models_dir", "llama_server_exe", "api_key_path",
            "data_path", "settings_path", "pidfile_path", "lockfile_path",
            "logs_dir", "stats_db_path",
        )
        for fname in path_fields:
            val = getattr(self, fname)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"Путь {fname} не может быть пустым")
            elif "\x00" in val:
                errors.append(f"Путь {fname} содержит недопустимые символы (null byte)")

        # --- models_dir must be a directory if it exists ---
        md = self.models_dir
        if isinstance(md, str) and md.strip():
            p = Path(md)
            if p.exists() and not p.is_dir():
                errors.append(f"models_dir '{md}' существует, но не является каталогом")

        # --- api_endpoint must be a valid URL ---
        ae = self.api_endpoint
        if isinstance(ae, str) and ae.strip():
            if not (ae.startswith("http://") or ae.startswith("https://")):
                errors.append(f"api_endpoint '{ae}' должен начинаться с http:// или https://")

        # --- host validation ---
        h = self.host
        if not isinstance(h, str) or not h.strip():
            errors.append("host не может быть пустым")
        elif "\x00" in h or " " in h:
            errors.append(f"host '{h}' содержит недопустимые символы")

        # --- model_costs structure: string keys, numeric values in [0, 1e6] ---
        mc = self.model_costs
        if isinstance(mc, dict):
            for model_name, costs in mc.items():
                if not isinstance(model_name, str) or not model_name.strip():
                    errors.append("model_costs: имя модели должно быть непустой строкой")
                    continue
                if not isinstance(costs, dict):
                    errors.append(f"model_costs['{model_name}']: значение должно быть объектом (dict)")
                    continue
                for field_name in ("prompt_per_1k_cny", "completion_per_1k_cny"):
                    v = costs.get(field_name)
                    if v is not None:
                        try:
                            fv = float(v)
                            if fv < 0 or fv > 1e6:
                                errors.append(
                                    f"model_costs['{model_name}']['{field_name}'] вне диапазона [0, 1e6]"
                                )
                        except (TypeError, ValueError):
                            errors.append(
                                f"model_costs['{model_name}']['{field_name}'] не является числом"
                            )

        return errors

    def get_model_cost(self, model_name: str) -> ModelCost:
        """Безопасный доступ к ставкам. Возвращает нули, если модель не сконфигурирована."""
        raw = self.model_costs.get(model_name) if isinstance(self.model_costs, dict) else None
        if not isinstance(raw, dict):
            return ModelCost()
        try:
            return ModelCost(
                prompt_per_1k_cny=float(raw.get("prompt_per_1k_cny", 0.0)),
                completion_per_1k_cny=float(raw.get("completion_per_1k_cny", 0.0)),
            )
        except (TypeError, ValueError):
            return ModelCost()

    def ensure_dirs(self) -> None:
        """Гарантирует существование папок, куда пишем логи/pidfile."""
        for p in (
            self.logs_dir,
            str(Path(self.pidfile_path).parent),
            str(Path(self.lockfile_path).parent),
            str(Path(self.data_path).parent),
        ):
            Path(p).mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # ------------------------------------------------------------------
    # FIX #2 (pass 3): from_dict валидирует типы, а не просто копирует поля
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppConfig":
        if not isinstance(d, dict):
            return cls()

        known = set(cls.__dataclass_fields__)
        cfg = cls(**{k: v for k, v in d.items() if k in known})
        defaults = cls()  # источник дефолтов для откатов

        # --- model_costs: dict[str, dict[str, float]] ---
        if not isinstance(cfg.model_costs, dict):
            cfg.model_costs = {}
        else:
            cleaned: dict[str, dict[str, float]] = {}
            for m, v in cfg.model_costs.items():
                if not isinstance(m, str) or not isinstance(v, dict):
                    continue
                try:
                    cleaned[m] = {
                        "prompt_per_1k_cny": float(v.get("prompt_per_1k_cny", 0.0)),
                        "completion_per_1k_cny": float(v.get("completion_per_1k_cny", 0.0)),
                    }
                except (TypeError, ValueError):
                    continue
            cfg.model_costs = cleaned

        # --- user_presets: list[dict] (max 3) ---
        if not isinstance(cfg.user_presets, list):
            cfg.user_presets = []
        else:
            cleaned_presets: list[dict] = []
            for p in cfg.user_presets:
                if isinstance(p, dict):
                    cleaned_presets.append(p)
            # Keep only last 3 (newest at end)
            cfg.user_presets = cleaned_presets[-3:]

        # --- advanced_opts: dict — устойчивость к битому settings.json ---
        if not isinstance(cfg.advanced_opts, dict):
            cfg.advanced_opts = {}

        # --- number fields with ranges ---
        for fname, lo, hi in (
            ("port", 1, 65535),
            ("refresh_interval_s", 1, 300),
            ("small_gpu_threshold_mib", 1024, 65536),
            ("vram_margin_mib", 0, 16384),
            ("terminal_buffer_lines", 100, 100_000),
            ("default_context_length", 1024, 1_048_576),
            ("stats_retention_days", 1, 3650),
            ("sample_interval_s", 1, 60),
            # --- advanced numeric fields ---
            ("spec_depth", 1, 1_048_576),
            ("ubatch", 0, 1_048_576),
            ("ckpt_every", 0, 1_048_576),
            ("kv_vram_cells", 0, 1_048_576),
            ("stage_cells", 0, 1_048_576),
            ("ram_budget_cache_mib", 0, 262144),
            ("ram_budget_ckpts", 0, 262144),
            ("think_budget", 0, 1_048_576),
            ("draft_window", 1, 1_048_576),
            ("spec_deep", 1, 32),
            ("pool_mib", 0, 262144),
            ("top_k", 1, 10000),
            ("batch_size", 0, 1_048_576),
            ("ngl", 1, 1024),
            ("last_context_length", 1024, 1_048_576),
            # --- PS1 parity int fields ---
            ("layer_inner_port", 0, 65535),
            ("force_8gb", -1, 1),
            ("sparse_mode", -1, 1),
            ("rs_replay_mode", -1, 1),
        ):
            try:
                val = int(getattr(cfg, fname))
                setattr(cfg, fname, max(lo, min(hi, val)))
            except (TypeError, ValueError):
                setattr(cfg, fname, getattr(defaults, fname))

        # --- float fields with ranges ---
        for fname, lo, hi in (
            ("model_min_size_gb", 0.001, 512.0),
            ("temp", 0.0, 4.0),
            ("top_p", 0.0, 1.0),
            ("repeat_penalty", 0.0, 10.0),
            ("price_per_1m", 0.0, 1e6),
            ("price_input_per_1m", 0.0, 1e6),
            ("price_output_per_1m", 0.0, 1e6),
            ("price_cached_input_per_1m", 0.0, 1e6),
        ):
            try:
                val = float(getattr(cfg, fname))
                setattr(cfg, fname, max(lo, min(hi, val)))
            except (TypeError, ValueError):
                setattr(cfg, fname, getattr(defaults, fname))

        # --- bool fields: "false"/"true" strings from JSON must become real booleans ---
        for fname in (
            "shared_pool", "prefill_f16", "fa_chunk", "think",
            "harness_proof", "backend_sampling", "kq_mask_packed",
            "start_in_performance_mode",
            "api_key_enabled",              # ← NEW: matches PS1 ($ApiKey = $null)
            # --- PS1 parity bool fields ---
            "mmproj_gpu", "layer_enabled",
        ):
            val = getattr(cfg, fname)
            if isinstance(val, bool):
                continue
            if isinstance(val, str):
                try:
                    cfg.__dict__[fname] = val.lower() in ("true", "1", "yes")
                except AttributeError:
                    setattr(cfg, fname, getattr(defaults, fname))
            else:
                setattr(cfg, fname, bool(val) if val is not None else False)

        # --- Migration: legacy single price → three new prices (one-time) ---
        try:
            old = float(getattr(cfg, "price_per_1m", 0.0) or 0.0)
        except (TypeError, ValueError):
            old = 0.0
        if old > 0 and not (cfg.price_input_per_1m or cfg.price_output_per_1m
                             or cfg.price_cached_input_per_1m):
            cfg.price_input_per_1m = old
            cfg.price_output_per_1m = old
            cfg.price_cached_input_per_1m = old
            cfg.price_per_1m = 0.0   # mark migration as done

        # --- string paths/fields: not None and exactly str ---
        for fname in (
            "project_root", "models_dir", "llama_server_exe", "api_key_path",
            "data_path", "settings_path", "pidfile_path", "lockfile_path",
            "logs_dir", "host", "api_endpoint", "default_kv_cache_type",
            "chart_granularity", "accent_color", "language", "stats_db_path",
            "last_selected_model_path",
            # --- advanced string fields ---
            "effort", "currency", "effort_mode",
            "api_key_value",                # ← NEW: actual API key value
            # --- PS1 parity string fields ---
            "mmproj_path", "slot_save_path",
        ):
            if not isinstance(getattr(cfg, fname, None), str):
                setattr(cfg, fname, getattr(defaults, fname))

        # --- enum fields ---
        if cfg.chart_granularity not in ("daily", "weekly", "monthly"):
            cfg.chart_granularity = "daily"
        if cfg.default_kv_cache_type not in ("q8_0", "q4_0", "f16"):
            cfg.default_kv_cache_type = "q8_0"
        if cfg.currency not in ("CNY", "USD", "RUB", "EUR"):
            cfg.currency = "CNY"
        if cfg.language not in ("en", "ru", "cn"):
            cfg.language = "en"
        if cfg.effort not in ("low", "medium", "high"):
            cfg.effort = "medium"
        # --- PS1 parity enum field ---
        if cfg.effort_mode not in ("low", "medium", "high", "xhigh"):
            cfg.effort_mode = "medium"
        if cfg.last_kv_cache_type not in ("q8_0", "q5_0", "q4_0", "f16"):
            cfg.last_kv_cache_type = "q8_0"

        # --- theme_name validation ---
        valid_themes = (
            "dracula", "solarized_dark", "solarized_light", "nord",
            "monokai", "one_dark", "github_dark", "tokyo_night",
        )
        if cfg.theme_name not in valid_themes:
            cfg.theme_name = "one_dark"

        # --- last_launch: dict with only int/float/str/bool values, str keys ---
        if not isinstance(cfg.last_launch, dict):
            cfg.last_launch = {}
        else:
            cleaned_ll: dict = {}
            for k, v in cfg.last_launch.items():
                if not isinstance(k, str):
                    continue
                if isinstance(v, (int, float, str, bool)):
                    cleaned_ll[k] = v
            cfg.last_launch = cleaned_ll

        return cfg


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------
def _resolve_stale_paths(cfg: AppConfig) -> None:
    """Переносимость: если сохранённый абсолютный путь больше не существует,
    подставляем переносимый кандидат относительно PROJECT_ROOT."""
    root = Path(PROJECT_ROOT).resolve()
    llama_cands = [
        root / "llama-server.exe",
        root / "bin" / "llama-server.exe",
        root / "bonsai surgery" / "bin" / "llama-server.exe",
        root.parent / "bonsai surgery" / "bin" / "llama-server.exe",
    ]
    models_cands = [
        root / "modules",
        root / "bonsai surgery" / "modules",
        root.parent / "bonsai surgery" / "modules",
    ]
    stored_exe = cfg.llama_server_exe
    if not Path(stored_exe).is_file():
        for c in llama_cands:
            if c.is_file():
                cfg.llama_server_exe = str(c)
                break
    stored_md = cfg.models_dir
    if not Path(stored_md).is_dir():
        for c in models_cands:
            if c.is_dir():
                cfg.models_dir = str(c)
                break


def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    """Никогда не падает: при любом битом settings.json — дефолтный конфиг."""
    p = Path(path) if path else DEFAULT_SETTINGS_PATH
    if not p.exists():
        return AppConfig()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AppConfig()
        cfg = AppConfig.from_dict(raw)
        _resolve_stale_paths(cfg)
        return cfg
    except (json.JSONDecodeError, TypeError, ValueError, OSError):
        return AppConfig()


def save_config(cfg: AppConfig, path: str | os.PathLike | None = None) -> None:
    """FIX #7 (pass 2): атомарная запись — краш посреди write не портит settings.json."""
    p = Path(path) if path else Path(cfg.settings_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)  # атомарно на Windows и POSIX


def internal_host(cfg: "AppConfig") -> str:
    """Host to use for *local* HTTP checks (/health, /metrics).

    cfg.host is a bind address (default "0.0.0.0"). For local health/metrics
    probes we must dial loopback instead of the wildcard bind target.
    """
    h = (cfg.host or "").strip()
    if h in ("", "0.0.0.0", "::", "[::]"):
        return "127.0.0.1"
    return h


# ---------------------------------------------------------------------------
# FIX #4: LAN IP detection helper (BUG 6: filter virtual adapters, sort by priority)
# ---------------------------------------------------------------------------
def detect_lan_ips() -> list[tuple[str, str]]:
    """Возвращает [(interface_name, ipv4)] для всех не-loopback интерфейсов.

    Фильтрует виртуальные адаптеры (WSL, Hyper-V, Docker, VirtualBox) и
    сортирует по приоритету IP-диапазона: 192.168.x > 10.x > другие private.
    """
    import socket

    out: list[tuple[str, str]] = []
    try:
        import psutil
        for iface, addrs in psutil.net_if_addrs().items():
            # Filter virtual adapters (WSL, Hyper-V, Docker, VirtualBox, etc.)
            iface_lower = iface.lower()
            if any(kw in iface_lower for kw in ("virtual", "wsl", "docker",
                                               "hyper-v", "hyperv", "vmware",
                                               "vbox", "loopback")):
                continue
            for a in addrs:
                if a.family == socket.AF_INET:
                    ip = a.address
                    # Skip loopback, link-local, and non-routable addresses
                    if (ip.startswith("127.") or ip.startswith("169.254.")
                            or ip.startswith("0.") or ip.startswith("255.")):
                        continue
                    out.append((iface, ip))
    except Exception:
        pass

    # Sort by IP range priority: 192.168.x > 10.x > other private (172.16-31)
    def _ip_priority(ip: str) -> int:
        try:
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private:
                parts = ip.split(".")
                if len(parts) == 4 and parts[0] == "192" and parts[1] == "168":
                    return 0  # highest priority
                if len(parts) == 4 and parts[0] == "10":
                    return 1
                if len(parts) == 4 and parts[0] == "172":
                    return 2
            return 3
        except ValueError:
            return 9

    out.sort(key=lambda x: _ip_priority(x[1]))
    return out
