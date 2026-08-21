import os
import sys


def resource_path(*parts):
    """Return a path to a bundled resource or a source-tree resource."""
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, *parts)


def writable_path(*parts):
    """Return a path beside the executable for user-editable files."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, *parts)