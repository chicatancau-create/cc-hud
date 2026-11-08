"""托盘像素判据：隐藏区图标被调暗后仍须能识别，背景/异色不得误判。"""
from PIL import Image
from tools.tray_pixel import green_pixels


def _img(colors):
    im = Image.new("RGB", (len(colors), 1))
    im.putdata(colors)
    return im


def test_dim_green_counts() -> None:
    assert green_pixels(_img([(0, 96, 60), (0, 131, 81), (52, 211, 153)])) == 3


def test_black_and_red_do_not_count() -> None:
    assert green_pixels(_img([(0, 0, 0), (255, 0, 0), (255, 255, 255)])) == 0


def test_low_saturation_green_ignored() -> None:
    assert green_pixels(_img([(60, 70, 65), (120, 140, 130)])) == 0
