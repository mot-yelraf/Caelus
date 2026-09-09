"""Render Android PNG assets from the existing vector logo using Playwright."""

from pathlib import Path
from xml.etree import ElementTree as ET

from playwright.sync_api import sync_playwright


ICONS = Path(__file__).resolve().parents[1] / "static" / "icons"
SVG_NS = "http://www.w3.org/2000/svg"


def maskable_svg(source: str) -> str:
    """Give the logo an opaque background and fit it inside the 40% safe radius."""
    ET.register_namespace("", SVG_NS)
    root = ET.fromstring(source)
    artwork = root.find(f"{{{SVG_NS}}}g")
    assert artwork is not None
    background = artwork.find(f"{{{SVG_NS}}}rect")
    assert background is not None
    artwork.remove(background)
    root.remove(artwork)
    ET.SubElement(root, f"{{{SVG_NS}}}rect", {
        "width": "512", "height": "512", "fill": "url(#background)",
    })
    # Scale the foreground about its center; the background always reaches the edge.
    padded = ET.SubElement(root, f"{{{SVG_NS}}}g", {
        "transform": "translate(76.8 76.8) scale(0.7)",
    })
    padded.append(artwork)
    return ET.tostring(root, encoding="unicode")


def main() -> None:
    """Regenerate the standard and maskable Android icons with headless Chromium."""
    source = (ICONS / "caelus-weather-compass.svg").read_text(encoding="utf-8")
    variants = [
        ("caelus-android-192.png", 192, source),
        ("caelus-android-512.png", 512, source),
        ("caelus-android-maskable-512.png", 512, maskable_svg(source)),
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(device_scale_factor=1)
            for filename, size, svg in variants:
                page.set_viewport_size({"width": size, "height": size})
                page.set_content(
                    "<style>html,body{margin:0}svg{display:block;width:100vw;height:100vh}</style>"
                    + svg
                )
                page.screenshot(path=str(ICONS / filename), omit_background=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
