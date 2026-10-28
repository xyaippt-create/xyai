from __future__ import annotations

# Stable compatibility entry point. The fail-closed implementation is separated
# so unit tests and the build script use the same scanner without duplicating rules.
from package_data_gate_core import (  # noqa: F401
    APP_EXE_NAME,
    ArchiveBudget,
    PackageDataLeakError,
    build_parser,
    main,
    scan_app_tree,
    scan_pyinstaller_archives,
    scan_zip_archive,
)


if __name__ == "__main__":
    raise SystemExit(main())
