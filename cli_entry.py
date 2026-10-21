import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from app_runtime import register_process
    register_process("CLI")
    from cli import main
    raise SystemExit(main())
