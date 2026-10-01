import sys
from pathlib import Path

# The worker is a flat set of modules (02 §5), not a package.
# Appended, not prepended: prepending would shadow apps/api/tests as the `tests` package.
sys.path.append(str(Path(__file__).resolve().parents[1]))
