"""Re-export cross-platform compat module for hooks/ consumers."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.compat import *  # noqa: F401,F403
