"""Smoke test: Verify package imports."""


def test_import_familylink():
    """Test that familylink package can be imported."""
    import familylink

    assert familylink is not None


def test_import_familylink_client():
    """Test that FamilyLink client can be imported."""
    from familylink import FamilyLink

    assert FamilyLink is not None


def test_import_models():
    """Test that models can be imported."""
    from familylink import models

    assert models is not None
    assert hasattr(models, "App")
    assert hasattr(models, "MembersResponse")
    assert hasattr(models, "AppUsage")


def test_import_cli():
    """Test that CLI module can be imported."""
    from familylink import cli

    assert cli is not None
    assert hasattr(cli, "main")


def test_package_version():
    """Test that package has __all__ defined."""
    from familylink import __all__

    assert "FamilyLink" in __all__
