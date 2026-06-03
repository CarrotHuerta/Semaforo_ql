import os
import platform
import subprocess
import sys
from functools import lru_cache


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


def _run_powershell(command):
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
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
        cpu_name = _run_powershell(
            "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)"
        )
        if cpu_name:
            info["cpu"] = cpu_name

        gpu_names = _run_powershell(
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"
        )
        if gpu_names:
            info["gpu"] = " / ".join(
                [line.strip() for line in gpu_names.splitlines() if line.strip()]
            )

        ram_bytes = _run_powershell(
            "(Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty TotalPhysicalMemory)"
        )
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
