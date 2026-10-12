"""Desktop sidecar and its bundled offline adapter dependencies."""

import os
import sys
from pathlib import Path

if os.environ.get("FACTUMDB_BUNDLE_ROOT"):
    packages = Path(os.environ["FACTUMDB_BUNDLE_ROOT"]) / "python-packages"
    if packages.is_dir():
        sys.path.insert(0, str(packages))
