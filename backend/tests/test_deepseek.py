"""DeepSeek provider: JSON mode, schema validation with one corrective retry, honest errors."""

import json

import httpx
import pytest
import respx

from app.research.analysis.ai_service import AIService, AIUnavailable
from app.research.analysis.schemas import ResearchSpec

URL = "https://api.deepseek.com/chat/completions"
VALID = {
    "industry": "dental_clinics",
    "country": "SA",
    "city": "Riyadh",
    "keywords": ["dentist", "عيادة أسنان"],
    "excluded_keywords": [],
    "characteristics": [],
    "services": [],
    "language": "en",
}


def reply(content: str, finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40},
        },
    )


def service() -> AIService:
    return AIService({"deepseek": {"api_key": "sk-test"}})


async def test_deepseek_structured_output_with_corrective_retry(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ai_provider", "deepseek")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(URL).mock(
            side_effect=[reply('{"industry": "dental_clinics"}'), reply("```json\n" + json.dumps(VALID) + "\n```")]
        )
        ai = service()
        assert ai.provider == "deepseek"
        result = await ai.parse_research_spec("dentists in Riyadh")
    assert result.output.city == "Riyadh" and result.provider == "deepseek"
    assert (result.input_tokens, result.output_tokens) == (200, 80)  # both attempts are counted
    first = json.loads(route.calls[0].request.content)
    assert first["response_format"] == {"type": "json_object"} and "JSON Schema" in first["messages"][0]["content"]
    second = json.loads(route.calls[1].request.content)
    assert second["messages"][-1]["content"].startswith("That JSON is invalid")
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, json={"error": "bad key"}), "rejected the API key"),
        (httpx.Response(402, json={"error": "no balance"}), "balance"),
        (reply("{}", finish="length"), "output tokens"),
    ],
)
async def test_deepseek_errors_are_explicit(response, message):
    with respx.mock() as mock:
        mock.post(URL).mock(return_value=response)
        with pytest.raises(AIUnavailable, match=message):
            await service().structured("sys", "user", ResearchSpec)
