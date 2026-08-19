"""Tests for custom theme persistence and image safety."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from caelus.theme_manager import THEME_PALETTES, ThemeManager, ThemeValidationError, is_custom_theme_selection


def image_bytes(*, size=(640, 360), color="#78a889", image_format="PNG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, image_format)
    return output.getvalue()


def test_create_resolve_and_delete_custom_theme(tmp_path) -> None:
    manager = ThemeManager(tmp_path)
    theme = manager.create_theme(name="My Garden", images=[
        {"name": "Morning", "palette": "pale_sage", "content": image_bytes()},
        {"name": "Evening", "palette": "pale_sky", "content": image_bytes(color="#577698")},
    ])

    assert len(theme["images"]) == 2
    selection = theme["images"][0]["selection"]
    assert is_custom_theme_selection(selection)
    assert manager.resolve(selection)["image"]["name"] == "Morning"
    assert manager.style_values(selection)["--scene-image"].startswith("url('/theme-assets/")
    with Image.open(manager.assets_dir / theme["id"] / f"{theme['images'][0]['id']}.webp") as processed:
        assert processed.size == (1920, 1080)
        assert processed.format == "WEBP"

    assert manager.delete_theme(theme["id"]) is True
    assert manager.resolve(selection) is None
    assert not (manager.assets_dir / theme["id"]).exists()


def test_custom_theme_validation_and_manifest_recovery(tmp_path) -> None:
    manager = ThemeManager(tmp_path)
    valid = {"name": "Garden", "palette": "pale_sage", "content": image_bytes()}
    with pytest.raises(ThemeValidationError, match="between one and five"):
        manager.create_theme(name="Empty", images=[])
    with pytest.raises(ThemeValidationError, match="predefined palettes"):
        manager.create_theme(name="Bad palette", images=[{**valid, "palette": "#000"}])
    with pytest.raises(ThemeValidationError, match="valid WebP"):
        manager.create_theme(name="Bad image", images=[{**valid, "content": b"not an image"}])
    with pytest.raises(ThemeValidationError, match="at least 320"):
        manager.create_theme(name="Tiny", images=[{**valid, "content": image_bytes(size=(100, 100))}])
    with pytest.raises(ThemeValidationError, match="ID is invalid"):
        manager.delete_theme("../outside")

    first = manager.create_theme(name="First", images=[valid])
    manager.create_theme(name="Second", images=[valid])
    manager.manifest_path.write_text("{broken", encoding="utf-8")
    assert [theme["id"] for theme in manager.list_themes()] == [first["id"]]


def test_palettes_have_expected_safe_contract() -> None:
    required = {"panel", "strong", "soft", "border", "text", "muted", "accent"}
    assert len(THEME_PALETTES) == 8
    assert all(required <= set(palette) for palette in THEME_PALETTES.values())
