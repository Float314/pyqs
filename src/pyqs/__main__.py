"""Allow ``python -m pyqs`` to work the same as the ``pyqs`` console script."""

from __future__ import annotations

import sys

from pyqs.cli import main

if __name__ == "__main__":
    sys.exit(main())
