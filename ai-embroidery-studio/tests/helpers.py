from pathlib import Path

import pyembroidery as pe


def make_pattern(path: Path, blocks: list[tuple[str, float, float]], fmt_suffix: str = ".dst") -> Path:
    """Write a simple pattern: one filled-ish square (zigzag rows) per colour block.

    blocks: [(hex, x0_mm, size_mm), ...]
    """
    p = pe.EmbPattern()
    for i, (hex_color, x0, size) in enumerate(blocks):
        p.add_thread(pe.EmbThread(hex_color))
        if i:
            p.add_command(pe.COLOR_CHANGE)
        x0u, s = x0 * 10, size * 10
        p.add_stitch_absolute(pe.JUMP, x0u, 0)
        y = 0.0
        while y <= s:
            p.add_stitch_absolute(pe.STITCH, x0u, y)
            p.add_stitch_absolute(pe.STITCH, x0u + s, y)
            y += 4  # 0.4 mm rows
        p.add_command(pe.TRIM)
    p.add_command(pe.END)
    path = path.with_suffix(fmt_suffix)
    pe.write(p, str(path))
    return path
