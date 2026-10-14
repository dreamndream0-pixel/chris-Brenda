"""AI suggestions with a fake Anthropic client: request shape, validation, rule review, failures."""
import json
from types import SimpleNamespace
from pathlib import Path

import anthropic
import httpx2
import pytest

from services.worker import ai_plan
from services.worker.ai_plan import AiError, build_request, parse_response, suggest
from services.worker.rules import plan_design
from services.worker.svg_import import import_svg

SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">
<path d="M10 40 C 30 5, 70 5, 90 40" fill="none" stroke="#1f2a44" stroke-width="3"/>
<rect x="40" y="20" width="20" height="15" fill="#c0392b"/>
<rect x="5" y="50" width="90" height="6" fill="#1f2a44"/></svg>'''


def design():
    return plan_design(import_svg(SVG, 100))


class FakeClient:
    def __init__(self, text=None, stop_reason="end_turn", error=None):
        self.text, self.stop_reason, self.error, self.calls = text, stop_reason, error, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        content = [SimpleNamespace(type="text", text=self.text)] if self.text is not None else []
        return SimpleNamespace(content=content, stop_reason=self.stop_reason, model=kwargs["model"],
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=300))


def answer(**over):
    data = {"regions": [
        {"id": "r1", "stitch": "satin", "confidence": 0.9, "needsReview": False, "reason": "均勻線條適合緞面"},
        {"id": "r2", "stitch": "satin", "confidence": 0.8, "needsReview": False, "reason": "試試緞面"},
        {"id": "r3", "stitch": "fill", "confidence": 0.4, "needsReview": False, "reason": "不確定"},
        {"id": "r99", "stitch": "fill", "confidence": 1, "needsReview": False, "reason": "不存在"},
    ], "risks": [{"code": "small_text", "regionIds": ["r2", "r99"], "message": "小字可能糊掉"},
                 {"code": "made_up", "regionIds": [], "message": "x"}],
        "summary": "整體適合刺繡"}
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


def test_request_shape():
    req = build_request(design())
    assert req["model"] == "claude-opus-5-5"
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["output_config"]["effort"] == "medium"
    assert req["output_config"]["format"]["type"] == "json_schema"
    image, text = req["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    facts = json.loads(text["text"].split("\n", 1)[1])
    assert {f["id"] for f in facts["regions"]} == {"r1", "r2", "r3"}
    assert "thinking" not in req  # Opus 5.5: adaptive by default; disabling is a 400


def test_parse_drops_unknown_and_invalid():
    out = parse_response(answer(), design())
    assert set(out["regions"]) == {"r1", "r2", "r3"}
    assert [r["code"] for r in out["risks"]] == ["small_text"]
    assert out["risks"][0]["regionIds"] == ["r2"]
    with pytest.raises(AiError) as e:
        parse_response("not json", design())
    assert e.value.code == "ai_bad_output"


def test_rules_review_ai_suggestions():
    d = design()
    ai = suggest(d, client=FakeClient(answer()))
    planned = {r["id"]: r for r in plan_design(d, ai["regions"])["regions"]}
    assert planned["r1"]["stitchType"] == "satin" and planned["r1"]["plan"]["source"] == "ai"
    # r2 is a 20x15 block: satin is geometrically impossible, rules override and flag it
    assert planned["r2"]["stitchType"] == "fill"
    assert planned["r2"]["plan"]["override"] == "satin_needs_uniform_stroke" and planned["r2"]["plan"]["needsReview"]
    assert planned["r3"]["plan"]["needsReview"]  # low confidence
    assert ai["usage"] == {"inputTokens": 1200, "outputTokens": 300}


@pytest.mark.parametrize("client,code", [
    (FakeClient(answer(), stop_reason="refusal"), "ai_refused"),
    (FakeClient(answer(), stop_reason="max_tokens"), "ai_truncated"),
    (FakeClient(None), "ai_bad_output"),
])
def test_bad_responses(client, code):
    with pytest.raises(AiError) as e:
        suggest(design(), client=client)
    assert e.value.code == code


def _status_error(cls, status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx2.Response(status, request=req), body=None)


@pytest.mark.parametrize("error,code", [
    (_status_error(anthropic.RateLimitError, 429), "ai_rate_limited"),
    (_status_error(anthropic.AuthenticationError, 401), "ai_auth_failed"),
    (_status_error(anthropic.InternalServerError, 500), "ai_unavailable"),
    (_status_error(anthropic.BadRequestError, 400), "ai_request_failed"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "ai_unavailable"),
])
def test_api_errors(error, code):
    with pytest.raises(AiError) as e:
        suggest(design(), client=FakeClient(error=error))
    assert e.value.code == code


def test_not_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("EMB_AI_ENABLED", raising=False)
    with pytest.raises(AiError) as e:
        suggest(design())
    assert e.value.code == "ai_not_configured"


def test_label_image_is_png():
    png = ai_plan.render_labels(design())
    assert png.startswith(b"\x89PNG")
