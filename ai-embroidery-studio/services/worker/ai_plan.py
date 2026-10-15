"""AI stitch suggestions (spec §6 stage 3): advisory only, reviewed by rules.py.

Claude sees a labelled re-render of the design's vector regions (never the raw
upload) plus per-region geometry, and returns structured JSON that may only
reference existing region ids. It never produces coordinates or stitches.
"""
from __future__ import annotations

import base64
import json
import os

import cv2
import numpy as np

from .geometry import masks_for
from .rules import ensure_metrics, satin_blocker, stroke_width_mm, unit_to_mm

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_IMAGE_SIDE = 1200
MAX_REGIONS = 400
RISK_CODES = ["small_text", "thin_lines", "tiny_details", "too_many_colors", "gradient_like",
              "large_satin", "dense_overlap", "other"]

SYSTEM_PROMPT = """You are an embroidery digitizing assistant inside a tool that turns logos and simple artwork into machine embroidery files.
You receive a labelled picture of the design (each region is filled with its thread colour and tagged with its id) and measured geometry for every region.
For each region, suggest one stitch type:
- "fill": tatami fill for areas.
- "running": a single running line, for thin lines (under about 1.2 mm) or outlines.
- "satin": a satin column, only for strokes of fairly uniform width, roughly 1-7 mm wide (letters' strokes, borders, ribbons). The geometry says whether satin is geometrically possible; do not suggest satin where satinAllowed is false.
Prefer the conventional digitizer choice for a clean, durable result on the stated fabric. Set needsReview when you are unsure or the region is ambiguous (e.g. you cannot tell whether it is text, or detail may be lost at this size).
Also list design-level risks a production digitizer would flag (small text, thin lines, tiny details, too many colours, gradient-like areas, very wide satin, heavy overlap).
Only use region ids that appear in the data. Write `reason` and risk `message` in Traditional Chinese (Taiwan), one short sentence each."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "stitch": {"type": "string", "enum": ["fill", "running", "satin"]},
                    "confidence": {"type": "number"},
                    "needsReview": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "stitch", "confidence", "needsReview", "reason"],
                "additionalProperties": False,
            },
        },
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "enum": RISK_CODES},
                    "regionIds": {"type": "array", "items": {"type": "string"}},
                    "message": {"type": "string"},
                },
                "required": ["code", "regionIds", "message"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["regions", "risks", "summary"],
    "additionalProperties": False,
}


class AiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def ai_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("EMB_AI_ENABLED") == "1")


def ai_model() -> str:
    return os.environ.get("EMB_AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def render_labels(design: dict) -> bytes:
    """PNG of all visible regions in thread colours with their ids printed inside."""
    masks, _ = masks_for(design)
    h, w = next(iter(masks.values())).shape
    scale = min(1.0, MAX_IMAGE_SIDE / max(h, w))
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    canvas = np.full((size[1], size[0], 3), 255, np.uint8)
    colors = {c["id"]: c["hex"] for c in design["palette"]}
    ordered = [r for r in sorted(design["regions"], key=lambda r: r["order"]) if not r.get("hidden")]
    small = {}
    for r in ordered:
        m = cv2.resize(masks[r["id"]].astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)
        small[r["id"]] = m
        hx = colors[r["colorId"]].lstrip("#")
        canvas[m] = (int(hx[4:6], 16), int(hx[2:4], 16), int(hx[0:2], 16))  # BGR
    for r in ordered:
        m = small[r["id"]]
        if not m.any():
            continue
        dist = cv2.distanceTransform(np.pad(m.astype(np.uint8), 1), cv2.DIST_L2, 3)[1:-1, 1:-1]
        y, x = np.unravel_index(int(dist.argmax()), dist.shape)
        label, font = r["id"], cv2.FONT_HERSHEY_SIMPLEX
        (tw, th), _ = cv2.getTextSize(label, font, 0.5, 1)
        org = (int(min(max(2, x - tw // 2), size[0] - tw - 2)), int(min(max(th + 2, y + th // 2), size[1] - 2)))
        cv2.putText(canvas, label, org, font, 0.5, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(canvas, label, org, font, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    ok, png = cv2.imencode(".png", canvas)
    return png.tobytes()


def region_facts(design: dict) -> list[dict]:
    k = unit_to_mm(design)
    colors = {c["id"]: c["hex"] for c in design["palette"]}
    facts = []
    for r in sorted(design["regions"], key=lambda r: r["order"]):
        if r.get("hidden"):
            continue
        m = r.get("metrics") or {}
        c = m.get("centerline")
        blocker = satin_blocker(r, design)
        w = stroke_width_mm(r, design)
        facts.append({
            "id": r["id"], "color": colors[r["colorId"]], "shape": r.get("shape", "area"),
            "currentStitch": r["stitchType"],
            "areaMm2": round(m.get("areaUnits2", 0) * k * k, 1),
            "maxThicknessMm": round(m.get("thicknessUnits", 0) * k, 2),
            "strokeWidthMm": round(w, 2) if w is not None else None,
            "strokeLengthMm": round(c["lengthUnits"] * k, 1) if c else None,
            "widthVariation": c["widthCv"] if c else None,
            "holes": m.get("holes", 0),
            "satinAllowed": blocker is None,
            "satinBlockedBecause": blocker,
        })
    return facts


def build_request(design: dict) -> dict:
    design = ensure_metrics(design)
    facts = region_facts(design)
    if len(facts) > MAX_REGIONS:
        raise AiError("too_many_regions", f"AI review supports at most {MAX_REGIONS} regions")
    info = {
        "sizeMm": design["sizeMm"], "fabric": design["fabricPreset"], "threadColors": len(design["palette"]),
        "regions": facts,
    }
    image = base64.standard_b64encode(render_labels(design)).decode()
    return {
        "model": ai_model(),
        "max_tokens": 16000,
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
        "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}},
            {"type": "text", "text": "Design data (JSON):\n" + json.dumps(info, ensure_ascii=False)},
        ]}],
    }


def parse_response(text: str, design: dict) -> dict:
    """Validate model output; anything referring to unknown regions is dropped."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AiError("ai_bad_output", "model did not return JSON") from exc
    known = {r["id"] for r in design["regions"]}
    regions: dict[str, dict] = {}
    for item in data.get("regions", []):
        rid = item.get("id")
        if rid not in known or rid in regions or item.get("stitch") not in ("fill", "running", "satin"):
            continue
        try:
            conf = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        regions[rid] = {"stitch": item["stitch"], "confidence": round(min(max(conf, 0.0), 1.0), 2),
                        "needsReview": bool(item.get("needsReview")), "reason": str(item.get("reason", ""))[:200]}
    risks = []
    for item in data.get("risks", [])[:20]:
        if item.get("code") in RISK_CODES:
            risks.append({"code": item["code"], "message": str(item.get("message", ""))[:300],
                          "regionIds": [i for i in item.get("regionIds", []) if i in known][:50]})
    return {"regions": regions, "risks": risks, "summary": str(data.get("summary", ""))[:600]}


def _client():
    import anthropic
    return anthropic.Anthropic(max_retries=2, timeout=180.0)


def suggest(design: dict, client=None) -> dict:
    """Call Claude and return validated suggestions + usage metadata. Raises AiError."""
    if client is None and not ai_enabled():
        raise AiError("ai_not_configured", "set ANTHROPIC_API_KEY to enable AI suggestions")
    import anthropic
    request = build_request(design)
    if client is None:
        try:
            client = _client()
        except anthropic.AnthropicError as exc:  # e.g. API enabled the button but this worker has no key
            raise AiError("ai_not_configured", "no Anthropic credentials on the worker") from exc
    try:
        response = client.beta.messages.create(**request)
    except anthropic.RateLimitError as exc:
        raise AiError("ai_rate_limited", "AI service is rate limited, try again later") from exc
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise AiError("ai_auth_failed", "AI credentials were rejected") from exc
    except anthropic.APIStatusError as exc:
        raise AiError("ai_unavailable" if exc.status_code >= 500 else "ai_request_failed",
                      f"AI request failed ({exc.status_code})") from exc
    except anthropic.APIConnectionError as exc:
        raise AiError("ai_unavailable", "cannot reach the AI service") from exc

    if response.stop_reason == "refusal":
        raise AiError("ai_refused", "the AI declined to analyse this design")
    if response.stop_reason == "max_tokens":
        raise AiError("ai_truncated", "AI response was cut off")
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
    if not text:
        raise AiError("ai_bad_output", "AI returned no text")
    result = parse_response(text, design)
    usage = getattr(response, "usage", None)
    result["model"] = getattr(response, "model", request["model"])
    result["usage"] = {"inputTokens": getattr(usage, "input_tokens", None),
                       "outputTokens": getattr(usage, "output_tokens", None)}
    return result
