import pytest

from cchud_next.win32 import compute_placement


def test_second_monitor_top_right():
    areas = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]
    assert compute_placement(areas, 400, 300, 1, "top-right", 16) == (3424, 16)


def test_bottom_right_clamps_into_work_area():
    areas = [(0, 0, 1920, 1080)]
    x, y = compute_placement(areas, 400, 300, 0, "bottom-right", 16)
    assert (x, y) == (1504, 764)


def test_oversize_window_is_clamped_to_left_top():
    areas = [(1920, 0, 3840, 1080)]
    assert compute_placement(areas, 4000, 2000, 0, "top-right", 16) == (1920, 0)


def test_monitor_index_out_of_range_uses_last():
    areas = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]
    assert compute_placement(areas, 400, 300, 9, "top-right", 16) == (3424, 16)


def test_empty_work_areas_raises():
    with pytest.raises(ValueError):
        compute_placement([], 100, 100)


def test_random_work_areas_never_leave_the_target_monitor():
    import random

    rnd = random.Random(20261108)
    for _ in range(500):
        l = rnd.randint(-3840, 3840)
        t = rnd.randint(-2160, 2160)
        r = l + rnd.randint(320, 3840)
        b = t + rnd.randint(240, 2160)
        w = rnd.randint(120, 2600)
        h = rnd.randint(100, 1800)
        mon = rnd.randint(-2, 2)
        anchor = rnd.choice(["top-right", "top-left", "bottom-right", "bottom-left"])
        margin = rnd.randint(0, 40)
        areas = [(l, t, r, b), (l + 5000, t, r + 5000, b)]
        x, y = compute_placement(areas, w, h, mon, anchor, margin)
        L, T, R, B = areas[min(max(0, mon), len(areas) - 1)]
        assert isinstance(x, int) and isinstance(y, int)
        assert L <= x <= max(L, R - w - 4)
        assert T <= y <= max(T, B - h - 4)
        assert x + min(w, R - L) <= R
        assert y + min(h, B - T) <= B
