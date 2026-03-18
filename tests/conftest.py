import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture
def tmp_config(tmp_path):
    """Create a temporary config directory with minimal setup."""
    conf_dir = tmp_path / "gniza"
    conf_dir.mkdir()
    (conf_dir / "targets.d").mkdir()
    (conf_dir / "remotes.d").mkdir()
    (conf_dir / "schedules.d").mkdir()

    gniza_conf = conf_dir / "gniza.conf"
    gniza_conf.write_text('WEB_API_KEY="testkey123"\nRETENTION_COUNT="30"\n')

    # Patch CONFIG_DIR in both lib.config and tui.config (tui re-exports lib)
    import lib.config
    original = lib.config.CONFIG_DIR
    lib.config.CONFIG_DIR = conf_dir
    try:
        import tui.config as tui_config
        tui_config.CONFIG_DIR = conf_dir
    except ImportError:
        pass
    yield conf_dir
    lib.config.CONFIG_DIR = original
    try:
        import tui.config as tui_config
        tui_config.CONFIG_DIR = original
    except ImportError:
        pass
