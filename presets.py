"""Preset system: VRAM/speed formulas and built-in tier computation."""
from __future__ import annotations

# --- KV cache bytes per token (per layer, per head) ---
KV_BYTES_PER_TOKEN: dict[str, int] = {
    "q8_0": 34816,
    "q5_0": 22528,
    "q5_1": 24576,
    "q4_0": 18432,
    "q4_1": 20480,
    "iq4_nl": 18432,
    "f16": 65536,
}

# --- Bandwidth estimates by VRAM class (GB/s) ---
BANDWIDTH_BY_VRAM: list[tuple[int, float]] = [
    # (min_vram_mib, bw_gb_s) — checked from highest to lowest
    (24576, 1500.0),   # A100/H100 class (24GB+)
    (16384, 1008.0),   # RTX 4090 (16GB)
    (12288, 504.0),    # RTX 4070 SUPER (12GB)
    (8704, 360.0),     # RTX 3060/4060 class (8-9GB)
    (0, 200.0),        # fallback / low-end
]

# --- Base decode efficiency η by GPU class (card-type dependent).
# Higher-end cards sustain a larger fraction of peak bandwidth during decode
# (more L2 cache, better memory controllers).
EFFICIENCY_BY_VRAM: list[tuple[int, float]] = [
    # (min_vram_mib, eta_base) — checked from highest to lowest
    (24576, 0.80),   # A100/H100 class
    (16384, 0.75),   # RTX 4090
    (12288, 0.70),   # RTX 4070 SUPER
    (8704, 0.65),    # RTX 3060/4060 class
    (0, 0.60),       # fallback / low-end
]

# --- Efficiency factor η for decode phase (bounds) ---
EFFICIENCY_MIN = 0.6
EFFICIENCY_MAX = 0.8


def get_bandwidth(gpu_vram_mib: int) -> float:
    """Return estimated memory bandwidth (GB/s) based on VRAM size."""
    for min_mib, bw in BANDWIDTH_BY_VRAM:
        if gpu_vram_mib >= min_mib:
            return bw
    return 200.0


def get_decode_efficiency(gpu_vram_mib: int) -> float:
    """Return a card-type-dependent base efficiency η for the decode phase.

    Higher-end cards (more L2 cache, better memory controllers) sustain a
    higher fraction of peak bandwidth during decode than low-end ones.
    """
    for min_mib, eta in EFFICIENCY_BY_VRAM:
        if gpu_vram_mib >= min_mib:
            return eta
    return EFFICIENCY_MIN


def compute_peak_vram(model_size_gb: float, context_length: int,
                      kv_type: str) -> int:
    """
    Peak VRAM (MiB) = Model Weight (MiB) + Context × KV Cache Slope

    Args:
        model_size_gb: Model weight in GB (q8_0 ≈ 1 byte/param)
        context_length: Total context window size
        kv_type: KV cache quantization type

    Returns:
        Estimated peak VRAM usage in MiB.
    """
    model_weight_mib = int(model_size_gb * 1024)
    kv_slope = KV_BYTES_PER_TOKEN.get(kv_type, KV_BYTES_PER_TOKEN["q8_0"])
    kv_bytes = context_length * kv_slope
    return model_weight_mib + (kv_bytes // (1024 * 1024))


def compute_tps(model_size_gb: float, gpu_vram_mib: int,
                context_length: int, kv_type: str,
                bandwidth_gb_s: float | None = None) -> float:
    """
    Theoretical tokens/second using memory-bound estimate:

        tps_raw = bw_bytes_s / total_mem_bytes
        depth_factor = empirical correction for attention kernel past ~16k
        tps = tps_raw × efficiency × depth_factor

    Args:
        model_size_gb: Model weight in GB
        gpu_vram_mib: Total GPU VRAM in MiB
        context_length: Context window size
        kv_type: KV cache quantization type
        bandwidth_gb_s: Real GPU bandwidth if known (from get_gpu_bandwidth),
            otherwise falls back to a VRAM-class estimate.

    Returns:
        Estimated decode speed in tokens/second (theoretical).
    """
    bw_gb_s = (bandwidth_gb_s if bandwidth_gb_s is not None
               else get_bandwidth(gpu_vram_mib))

    model_size_bytes = model_size_gb * 1024**3
    kv_slope = KV_BYTES_PER_TOKEN.get(kv_type, KV_BYTES_PER_TOKEN["q8_0"])
    kv_active_bytes = context_length * kv_slope
    total_mem_bytes = model_size_bytes + kv_active_bytes

    if total_mem_bytes <= 0:
        return 0.0

    bw_bytes_s = bw_gb_s * 1024**3
    tps_raw = bw_bytes_s / total_mem_bytes

    # Empirical depth penalty: the pure bandwidth formula overestimates past
    # ~16k because the attention kernel is latency-bound, not bandwidth-bound.
    # Curve fitted to RTX 4070 / q8_0 data in QUALITY.md and RECEIPTS.md.
    depth_factor = 1.0
    if context_length > 16384:
        depth_factor = (16384 / context_length) ** 0.15

    efficiency = get_decode_efficiency(gpu_vram_mib)
    return tps_raw * efficiency * depth_factor


def compute_preset(gpu_vram_mib: int, model_size_gb: float,
                   tier: str) -> dict:
    """
    Compute optimal preset settings for a given GPU VRAM and model size.

    Args:
        gpu_vram_mib: Available GPU VRAM in MiB
        model_size_gb: Model weight in GB
        tier: One of "very_fast", "fast", "mid", "slow", "very_slow"

    Returns:
        dict with keys: context_length, kv_cache_type, ngl, batch_size,
                        estimated_vram_mib, estimated_tps
    """
    # Tier-specific parameters
    tier_params = {
        "very_fast": {"ctx_mult": 0.25, "kv_pref": "q4_0", "eff": EFFICIENCY_MAX},
        "fast":      {"ctx_mult": 1.0,  "kv_pref": "q4_0", "eff": (EFFICIENCY_MIN + EFFICIENCY_MAX) / 2.0},
        "mid":       {"ctx_mult": 2.0,  "kv_pref": "q4_0", "eff": (EFFICIENCY_MIN + EFFICIENCY_MAX) / 2.0},
        "slow":      {"ctx_mult": 4.0,  "kv_pref": "q5_0", "eff": EFFICIENCY_MIN},
        "very_slow": {"ctx_mult": 8.0,  "kv_pref": "q8_0", "eff": EFFICIENCY_MIN},
    }

    params = tier_params.get(tier, tier_params["mid"])
    ctx_mult = params["ctx_mult"]
    kv_type = params["kv_pref"]

    # Base context: fit model + KV into available VRAM with 15% headroom
    usable_vram_mib = int(gpu_vram_mib * 0.85)
    model_weight_mib = int(model_size_gb * 1024)
    remaining_for_kv_mib = max(usable_vram_mib - model_weight_mib, 0)

    kv_slope = KV_BYTES_PER_TOKEN.get(kv_type, KV_BYTES_PER_TOKEN["q8_0"])
    # Max context that fits in remaining VRAM
    max_ctx = remaining_for_kv_mib * 1024 // kv_slope if kv_slope > 0 else 65536

    # Target context: base (32768) × multiplier, capped by what fits
    target_ctx = int(32768 * ctx_mult)
    context_length = min(target_ctx, max(max_ctx, 4096))

    # Round to nearest power of 2 for cleanliness
    if context_length > 0:
        import math as _m
        context_length = 1 << int(_m.log2(context_length))

    ngl = 999  # default: all layers on GPU
    batch_size = 0  # auto

    # Estimate VRAM and speed with chosen settings
    est_vram = compute_peak_vram(model_size_gb, context_length, kv_type)
    est_tps = compute_tps(model_size_gb, gpu_vram_mib, context_length, kv_type)

    return {
        "context_length": context_length,
        "kv_cache_type": kv_type,
        "ngl": ngl,
        "batch_size": batch_size,
        "estimated_vram_mib": est_vram,
        "estimated_tps": round(est_tps, 2),
    }


def get_builtin_presets() -> list[dict]:
    """Return the 5 built-in preset definitions (name + tier)."""
    return [
        {"name": "Very Fast", "tier": "very_fast"},
        {"name": "Fast", "tier": "fast"},
        {"name": "Mid", "tier": "mid"},
        {"name": "Slow", "tier": "slow"},
        {"name": "Very Slow", "tier": "very_slow"},
    ]
