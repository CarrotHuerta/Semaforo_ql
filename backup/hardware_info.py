import json
import os
import platform
import subprocess
import sys
from functools import lru_cache

# One combined PowerShell query instead of 3 separate processes: each
# powershell.exe spawn has a fixed startup cost, so batching cuts detection
# time roughly to a third and avoids blocking the UI for as long.
_PS_COMMAND = (
    "$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name; "
    "$gpu = Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name; "
    "$ram = Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty TotalPhysicalMemory; "
    "@{cpu=$cpu; gpu=@($gpu); ram=$ram} | ConvertTo-Json -Compress"
)

_STARTUPINFO = None
if sys.platform.startswith("win"):
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW


def _format_bytes(value):
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "No detectado"

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _run_powershell(command, timeout=8):
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            startupinfo=_STARTUPINFO,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def _detect_hardware():
    info = {
        "cpu": "No detectado",
        "gpu": "No detectado",
        "ram": "No detectado",
        "os": "No detectado",
    }

    info["os"] = platform.platform() or f"{platform.system()} {platform.release()}"

    if sys.platform.startswith("win"):
        raw = _run_powershell(_PS_COMMAND)
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}

        cpu_name = data.get("cpu")
        if cpu_name:
            info["cpu"] = cpu_name

        gpu_names = data.get("gpu")
        if isinstance(gpu_names, str):
            gpu_names = [gpu_names]
        if gpu_names:
            info["gpu"] = " / ".join(
                [str(name).strip() for name in gpu_names if str(name).strip()]
            )

        ram_bytes = data.get("ram")
        if ram_bytes:
            info["ram"] = _format_bytes(ram_bytes)
    else:
        cpu_name = platform.processor() or platform.machine()
        if cpu_name:
            info["cpu"] = cpu_name

        if hasattr(os, "sysconf"):
            try:
                pages = os.sysconf("SC_PHYS_PAGES")
                page_size = os.sysconf("SC_PAGE_SIZE")
                info["ram"] = _format_bytes(pages * page_size)
            except (ValueError, OSError, AttributeError):
                pass

    return info


@lru_cache(maxsize=1)
def get_hardware_info():
    return _detect_hardware()
