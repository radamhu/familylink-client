"""Smoke test: Verify CLI help command."""

import subprocess
import sys


def test_cli_help_command():
    """Test that CLI --help command works."""
    result = subprocess.run(
        [sys.executable, "-m", "familylink.cli", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout.lower() or "Family Link" in result.stdout


def test_cli_version_import():
    """Test that CLI can be imported without errors."""
    from familylink.cli import main

    assert callable(main)


def test_cli_module_execution():
    """Test that familylink.cli module can be executed."""
    result = subprocess.run(
        [sys.executable, "-c", "import familylink.cli"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == "" or "warning" in result.stderr.lower()
