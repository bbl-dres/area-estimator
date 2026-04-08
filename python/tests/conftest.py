"""
pytest setup — adds the python/ source directory to sys.path so test
modules can ``from area import ...``, ``from volume import ...``, etc.
without needing a package install.

This file lives at python/tests/conftest.py, so its parent directory
(python/) is exactly the source root we need on sys.path.
"""
import sys
from pathlib import Path

PYTHON_SRC = Path(__file__).resolve().parent.parent

if str(PYTHON_SRC) not in sys.path:
    sys.path.insert(0, str(PYTHON_SRC))
