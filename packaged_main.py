import sys

from runtime.packaged_launcher import main, write_startup_error


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        from runtime.error_dialog import show_error_dialog

        write_startup_error(exc)
        show_error_dialog("影界 HDDE 启动失败", str(exc))
        raise SystemExit(1) from exc
