import os
import sys


def resource_path(*parts):
    """Return a path to a bundled resource or a source-tree resource."""
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, *parts)


def ensure_parent_dir(path):
    """Create the parent directory for any user-writable file if it does not exist."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    return path


def writable_path(*parts):
    """Return a path beside the executable for user-editable files."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, *parts)
    return ensure_parent_dir(path)