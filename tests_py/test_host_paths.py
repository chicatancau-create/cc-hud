from pathlib import Path

from cchud_next.host import safe_capture_path


def test_relative_path_stays_under_artifacts(tmp_path):
    got = safe_capture_path(tmp_path, "shots/a.png")
    assert got == (tmp_path / "artifacts" / "shots" / "a.png").resolve()


def test_absolute_outside_is_clamped(tmp_path):
    got = safe_capture_path(tmp_path, r"C:\Windows\evil.png")
    assert got == (tmp_path / "artifacts" / "capture.png").resolve()


def test_traversal_is_clamped(tmp_path):
    got = safe_capture_path(tmp_path, "../../evil.png")
    assert got.parent == (tmp_path / "artifacts").resolve()
