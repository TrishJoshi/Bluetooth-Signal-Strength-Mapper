"""
Floor plan image processing utilities.

Responsibilities:
- Strip a target color (and similar colors within a tolerance) from an image.
- Composite a measurement grid over a PIL image.
- Convert physical measurements (meters) to pixel coordinates.

All functions are pure (no side effects) — they accept images and return new images.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def strip_color_range(
    image: Image.Image,
    target_rgb: tuple[int, int, int],
    tolerance: int,
) -> Image.Image:
    """
    Replace pixels within `tolerance` of `target_rgb` with white.

    Uses vectorised NumPy operations for performance on large floor plan images.
    Operates in RGB mode; converts and restores RGBA if necessary.
    """
    had_alpha = image.mode == "RGBA"
    working = image.convert("RGBA")
    pixels = np.array(working, dtype=np.int32)

    r, g, b = target_rgb
    color_distance = np.sqrt(
        (pixels[:, :, 0] - r) ** 2
        + (pixels[:, :, 1] - g) ** 2
        + (pixels[:, :, 2] - b) ** 2
    )

    mask = color_distance <= tolerance
    pixels[mask] = [255, 255, 255, 255]

    result = Image.fromarray(pixels.astype(np.uint8), mode="RGBA")
    return result if had_alpha else result.convert("RGB")


def composite_grid(
    image: Image.Image,
    grid_spacing_px: int,
    line_color: str = "#4444FF",
    line_width: int = 1,
    selected_cell: tuple[int, int] | None = None,
    highlight_color: str = "#FF000066",
) -> Image.Image:
    """
    Draw a uniform grid over a copy of `image` and optionally highlight one cell.

    Args:
        image: The background floor plan (PIL Image).
        grid_spacing_px: Pixel distance between grid lines.
        line_color: Hex color string for grid lines.
        line_width: Width of grid lines in pixels.
        selected_cell: (row, col) of the cell to highlight, or None.
        highlight_color: Hex color (with optional alpha) for the selected cell.
    """
    # Work on an RGBA copy so we can paint a semi-transparent highlight.
    result = image.convert("RGBA").copy()
    overlay = Image.new("RGBA", result.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    width, height = result.size

    # Draw vertical grid lines.
    for x in range(0, width + grid_spacing_px, grid_spacing_px):
        draw.line([(x, 0), (x, height)], fill=line_color, width=line_width)

    # Draw horizontal grid lines.
    for y in range(0, height + grid_spacing_px, grid_spacing_px):
        draw.line([(0, y), (width, y)], fill=line_color, width=line_width)

    # Highlight the selected cell with a semi-transparent rectangle.
    if selected_cell is not None:
        row, col = selected_cell
        x0 = col * grid_spacing_px
        y0 = row * grid_spacing_px
        x1 = x0 + grid_spacing_px
        y1 = y0 + grid_spacing_px
        # Parse highlight_color — supports #RRGGBBAA or #RRGGBB.
        fill = _parse_hex_color_with_alpha(highlight_color)
        draw.rectangle([x0, y0, x1, y1], fill=fill)

    result = Image.alpha_composite(result, overlay)
    return result.convert("RGB")


def compute_grid_spacing_px(pixels_per_meter: float, cell_size_meters: float) -> int:
    """Convert a physical cell size to a pixel spacing value."""
    return max(1, int(round(pixels_per_meter * cell_size_meters)))


def cell_from_click(click_x: float, click_y: float, grid_spacing_px: int) -> tuple[int, int]:
    """Map a pixel click coordinate to (row, col) grid indices."""
    col = int(click_x // grid_spacing_px)
    row = int(click_y // grid_spacing_px)
    return row, col


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_hex_color_with_alpha(hex_color: str) -> tuple[int, int, int, int]:
    """Parse #RRGGBB or #RRGGBBAA into an (R, G, B, A) tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        return r, g, b, 120  # Default alpha: ~47% opacity.
    if len(hex_color) == 8:
        r, g, b, a = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4, 6))
        return r, g, b, a
    raise ValueError(f"Unrecognised hex color: #{hex_color}")
