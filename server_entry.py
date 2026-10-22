"""Explicit, optional foreground server. Never installed as a service."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from app_runtime import register_process
    register_process("Server")
    from server import run
    run()
