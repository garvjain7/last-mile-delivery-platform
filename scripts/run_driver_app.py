"""Run the Core API and Driver Gateway together for local Driver App development."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICES = (
    (
        "Core API",
        "services.core_api.app.main:app",
        "8000",
    ),
    (
        "Driver Gateway",
        "services.driver_gateway.app.main:app",
        "8002",
    ),
)


def stop_services(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    for name, process in processes:
        if process.poll() is None:
            print(f"Stopping {name}...", flush=True)
            process.terminate()

    for _, process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        for name, app, port in SERVICES:
            command = [
                sys.executable,
                "-m",
                "uvicorn",
                app,
                "--host",
                "127.0.0.1",
                "--port",
                port,
            ]
            print(f"Starting {name} on port {port}...", flush=True)
            processes.append((name, subprocess.Popen(command, cwd=REPOSITORY_ROOT)))

        print("Open http://127.0.0.1:8000/driver. Press Ctrl+C to stop.", flush=True)
        while True:
            for name, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    print(f"{name} exited with code {exit_code}.", file=sys.stderr, flush=True)
                    return exit_code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping Driver App services...", flush=True)
        return 0
    finally:
        stop_services(processes)


if __name__ == "__main__":
    raise SystemExit(main())
