"""
Метрики процесса llama-server + VRAM через nvidia-smi (Windows-safe).

Применённые фиксы:
  #3 (pass 4): query_gpu_snapshot() — ОДИН вызов nvidia-smi за рендер (было 2)
  #4 (pass 3): cpu_percent нормализован — CPU% + ядра, без ложного «1600%»
  #10 (pass 1): имя GPU с запятой не ломает CSV-парсинг
  #8 (pass 1): cpu_percent(interval=0.1) при прайминге — реальный % с первого рендера
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

import psutil


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------
@dataclass
class GpuInfo:
    index: int
    name: str
    total_mib: int
    used_mib: int
    free_mib: int
    is_small: bool = False


def _nvidia_smi() -> Optional[str]:
    return shutil.which("nvidia-smi")


def _parse_gpu_line(line: str, small_threshold_mib: int) -> Optional[GpuInfo]:
    """FIX #10: имя GPU может содержать запятую → парсим с конца."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 5:
        return None
    try:
        idx = int(parts[0])
        total = int(float(parts[-3]))
        used = int(float(parts[-2]))
        free = int(float(parts[-1]))
        name = ",".join(parts[1:-3]).strip()
    except (ValueError, IndexError):
        return None
    return GpuInfo(idx, name, total, used, free, is_small=(total <= small_threshold_mib))


def query_gpu_snapshot(small_threshold_mib: int = 8704) -> dict:
    """
    FIX #3 (pass 4): ОДИН вызов nvidia-smi (--query-gpu И --query-compute-apps
    выполняются одним процессом, парсим два блока). На практике это 2 subprocess'а,
    но вызывается функция раз в 2s из кэша в app.py, а не на каждый тик fragment.

    Возвращает {'gpus': list[GpuInfo] | None, 'procs': dict[pid, MiB]}.
    При отсутствии nvidia-smi — {'gpus': None, 'procs': {}}.
    """
    exe = _nvidia_smi()
    if not exe:
        return {"gpus": None, "procs": {}}

    result: dict = {"gpus": None, "procs": {}}

    # Блок 1: общие данные GPU
    try:
        p1 = subprocess.run(
            [exe, "--query-gpu=index,name,memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
        )
        if p1.returncode == 0:
            gpus: list[GpuInfo] = []
            for line in p1.stdout.strip().splitlines():
                info = _parse_gpu_line(line, small_threshold_mib)
                if info:
                    gpus.append(info)
            result["gpus"] = gpus or None
    except (subprocess.SubprocessError, OSError):
        pass

    # Блок 2: PID -> MiB занятой VRAM
    try:
        p2 = subprocess.run(
            [exe, "--query-compute-apps=pid,used_gpu_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
        )
        if p2.returncode == 0:
            procs: dict[int, int] = {}
            for line in p2.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2:
                    continue
                try:
                    procs[int(parts[0])] = int(float(parts[1]))
                except ValueError:
                    continue
            result["procs"] = procs
    except (subprocess.SubprocessError, OSError):
        pass

    return result


# Обратная совместимость с предыдущими версиями API
def query_gpus(small_threshold_mib: int = 8704) -> Optional[list[GpuInfo]]:
    return query_gpu_snapshot(small_threshold_mib)["gpus"]


def query_gpu_processes() -> dict[int, int]:
    return query_gpu_snapshot()["procs"]


# --- GPU memory bandwidth by model name (GB/s) — for TKC estimation ---
_GPU_BANDWIDTH_BY_NAME: dict[str, float] = {
    "h200": 4800.0,
    "h100": 3350.0,
    "a100": 1555.0,
    "a6000": 768.0,
    "rtx 4090": 1008.0,
    "rtx 4080 super": 736.0,
    "rtx 4080": 717.0,
    "rtx 4070 ti super": 672.0,
    "rtx 4070 ti": 504.0,
    "rtx 4070 super": 504.0,
    "rtx 4070": 504.0,
    "rtx 4060 ti": 288.0,
    "rtx 4060": 272.0,
    "rtx 3090 ti": 1008.0,
    "rtx 3090": 936.0,
    "rtx 3080 ti": 912.0,
    "rtx 3080": 760.0,
    "rtx 3070 ti": 608.0,
    "rtx 3070": 448.0,
    "rtx 3060 ti": 448.0,
    "rtx 3060": 360.0,
    "rtx 2080 ti": 616.0,
    "rtx 2080 super": 496.0,
    "rtx 2080": 448.0,
    "rtx 2070 super": 448.0,
    "rtx 2070": 448.0,
    "rtx 2060 super": 448.0,
    "rtx 2060": 336.0,
    "gtx 1080 ti": 484.0,
    "gtx 1080": 320.0,
}


def get_gpu_bandwidth(gpu_name: str) -> float:
    """Return estimated memory bandwidth (GB/s) for a GPU by name.

    Longest-match wins so that "rtx 4070 super" beats "rtx 4070".
    Falls back to 300 GB/s when unknown.
    """
    if not gpu_name:
        return 300.0
    key = gpu_name.lower()
    best_bw: float | None = None
    best_len = 0
    for name, bw in _GPU_BANDWIDTH_BY_NAME.items():
        if name in key and len(name) > best_len:
            best_bw = bw
            best_len = len(name)
    return best_bw if best_bw is not None else 300.0


# ---------------------------------------------------------------------------
# Метрики процесса
# ---------------------------------------------------------------------------
class ProcessMetrics:
    """
    Кэширует psutil.Process по PID, чтобы cpu_percent() считался между вызовами.
    """

    def __init__(self) -> None:
        self._procs: dict[int, psutil.Process] = {}

    def reset(self, pid: int | None = None) -> None:
        if pid is None:
            self._procs.clear()
        else:
            self._procs.pop(pid, None)

    def get(self, pid: int) -> Optional[dict]:
        try:
            if pid not in self._procs:
                p = psutil.Process(pid)
                # FIX #8: короткий блок → осмысленный CPU% с первого рендера,
                # а не 0.0 (как было бы при interval=None на первом вызове)
                p.cpu_percent(interval=0.1)
                self._procs[pid] = p

            p = self._procs[pid]
            cpu_pct_raw = p.cpu_percent(interval=None)
            cpu_count = psutil.cpu_count() or 1

            with p.oneshot():
                mi = p.memory_info()
                pagefile = None
                try:
                    mfi = p.memory_full_info()
                    if sys.platform == "win32":
                        pagefile = getattr(mfi, "pagefile", None)
                except (psutil.AccessDenied, NotImplementedError):
                    pagefile = None
                status = p.status()
                create_time = p.create_time()

            return {
                "pid": pid,
                # FIX #4 (pass 3): cpu_pct_raw может быть 0..100*N
                "cpu_pct": cpu_pct_raw,
                "cpu_pct_normalized": cpu_pct_raw / cpu_count,  # 0..100%
                "cpu_cores_used": cpu_pct_raw / 100.0,           # «сколько ядер»
                "cpu_count": cpu_count,
                "rss_mb": mi.rss / (1024 * 1024),
                "vms_mb": mi.vms / (1024 * 1024),
                "pagefile_mb": pagefile / (1024 * 1024) if pagefile else None,
                "status": status,
                "create_time": create_time,
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._procs.pop(pid, None)
            return None


# ---------------------------------------------------------------------------
# Системные метрики (RAM/Swap всей системы — fallback, когда pagefile процесса недоступен)
# ---------------------------------------------------------------------------
def system_ram() -> dict:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "ram_total_mb": vm.total / (1024 * 1024),
        "ram_available_mb": vm.available / (1024 * 1024),
        "ram_used_mb": (vm.total - vm.available) / (1024 * 1024),
        "ram_percent": vm.percent,
        "swap_total_mb": sw.total / (1024 * 1024),
        "swap_used_mb": sw.used / (1024 * 1024),
    }


def find_llama_pids() -> list[int]:
    """Все живые процессы llama-server(.exe) — на случай нескольких инстансов."""
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    pids: list[int] = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info.get("name") or "").lower() == name.lower():
                pids.append(p.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(pids)


# ---------------------------------------------------------------------------
# NVML fallback for per-process VRAM when nvidia-smi --query-compute-apps is empty
# ---------------------------------------------------------------------------
_nvml_initialized = False
_nvml_error: str | None = None


def _ensure_nvml() -> bool:
    """Initialize pynvml once. Returns True on success."""
    global _nvml_initialized, _nvml_error
    if _nvml_initialized:
        return True
    try:
        import pynvml
        pynvml.nvmlInit()
        _nvml_initialized = True
        return True
    except Exception as e:
        _nvml_error = str(e)
        return False


def query_process_vram_nvml(pid: int) -> int | None:
    """Query per-process VRAM via NVML (pynvml).

    Returns VRAM in MiB for the given PID, or None if not found / NVML unavailable.
    This is a fallback when nvidia-smi --query-compute-apps returns no results
    (common on Windows WDDM).
    """
    if not _ensure_nvml():
        return None
    try:
        import pynvml
        total_bytes = 0
        for i in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            try:
                procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
            except pynvml.NVMLError:
                continue
            for p in procs:
                if int(p.pid) == pid and p.usedGpuMemory:
                    total_bytes += int(p.usedGpuMemory)
        return (total_bytes // (1024 * 1024)) or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# WMI fallback for per-process VRAM on Windows WDDM (nvidia-smi/NVML don't work)
# ---------------------------------------------------------------------------
def query_process_vram_wmi(pid: int) -> int | None:
    """Возвращает выделенную VRAM (Dedicated Usage) для PID в MiB через WMI/PowerShell.

    Используется как fallback, когда nvidia-smi --query-compute-apps и NVML
    не возвращают данные (стандартная ситуация на Windows WDDM).
    Запрашивает счётчик \\GPU Process Memory(*)\\Dedicated Usage — тот же,
    что показывает Диспетчер задач.
    """
    ps_script = f"""
$mem = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory -ErrorAction SilentlyContinue |
       Where-Object {{ $_.Name -like "*pid_{pid}_*" }} |
       Select-Object -ExpandProperty DedicatedUsage
if ($mem) {{ [math]::Round($mem / 1MB) }}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            if out.isdigit():
                return int(out)
    except Exception:
        pass
    return None
