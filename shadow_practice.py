"""Compatibility launcher for running Shadow Practice from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent / "src"
source_root = str(SOURCE_ROOT)
# Editable installs may already add ``src`` after the script directory. It must
# be first, otherwise this file shadows the ``shadow_practice`` package.
while source_root in sys.path:
    sys.path.remove(source_root)
sys.path.insert(0, source_root)

from shadow_practice.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
