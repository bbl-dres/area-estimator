"""
pytest setup — adds the python/ source directory to sys.path so test
modules can ``from area import ...``, ``from volume import ...``, etc.
without needing a package install.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_SRC = PROJECT_ROOT / "python"

if str(PYTHON_SRC) not in sys.path:
    sys.path.insert(0, str(PYTHON_SRC))
