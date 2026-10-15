from lxml import etree

from services.worker.svg_compile import INKSTITCH_NS, compile_design, split_components

SQUARE_WITH_HOLE = "M 0 0 L 10 0 L 10 10 L 0 10 Z M 3 3 L 7 3 L 7 7 L 3 7 Z"
SECOND_SQUARE = "M 20 0 L 30 0 L 30 10 L 20 10 Z"


def _design(path: str) -> dict:
    return {
        "schemaVersion": 1,
        "sizeMm": {"width": 30, "height": 10},
        "geometry": {"viewBox": [0, 0, 30, 10]},
        "palette": [{"id": "c1", "hex": "#112233"}],
        "regions": [{"id": "r1", "order": 1, "colorId": "c1", "stitchType": "fill", "shape": "area",
                     "fillRule": "evenodd", "svgPath": path, "params": {}}],
    }


def test_split_keeps_holes_with_their_island():
    parts = split_components(f"{SQUARE_WITH_HOLE} {SECOND_SQUARE}")
    assert len(parts) == 2
    assert parts[0].upper().count("M") == 2   # outline + hole
    assert parts[1].upper().count("M") == 1


def test_single_island_is_untouched():
    assert len(split_components(SQUARE_WITH_HOLE)) == 1


def test_every_element_trims_after():
    root = etree.fromstring(compile_design(_design(f"{SQUARE_WITH_HOLE} {SECOND_SQUARE}")))
    paths = root.findall(".//{http://www.w3.org/2000/svg}path")
    assert [p.get("id") for p in paths] == ["r1_1", "r1_2"]
    assert all(p.get(f"{{{INKSTITCH_NS}}}trim_after") == "True" for p in paths)


def test_detail_level_tightens_fill():
    from services.worker.svg_compile import INKSTITCH_NS as NS

    def attrs(level):
        design = _design(SECOND_SQUARE) | {"detailLevel": level}
        design["regions"][0]["params"] = {"rowSpacingMm": 0.4, "maxStitchLengthMm": 3.0}
        path = etree.fromstring(compile_design(design)).find(".//{http://www.w3.org/2000/svg}path")
        return float(path.get(f"{{{NS}}}row_spacing_mm")), float(path.get(f"{{{NS}}}max_stitch_length_mm"))

    assert attrs("standard") == (0.4, 3.0)
    assert attrs("fine") == (0.35, 2.5)
    assert attrs("ultra") == (0.3, 2.0)
