"""Check readable text on both surfaces of every bundled theme."""
from pathlib import Path
import re

import pytest

from caelus.theme_manager import THEME_PALETTES


def contrast(first: str, second: str) -> float:
    """Calculate the relative-luminance contrast ratio of two RGB hex colors."""
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize('theme', ['garden', 'island', 'river', 'desert'])
def test_bundled_surface_text_contrast(theme):
    css = (Path(__file__).resolve().parents[1] / 'static/styles.css').read_text()
    rule = re.search(r'\.theme-' + theme + r', \.theme-swatch-' + theme + r'\s*\{([^}]+)', css).group(1)
    colors = dict(re.findall(r'--surface-(\w+): (#[\da-f]{6});', rule))
    for background in ('light', 'tint'):
        for foreground in ('ink', 'muted', 'accent'):
            assert contrast(colors[foreground], colors[background]) >= 4.5, (theme, foreground, background)
    assert contrast('#ffffff', colors['accent']) >= 4.5


@pytest.mark.parametrize('palette', THEME_PALETTES.values(), ids=THEME_PALETTES.keys())
def test_custom_surface_text_contrast(palette):
    for background in ('strong', 'panel'):
        for foreground in ('text', 'muted', 'accent'):
            assert contrast(palette[foreground], palette[background]) >= 4.5
