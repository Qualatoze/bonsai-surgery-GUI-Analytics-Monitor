"""PS1-equivalent server launch preparation.

This module is the single source of truth for what start-server.ps1 decides:
capability detection (from --help and DLL strings), auto-pick of KV type /
context / VRAM margin / spec depth, PS1-accurate VRAM-cell and RAM-budget
formulas, and the full env-var dict. server_manager delegates here.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


MB = 1024 * 1024


@dataclass
class Capabilities:
    has_tier: bool = False          # --kv-vram-cells
    has_harness: bool = False        # --reasoning-effort-allow
    has_262: bool = False            # --kq-mask-packed (used as proxy)
    has_replay: bool = False         # LLAMA_RS_REPLAY in llama.dll
    has_8gb_switches: bool = False   # GGML_CUDA_SHARED_POOL in ggml-cuda.dll
    has_sparse: bool = False         # GGML_CUDA_FA_SPARSE_MIN_HOST
    has_sparse_auto: bool = False    # GGML_CUDA_FA_SPARSE_AUTO + KV_TIER_DEMOTE_FRAC
    has_q3: bool = False             # "q3_0" in --help
    has_packed_mask: bool = False    # --kq-mask-packed in --help
    has_checkpoint: bool = False     # --checkpoint-every-nt in --help
    has_cache_ram: bool = False
    has_ctx_checkpoints: bool = False
    help_text: str = ""


_CAP_CACHE: dict[tuple[str, int], Capabilities] = {}


def _read_file_text(p: Path) -> str:
    try:
        return p.read_bytes().decode("latin-1", errors="ignore")
    except OSError:
        return ""


def detect_capabilities(bin_dir: str | Path) -> Capabilities:
    """Detect which llama-server / DLL features are available."""
    bin_dir = Path(bin_dir)
    exe = bin_dir / "llama-server.exe"
    key = (str(exe), int(exe.stat().st_mtime) if exe.exists() else 0)
    if key in _CAP_CACHE:
        return _CAP_CACHE[key]

    caps = Capabilities()
    if exe.exists():
        try:
            r = subprocess.run(
                [str(exe), "--help"], capture_output=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            caps.help_text = (r.stdout + r.stderr).decode("utf-8", errors="replace")
        except Exception:
            pass

    h = caps.help_text
    caps.has_tier = "--kv-vram-cells" in h
    caps.has_harness = "--reasoning-effort-allow" in h
    caps.has_packed_mask = "--kq-mask-packed" in h
    caps.has_checkpoint = "--checkpoint-every-nt" in h
    caps.has_cache_ram = "--cache-ram" in h
    caps.has_ctx_checkpoints = "--ctx-checkpoints" in h
    caps.has_q3 = bool(re.search(r"\bq3_0\b", h))

    cuda = _read_file_text(bin_dir / "ggml-cuda.dll")
    llama = _read_file_text(bin_dir / "llama.dll")

    caps.has_262 = ("--kq-mask-packed" in h) and ("GGML_CUDA_KV_TIER_STAGING_FRAC" in cuda)
    caps.has_replay = "LLAMA_RS_REPLAY" in llama
    caps.has_8gb_switches = "GGML_CUDA_SHARED_POOL" in cuda
    caps.has_sparse = "GGML_CUDA_FA_SPARSE_MIN_HOST" in cuda
    caps.has_sparse_auto = ("GGML_CUDA_FA_SPARSE_AUTO" in cuda
                            and "GGML_CUDA_KV_TIER_DEMOTE_FRAC" in cuda)

    _CAP_CACHE[key] = caps
    return caps


def detect_ram_gib() -> int:
    """Detect physical RAM in GiB. psutil first, wmic as fallback."""
    try:
        import psutil
        return int(psutil.virtual_memory().total / (1024 ** 3) + 0.5)
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory", "/value"],
                capture_output=True, timeout=3, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
            m = re.search(r"TotalPhysicalMemory=(\d+)", out)
            if m:
                return int(int(m.group(1)) / (1024 ** 3) + 0.5)
    except Exception:
        pass
    return 0


def detect_headless(gpu_name: str) -> bool:
    """PS1 heuristic: nvidia-smi display_active == Disabled, unless a Windows
    video controller that is NOT this GPU reports a resolution."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=display_active", "--format=csv,noheader"],
            capture_output=True, timeout=3, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if r.returncode != 0:
            return False
        headless = r.stdout.strip().splitlines()[0].strip() == "Disabled"
    except Exception:
        return False
    if not headless:
        return False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | "
             "Where-Object { $_.CurrentHorizontalResolution -and $_.Name -ne '%s' } | "
             "Select-Object -First 1 -ExpandProperty Name" % gpu_name.replace("'", "")],
            capture_output=True, timeout=4, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # PS1: if NO other adapter has a resolution AND this card reports one → not headless
        # Reverse: if NO other adapter has a resolution, check our own adapter
        if not r.stdout.strip():
            r2 = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -eq '%s' }).CurrentHorizontalResolution" % gpu_name.replace("'", "")],
                capture_output=True, timeout=3, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r2.stdout.strip().isdigit():
                return False
    except Exception:
        pass
    return True


def auto_ctk(caps: Capabilities, total_vram_mib: int) -> str:
    small = total_vram_mib <= 8704
    if small:
        return "q3_0" if caps.has_q3 else "q4_0"
    if 12288 < total_vram_mib <= 14336:
        return "q4_0"
    return "q8_0"


def auto_ctx(caps: Capabilities, total_vram_mib: int, ram_gib: int,
             model_name: str, spec_on: bool) -> int:
    small = total_vram_mib <= 8704
    if not small:
        return 262144 if caps.has_tier else 98304
    small262 = (caps.has_tier and caps.has_262 and ram_gib >= 24
                and spec_on and "-mtp" in model_name.lower())
    return 262144 if small262 else 131072


def auto_spec_n_max(small: bool) -> int:
    return 1 if small else 2


def auto_spec_deep(small: bool, has_replay: bool) -> int:
    if small:
        return 2 if has_replay else 1
    return 4


def auto_margin(headless: bool, small: bool, spec_on: bool) -> int:
    if small:
        return 225 if spec_on else 400
    return 1000 if headless else 1300


# Bytes per KV cell for the Bonsai 2 27B architecture (16 attention layers,
# 4 heads x 256 dims, K+V). Sparse page bounds and staging share separately.
_CELL_BYTES = {"q8_0": 34816, "q4_0": 18432, "q3_0": 14336, "f16": 65536}


def auto_kv_vram_cells(*, caps: Capabilities, total_vram_mib: int,
                       free_vram_mib: int, model_size_mb: float,
                       mmproj_mib: int, ctx: int, ctk: str, spec: int,
                       spec_deep: int, small: bool, headless: bool,
                       model_has_mtp: bool, ubatch: int,
                       replay_on: bool, packed_mask: bool,
                       sparse_page: int = 0, stage_cells: int = 81920) -> int:
    """PS1-equivalent VRAM line sizing (docs/*/README.md receipts)."""
    cell_bytes = _CELL_BYTES.get(ctk, 34816)
    margin = auto_margin(headless, small, spec > 0)
    pool_mib = 0
    if spec > 0:
        pool_mib = 48 if small else 42
    mask_saved_mib = 0
    if packed_mask and not small and ctx > 0:
        mask_saved_mib = int(ctx * ubatch * 2 * 15 / 16 / MB)
    draft_cells = (16384 + 2 * 2048 + 256) if caps.has_tier and spec > 0 else 0

    if small:
        if spec > 0:
            fixed = 6531 + mmproj_mib
        elif ubatch >= 1024:
            fixed = 6218 + mmproj_mib
        else:
            fixed = 5955 + mmproj_mib
        if replay_on:
            fixed += -142 + 7 * (max(spec, spec_deep) - 1)
        mask_mib = (ctx * ubatch / 8 / MB) if packed_mask else (ctx * ubatch * 2 / MB)
        fixed += mask_mib - 131072 * ubatch * 2 / MB - pool_mib
    else:
        fixed = (model_size_mb - 265 + 150 + 400 + 300
                 + draft_cells * cell_bytes / 16 / MB
                 + mmproj_mib - pool_mib - mask_saved_mib)

    sparse_cell_bytes = 0
    if sparse_page:
        sparse_cell_bytes = 16 * 4 * (2 * 256 + 2) / sparse_page

    if sparse_page:
        fixed += 64

    partial = (small and caps.has_tier and stage_cells > 0)
    if partial:
        budget = (free_vram_mib - margin - fixed) * MB \
                 - stage_cells * cell_bytes / 16 - ctx * sparse_cell_bytes
        denom = cell_bytes - sparse_cell_bytes
        cells = int(budget / denom / 256) * 256 if denom > 0 else 0
    else:
        budget = (free_vram_mib - margin - fixed) * MB - ctx * cell_bytes / 16 - ctx * sparse_cell_bytes
        denom = cell_bytes * 15 / 16 - sparse_cell_bytes
        cells = int(budget / denom / 256) * 256 if denom > 0 else 0

    if cells >= ctx:
        return 0  # everything fits: plain cache
    return max(0, cells)


def auto_ram_budget(ram_gib: int, commit_free_mib: int,
                    server_vram_mib: int, kv_tail_mib: int) -> tuple[Optional[int], Optional[int]]:
    """PS1 issue-#16 formula. Returns (cache_mib, checkpoints) or (None, None)
    for server defaults."""
    if ram_gib >= 48:
        return None, None
    if ram_gib >= 24:
        return 4096, 32
    budget = commit_free_mib - server_vram_mib - kv_tail_mib - 2048
    ckpts = max(4, min(32, int(0.4 * max(0, budget) / 170)))
    cache = min(8192, int(0.5 * (budget - ckpts * 170)))
    if cache < 1536:
        cache = 0
    return cache, ckpts


@dataclass
class LaunchPlan:
    opts: dict               # effective opts (after auto-fills)
    env: dict                # env vars to apply on top of os.environ
    caps: Capabilities
    notes: list[str] = field(default_factory=list)
    listen_host: str = "0.0.0.0"
    listen_port: int = 8080


_STALE_ENV = (
    "BONSAI_8GB", "BONSAI_TIER", "BONSAI_SPEC", "BONSAI_CTK", "BONSAI_EFFORT",
    "BONSAI_THINK", "BONSAI_THINK_BUDGET", "BONSAI_THINK_BUDGET_MSG",
    "BONSAI_HARNESS_PROOF", "BONSAI_EFFORT_ALLOWED", "BONSAI_BS",
    "BONSAI_SPEC_DEEP", "BONSAI_SPEC_DEPTH", "BONSAI_SPEC_TYPE",
    "BONSAI_SPEC_ARGS", "BONSAI_DRAFT_WINDOW", "BONSAI_LOOKUP_N",
    "BONSAI_LOOKUP", "BONSAI_KV_VRAM_CELLS", "BONSAI_STAGE_CELLS",
    "BONSAI_POOL_MIB", "BONSAI_SHARED_POOL", "BONSAI_RS_REPLAY",
    "BONSAI_SPARSE", "BONSAI_SPARSE_LATE", "BONSAI_RAM_BUDGET",
    "BONSAI_RAM_GB", "BONSAI_CKPT_EVERY", "BONSAI_UBATCH",
    "BONSAI_VRAM_MARGIN", "BONSAI_TOTAL_MIB", "BONSAI_MODEL",
    "BONSAI_MMPROJ", "BONSAI_MMPROJ_GPU", "BONSAI_CTX", "BONSAI_PORT",
    "BONSAI_LAYER", "BONSAI_INNER_PORT", "BONSAI_SLOT_SAVE_PATH",
    "BONSAI_SLOT_CACHE_GROW", "BONSAI_LAYER_KEY",
    "BONSAI_SPILL_GUARD",
    "GGML_CUDA_SHARED_POOL", "GGML_CUDA_BATCH_INVARIANT",
    "GGML_CUDA_FA_PREFILL_F16", "GGML_CUDA_FA_CHUNK",
    "GGML_CUDA_KV_TIER_STAGING_FRAC", "GGML_CUDA_KV_TIER_DEMOTE_FRAC",
    "GGML_CUDA_FA_SPARSE_MIN_HOST", "GGML_CUDA_FA_SPARSE_FAST",
    "GGML_CUDA_FA_SPARSE_FRAC", "GGML_CUDA_KV_TIER_STAGE_MIN_Q",
    "GGML_CUDA_FA_SPARSE_CALIB", "GGML_CUDA_FA_SPARSE_CALIB_KEY",
    "LLAMA_ARG_MMPROJ", "LLAMA_ARG_KQ_MASK_PACKED",
    "LLAMA_ARG_CHECKPOINT_EVERY_NT", "LLAMA_ARG_CHAT_TEMPLATE_KWARGS",
    "LLAMA_MTP_DRAFT_UBATCH", "LLAMA_RS_REPLAY",
    "LLAMA_ARG_CACHE_RAM", "LLAMA_ARG_CTX_CHECKPOINTS",
)


def prepare_launch(opts: dict, cfg, *, gpu_vram_mib: int = 0,
                   gpu_free_mib: int = 0, gpu_name: str = "",
                   model_path: str = "", model_size_gb: float = 0.0,
                   model_has_mtp: bool = False,
                   bin_dir: str | Path | None = None) -> LaunchPlan:
    """Merge opts with PS1-equivalent auto-fills; return effective opts + env."""
    eff = dict(opts)
    caps = detect_capabilities(bin_dir or _default_bin(cfg))
    notes: list[str] = []

    total_vram = int(gpu_vram_mib or 0)
    free_vram = int(gpu_free_mib or 0)
    small_auto = 0 < total_vram <= 8704
    force = int(cfg.force_8gb) if hasattr(cfg, "force_8gb") else -1
    small = (force == 1) if force in (0, 1) else small_auto

    if force == 0 and small_auto:
        notes.append("force_8gb=off: overriding 8 GB card detection")

    headless = detect_headless(gpu_name) if gpu_name else False
    ram_gib = detect_ram_gib()
    model_size_mb = model_size_gb * 1024

    model_name = Path(model_path).name if model_path else ""
    spec_on = bool(eff.get("use_mtp")) and model_has_mtp
    if spec_on and not caps.has_tier:
        notes.append("MTP requested but tiered-KV unavailable in this binary; drafting may stop at 24k")

    # --- auto CTK / ctx / margin / spec ---
    ctk = eff.get("kv_type")
    if not ctk or ctk == "auto":
        ctk = auto_ctk(caps, total_vram)
        eff["kv_type"] = ctk
        notes.append(f"auto KV type: {ctk}")
    eff["ctk"] = ctk

    ctx = int(eff.get("ctx") or 0)
    if ctx <= 0:
        ctx = auto_ctx(caps, total_vram, ram_gib, model_name, spec_on)
        eff["ctx"] = ctx
        notes.append(f"auto ctx: {ctx}")
    if not eff.get("draft_window"):
        eff["draft_window"] = 16384
    if not eff.get("spec_n_max"):
        eff["spec_n_max"] = auto_spec_n_max(small)
    if not eff.get("spec_deep"):
        eff["spec_deep"] = auto_spec_deep(small, caps.has_replay)

    # --- RS_REPLAY auto ---
    replay_mode = int(getattr(cfg, "rs_replay_mode", -1))
    replay_on = (replay_mode == 1) or (replay_mode == -1 and small and caps.has_replay and spec_on)
    if replay_mode == 1 and not caps.has_replay:
        notes.append("rs_replay=on but binary has no replay rollback; ignored")
        replay_on = False
    eff["_replay_on"] = replay_on

    # --- sparse auto ---
    sparse_mode = int(getattr(cfg, "sparse_mode", -1))
    sparse_page = 0
    sparse_auto = False
    if small and caps.has_sparse and sparse_mode != 0 and ctx > 0:
        if sparse_mode == 1 or (sparse_mode == -1 and caps.has_sparse_auto):
            sparse_auto = (sparse_mode == -1) and caps.has_sparse_auto
            sparse_page = 64

    # --- mmproj ---
    mmproj_path = str(getattr(cfg, "mmproj_path", "") or "")
    mmproj_mib = 0
    if mmproj_path and Path(mmproj_path).is_file():
        mmproj_gpu = bool(getattr(cfg, "mmproj_gpu", False))
        if mmproj_gpu:
            mmproj_mib = int(Path(mmproj_path).stat().st_size / MB)
    else:
        mmproj_path = ""

    # --- ubatch (used by cell formula + -ub arg) ---
    ubatch = int(eff.get("ubatch") or 0)
    if ubatch <= 0:
        if small and spec_on:
            ubatch = 256
        elif small and not spec_on:
            ubatch = 1024
        elif total_vram and total_vram <= 12288:
            ubatch = 256
        else:
            ubatch = 512

    # --- stage_cells (partial staging only on 8 GB) ---
    stage_cells = int(eff.get("stage_cells") or 0)
    if small and not stage_cells:
        stage_cells = 81920
    if not small:
        stage_cells = 0

    # --- packed mask ---
    packed_mask = bool(eff.get("kq_mask_packed"))
    if not packed_mask and (small and spec_on or 12288 < total_vram <= 14336):
        packed_mask = True
    eff["kq_mask_packed"] = packed_mask

    # --- kv_vram_cells ---
    kv_cells = int(eff.get("kv_vram_cells") or 0)
    if kv_cells <= 0 and caps.has_tier and free_vram > 0:
        kv_cells = auto_kv_vram_cells(
            caps=caps, total_vram_mib=total_vram, free_vram_mib=free_vram,
            model_size_mb=model_size_mb, mmproj_mib=mmproj_mib,
            ctx=ctx, ctk=ctk, spec=int(eff.get("spec_n_max") or 0),
            spec_deep=int(eff.get("spec_deep") or 0), small=small,
            headless=headless, model_has_mtp=model_has_mtp,
            ubatch=ubatch, replay_on=replay_on, packed_mask=packed_mask,
            sparse_page=sparse_page, stage_cells=stage_cells,
        )
    if kv_cells >= ctx:
        kv_cells = 0
    if 0 < kv_cells < 16384:
        notes.append(f"tiered-KV line only {kv_cells} cells; consider freeing VRAM")
        kv_cells = 0
    eff["kv_vram_cells"] = kv_cells
    eff["stage_cells"] = stage_cells

    # --- RAM budget ---
    cache_mib = int(eff.get("ram_budget_cache") or 0)
    ckpt = int(eff.get("ram_budget_ckpts") or 0)
    if cache_mib == 0 and ckpt == 0:
        try:
            import psutil
            vm = psutil.virtual_memory()
            commit_free_mib = int(vm.available / MB)
        except Exception:
            commit_free_mib = 0
        kv_tail = int((ctx - kv_cells) * _CELL_BYTES.get(ctk, 34816) / MB) if kv_cells else 0
        cache_auto, ckpt_auto = auto_ram_budget(
            ram_gib, commit_free_mib, int(free_vram or 0), kv_tail)
        if cache_auto is not None:
            eff["ram_budget_cache"] = cache_auto
            eff["ram_budget_ckpts"] = ckpt_auto

    # --- env dict (stale cleared) ---
    env = {k: v for k, v in os.environ.items() if k not in _STALE_ENV}
    for k in list(env.keys()):
        if k.startswith("GGML_CUDA_FA_SPARSE_"):
            env.pop(k, None)

    if cfg.host in ("0.0.0.0", "::", ""):
        listen_host = "0.0.0.0"
    else:
        listen_host = cfg.host
    public_port = int(cfg.port)
    layer_on = bool(getattr(cfg, "layer_enabled", False))
    if layer_on:
        inner = int(getattr(cfg, "layer_inner_port", 0) or 0) or (public_port + 10000)
        listen_host = "127.0.0.1"
        listen_port = inner
    else:
        listen_port = public_port

    if force == 1:
        env["BONSAI_8GB"] = "1"

    if spec_on:
        env["GGML_CUDA_BATCH_INVARIANT"] = "1"
        env.setdefault("LLAMA_MTP_DRAFT_UBATCH", "256")

    if replay_on:
        env["LLAMA_RS_REPLAY"] = "1"

    if eff.get("shared_pool") and spec_on:
        env["GGML_CUDA_SHARED_POOL"] = "1"
        pool = int(eff.get("pool_mib") or 0) or (48 if small else 42)
        env["BONSAI_POOL_MIB"] = str(pool)

    if packed_mask:
        env["LLAMA_ARG_KQ_MASK_PACKED"] = "1"

    if small:
        pf = int(eff.get("prefill_f16") or 0)
        if isinstance(eff.get("prefill_f16"), bool):
            pf = 32768 if eff.get("prefill_f16") and spec_on else (65536 if eff.get("prefill_f16") else 0)
        if pf > 0:
            env["GGML_CUDA_FA_PREFILL_F16"] = str(pf)
        fc = int(eff.get("fa_chunk") or 0)
        if isinstance(eff.get("fa_chunk"), bool):
            fc = 32768 if eff.get("fa_chunk") else 0
        if fc > 0 and "GGML_CUDA_FA_CHUNK" in caps.help_text or True:
            env["GGML_CUDA_FA_CHUNK"] = str(fc)

    if small and stage_cells and caps.has_tier:
        env["BONSAI_STAGE_CELLS"] = str(stage_cells)
        env["GGML_CUDA_KV_TIER_STAGING_FRAC"] = f"{stage_cells / ctx:.6f}" if ctx else "0"

    if sparse_page and caps.has_sparse:
        env["GGML_CUDA_FA_SPARSE"] = "12288,64,1024"
        env.setdefault("GGML_CUDA_FA_SPARSE_FAST", "1")
        env.setdefault("GGML_CUDA_KV_TIER_STAGE_MIN_Q", "9")
        env.setdefault("GGML_CUDA_FA_SPARSE_MIN_HOST",
                       "16384" if sparse_auto else "32768")
        if sparse_auto:
            env["GGML_CUDA_FA_SPARSE_AUTO"] = "1"
        frac = "0.25" if ctk == "q3_0" else "0.125"
        env.setdefault("GGML_CUDA_FA_SPARSE_FRAC", frac)

    if eff.get("ckpt_every") and caps.has_checkpoint:
        env["LLAMA_ARG_CHECKPOINT_EVERY_NT"] = str(int(eff["ckpt_every"]))

    if mmproj_path:
        env["LLAMA_ARG_MMPROJ"] = mmproj_path
        if not getattr(cfg, "mmproj_gpu", False):
            eff["_mmproj_no_offload"] = True

    # --- thinking / harness ---
    effort = str(getattr(cfg, "effort_mode", "medium") or "medium")
    think = bool(eff.get("think", True))
    import json as _json
    kwargs = {"reasoning_effort": effort}
    if not think:
        kwargs["enable_thinking"] = False
    env["LLAMA_ARG_CHAT_TEMPLATE_KWARGS"] = _json.dumps(kwargs)
    if bool(eff.get("harness_proof")) and not caps.has_harness:
        notes.append("harness_proof requested but binary lacks --reasoning-effort-allow")
        eff["harness_proof"] = False

    return LaunchPlan(
        opts=eff, env=env, caps=caps, notes=notes,
        listen_host=listen_host, listen_port=listen_port,
    )


def _default_bin(cfg) -> Path:
    p = Path(cfg.llama_server_exe)
    return p.parent if p.exists() else Path(cfg.project_root) / "bin"
