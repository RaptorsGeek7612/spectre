"""`python -m spectre.web`: same as `spectre-web` (useful where .exe shims are blocked)."""

import sys

from spectre.web.server import main

sys.exit(main())
