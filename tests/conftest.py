"""Root pytest configuration."""

import sys
from pathlib import Path

# Add project root to path so that 'scripts' module is importable
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
