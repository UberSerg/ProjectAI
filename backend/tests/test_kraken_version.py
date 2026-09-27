"""Product version source of truth stays consistent across packages."""

from pathlib import Path

from app import __version__


def test_backend_version_matches_release() -> None:
    assert __version__ == "1.0.0"
    candidates = [
        Path(__file__).resolve().parents[2] / "VERSION",  # repo root (CI / local)
        Path("/VERSION"),  # optional compose mount
    ]
    for path in candidates:
        if path.is_file():
            assert path.read_text(encoding="utf-8").strip() == __version__
            return
