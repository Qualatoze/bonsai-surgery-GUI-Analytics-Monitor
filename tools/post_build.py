"""Post-build script: prepares the dist/ folder for distribution.

Creates required runtime folders next to the .exe and copies
llama-server.exe (and its DLLs) from the sibling 'bonsai surgery' directory.

IMPORTANT: Never copies developer artifacts (api_key.txt, stats.db, settings.json).
"""

import os
import shutil
import sys
from pathlib import Path


def main() -> None:
    dist_dir = Path(os.environ.get("BONSAI_DIST", "dist/Bonsai")).resolve()
    exe_name = os.environ.get("BONSAI_APP_NAME", "Bonsai") + ".exe"

    if not dist_dir.exists():
        sys.exit(f"[post_build] Dist dir not found: {dist_dir}")

    exe_path = dist_dir / exe_name
    if not exe_path.exists():
        sys.exit(f"[post_build] Executable not found: {exe_path}")

    print(f"[post_build] Target: {dist_dir}")

    # ------------------------------------------------------------------
    # Required runtime folders next to the .exe
    # ------------------------------------------------------------------
    for rel in ["artifacts", "artifacts/logs", "modules"]:
        target = dist_dir / rel
        target.mkdir(parents=True, exist_ok=True)
        print(f"[post_build] Ensured folder: {target}")

    # ------------------------------------------------------------------
    # Copy llama-server.exe + CUDA/ggml DLLs from sibling directory
    # ------------------------------------------------------------------
    project_root = Path(__file__).resolve().parent.parent  # bonsai GUI/
    src_bin = project_root.parent / "bonsai surgery" / "bin"

    if src_bin.is_dir():
        dst_bin = dist_dir / "bin"
        dst_bin.mkdir(parents=True, exist_ok=True)

        # Copy llama-server.exe specifically
        llama_exe = src_bin / "llama-server.exe"
        if llama_exe.is_file():
            shutil.copy2(llama_exe, dst_bin / llama_exe.name)
            print(f"[post_build] Copied {llama_exe} -> {dst_bin / llama_exe.name}")

        # Copy all DLLs (CUDA, ggml, llama-common, etc.)
        for dll in src_bin.glob("*.dll"):
            shutil.copy2(dll, dst_bin / dll.name)
            print(f"[post_build] Copied {dll.name} -> bin/")

        # Copy cloudflared.exe if present (used for LAN tunneling)
        cf = src_bin / "cloudflared.exe"
        if cf.is_file():
            shutil.copy2(cf, dst_bin / cf.name)
            print(f"[post_build] Copied {cf} -> bin/")

    else:
        print("[post_build] No sibling 'bonsai surgery/bin' found; skipping server copy")

    # ------------------------------------------------------------------
    # Safety check: ensure no secrets leaked into dist
    # ------------------------------------------------------------------
    forbidden = ["api_key.txt", "stats.db"]
    for f in forbidden:
        if (dist_dir / f).exists():
            print(f"[post_build] WARNING: {f} found in dist — removing")
            (dist_dir / f).unlink()

    # Check artifacts/ subfolder too
    for f in forbidden:
        art = dist_dir / "artifacts" / f
        if art.exists():
            print(f"[post_build] WARNING: {f} found in dist/artifacts — removing")
            art.unlink()

    print("[post_build] Done. No secrets copied.")


if __name__ == "__main__":
    main()
