"""Root conftest — fix sys.path so vendored pydantic stubs don't shadow the real package."""

import sys
import os

# The backend/ directory contains vendored pydantic/pydantic_core stubs for Lambda
# packaging. These are pure-Python stubs without the compiled _pydantic_core extension.
# When pytest runs from backend/, '' (cwd) in sys.path picks up these stubs instead
# of the real pydantic from site-packages. Fix by removing the backend dir from path.
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_backend_dir, "src")

# Remove backend dir entries that would shadow site-packages
sys.path = [
    p
    for p in sys.path
    if p == _src_dir  # keep src/
    or "site-packages" in p  # keep venv packages
    or (p and not os.path.samefile(p, _backend_dir) if os.path.isdir(p) and p else True)
]

# Ensure src/ is on the path
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
