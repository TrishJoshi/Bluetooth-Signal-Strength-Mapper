"""
Floor plan image processing utilities.

All functions are pure — they accept PIL images and return new images.
No global state, no side effects.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

# Cell-state fill colours (RGBA).
_STATE_COLORS: dict[str, tuple[int, int, int, int]] = {
    "ble": (100, 149, 237, 85),   # Cornflower blue  — BLE measured, no app position.
    "full": (50, 205, 50, 100),   # Lime green        — BLE + app position recorded.
}

_COLOR_SELECTED = (220, 50, 50, 160)     # Red   — true (ground-truth) selected cell.
_COLOR_APP_REPORTED = (255, 200, 0, 140) # Gold  — app-reported position cell.


def strip_color_range(
    image: Image.Image,
    target_rgb: tuple[int, int, int],
    tolerance: int,
) -> Image.Image:
    """
    Replace all pixels within `tolerance` of `target_rgb` with white.

    Uses vectorised NumPy operations for performance on large floor plan images.
    """
    had_alpha = image.mode == "RGBA"
    working = image.convert("RGBA")
    pixels = np.array(working, dtype=np.int32)

    r, g, b = target_rgb
    distance = np.sqrt(
        (pixels[:, :, 0] - r) ** 2
        + (pixels[:, :, 1] - g) ** 2
        + (pixels[:, :, 2] - b) ** 2
    )
    pixels[distance <= tolerance] = [255, 255, 255, 255]

    result = Image.fromarray(pixels.astype(np.uint8), mode="RGBA")
    return result if had_alpha else result.convert("RGB")


def composite_grid(
    image: Image.Image,
    grid_spacing_px: int,
    line_color: str = "#3355BB",
    line_width: int = 1,
    selected_cell: tuple[int, int] | None = None,
    app_reported_cell: tuple[int, int] | None = None,
    cell_states: dict[tuple[int, int], str] | None = None,
    display_scale: float = 1.0,
) -> Image.Image:
    """
    Draw a measurement grid over a copy of `image`.

    Layers (bottom to top):
      1. Cell-state colour fills  (blue = BLE only, green = BLE + app location)
      2. App-reported position    (gold highlight)
      3. True selected position   (red highlight)
      4. Grid lines

    Args:
        image: Background floor plan.
        grid_spacing_px: Grid cell size in source-image pixels.
        line_color: Hex colour for grid lines.
        line_width: Grid line width in pixels.
        selected_cell: (row, col) of the true/ground-truth selected cell.
        app_reported_cell: (row, col) of the app-reported position cell.
        cell_states: Mapping of (row, col) → "ble" | "full".
        display_scale: Final resize multiplier (zoom). 1.0 = original size.
    """
    result = image.convert("RGBA").copy()
    overlay = Image.new("RGBA", result.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    w, h = result.size

    # --- Layer 1: cell-state fills ---
    if cell_states:
        for (row, col), state in cell_states.items():
            color = _STATE_COLORS.get(state)
            if color:
                _fill_cell(draw, row, col, grid_spacing_px, color)

    # --- Layer 2: app-reported highlight ---
    if app_reported_cell is not None:
        _fill_cell(draw, *app_reported_cell, grid_spacing_px, _COLOR_APP_REPORTED)

    # --- Layer 3: true selected cell highlight ---
    if selected_cell is not None:
        _fill_cell(draw, *selected_cell, grid_spacing_px, _COLOR_SELECTED)

    # --- Layer 4: grid lines ---
    for x in range(0, w + grid_spacing_px, grid_spacing_px):
        draw.line([(x, 0), (x, h)], fill=line_color, width=line_width)
    for y in range(0, h + grid_spacing_px, grid_spacing_px):
        draw.line([(0, y), (w, y)], fill=line_color, width=line_width)

    result = Image.alpha_composite(result, overlay).convert("RGB")

    # --- Layer 5: display zoom resize ---
    if display_scale != 1.0:
        new_w = max(1, int(result.width * display_scale))
        new_h = max(1, int(result.height * display_scale))
        result = result.resize((new_w, new_h), Image.LANCZOS)

    return result


def compute_grid_spacing_px(pixels_per_meter: float, cell_size_meters: float) -> int:
    """Convert a physical cell size to a pixel spacing value. Minimum 2px."""
    return max(2, int(round(pixels_per_meter * cell_size_meters)))


def cell_from_click(click_x: float, click_y: float, grid_spacing_px: int) -> tuple[int, int]:
    """Map a pixel click coordinate (original image space) to (row, col) grid indices."""
    col = int(click_x // grid_spacing_px)
    row = int(click_y // grid_spacing_px)
    return row, col


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fill_cell(
    draw: ImageDraw.ImageDraw,
    row: int,
    col: int,
    spacing: int,
    color: tuple[int, int, int, int],
) -> None:
    x0, y0 = col * spacing, row * spacing
    draw.rectangle([x0, y0, x0 + spacing, y0 + spacing], fill=color)
