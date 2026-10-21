"""Frozen GUI entrypoint: initialize paths before importing the application."""
import multiprocessing
import os
import sys


def run():
    multiprocessing.freeze_support()
    try:
        from app_paths import initialize_user_data, writable_path
        initialize_user_data()
        import logging
        logging.basicConfig(filename=writable_path("logs", "desktop.log"), level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        from app_runtime import register_process
        register_process("GUI")
        if "--self-test" in sys.argv:
            from distribution_smoke import desktop_smoke
            return desktop_smoke(sys.argv)
        import main
        return main.main()
    except Exception as exc:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), "Semáforo IA - Error de inicio", 0x10)
        elif sys.stderr is not None:
            print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
