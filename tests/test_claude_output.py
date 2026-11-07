from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from qa_intelligence.analysis import UnusableAnalysisError
from qa_intelligence.claude_provider import ClaudeAnalysisProvider
from qa_intelligence.schemas import AnalysisRequest


@pytest.mark.parametrize(
    "stop_reason, content, expected_error",
    [
        ("max_tokens", '{"questions": [', UnusableAnalysisError),
        ("refusal", "Unable to comply", UnusableAnalysisError),
        ("end_turn", '{"questions": [', ValidationError),
        ("end_turn", '{"questions": [], "risks": []}', None),
    ],
)
def test_claude_checks_completion_before_validating_json(
    stop_reason, content, expected_error
):
    response = SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=content)],
        model="test-model",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    client = MagicMock()
    client.messages.create.return_value = response
    request = AnalysisRequest(
        requirement_id="REQ-1", text="Accept energy events.", acceptance_criteria=[]
    )
    with patch("qa_intelligence.claude_provider.Anthropic") as constructor:
        constructor.return_value.__enter__.return_value = client
        provider = ClaudeAnalysisProvider("synthetic-key", "test-model")
        if expected_error:
            with pytest.raises(expected_error) as caught:
                provider.analyze(request)
            if expected_error is UnusableAnalysisError:
                assert caught.value.reason == stop_reason
        else:
            draft = provider.analyze(request)
            assert draft.questions == []
            assert draft.risks == []
            assert draft.metadata.provider == "anthropic"
            assert draft.metadata.token_usage == 15
        client.messages.create.assert_called_once()
