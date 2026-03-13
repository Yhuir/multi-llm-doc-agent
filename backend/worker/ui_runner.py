"""Launch the Vite UI without relying on a shell wrapper.

This entrypoint is intended for macOS launchd / background startup so the UI
can be started through Python instead of executing a shell script from Desktop.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from backend.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Vite UI server.")
    parser.add_argument("--workspace", default=".", help="Repository root path.")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    settings = load_settings(workspace / ".env")
    ui_dir = workspace / "ui"
    if not ui_dir.exists():
        raise RuntimeError(f"UI directory not found: {ui_dir}")

    env = dict(os.environ)
    api_host = settings.api_host
    if api_host == "0.0.0.0":
        api_host = "127.0.0.1"
    env.setdefault("VITE_API_BASE", f"http://{api_host}:{settings.api_port}")

    npm_path = shutil.which("npm")
    if not npm_path:
        raise RuntimeError("npm not found in PATH.")

    if not (ui_dir / "node_modules").exists():
        subprocess.run([npm_path, "install"], cwd=ui_dir, env=env, check=True)

    # Vite must start inside ui/ so npm resolves ui/package.json instead of the repo root.
    os.chdir(ui_dir)
    env["PWD"] = str(ui_dir)
    os.execvpe(npm_path, [npm_path, "run", "dev", "--", "--host", "0.0.0.0"], env)


if __name__ == "__main__":
    main()
