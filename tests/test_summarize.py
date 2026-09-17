import logging

import httpx
import pytest
from langchain_google_genai.chat_models import (
    GoogleAPIError,
    GoogleInvalidRequestError,
    GoogleRateLimitError,
)

from src.summarize import summarize_repo

REPO = {"full_name": "octocat/hello-world", "description": "A friendly repo", "language": "Python"}


def _mock_client(mocker, invoke_result_or_side_effect):
    structured_model = mocker.Mock()
    if isinstance(invoke_result_or_side_effect, list):
        structured_model.invoke.side_effect = invoke_result_or_side_effect
    else:
        structured_model.invoke.return_value = invoke_result_or_side_effect

    client = mocker.Mock()
    client.with_structured_output.return_value = structured_model
    return client, structured_model


def _response(summary="a summary", use_cases="a use case"):
    response = type("Resp", (), {})()
    response.model_dump = lambda: {"summary": summary, "use_cases": use_cases}
    return response


class TestSummarizeRepo:
    def test_returns_summary_and_use_cases_on_first_success(self, mocker):
        client, structured_model = _mock_client(mocker, _response())

        summary, use_cases = summarize_repo(client, REPO, profile="likes python tooling")

        assert (summary, use_cases) == ("a summary", "a use case")
        assert structured_model.invoke.call_count == 1

    def test_retries_rate_limit_then_succeeds(self, mocker, caplog):
        mocker.patch("time.sleep")
        client, structured_model = _mock_client(
            mocker, [GoogleRateLimitError("rate limited"), _response()]
        )

        with caplog.at_level(logging.WARNING, logger="zeitgeist"):
            summary, use_cases = summarize_repo(client, REPO, profile="p")

        assert structured_model.invoke.call_count == 2
        assert (summary, use_cases) == ("a summary", "a use case")
        assert any(
            "summarize: attempt 1 failed, retrying" in record.message
            for record in caplog.records
        )

    def test_retries_server_error_then_succeeds(self, mocker):
        mocker.patch("time.sleep")
        server_error = GoogleAPIError(code=500, response_json={"error": "server error"})
        client, structured_model = _mock_client(mocker, [server_error, _response()])

        summarize_repo(client, REPO, profile="p")

        assert structured_model.invoke.call_count == 2

    @pytest.mark.parametrize(
        "transient_exc",
        [
            httpx.TimeoutException("timed out"),
            httpx.ConnectError("connection refused"),
        ],
    )
    def test_retries_transport_errors_then_succeeds(self, mocker, transient_exc):
        mocker.patch("time.sleep")
        client, structured_model = _mock_client(mocker, [transient_exc, _response()])

        summarize_repo(client, REPO, profile="p")

        assert structured_model.invoke.call_count == 2

    def test_exhausts_all_three_attempts_then_reraises_original_error(self, mocker):
        mocker.patch("time.sleep")
        client, structured_model = _mock_client(mocker, GoogleRateLimitError("still limited"))
        structured_model.invoke.side_effect = GoogleRateLimitError("still limited")

        with pytest.raises(GoogleRateLimitError):
            summarize_repo(client, REPO, profile="p")

        assert structured_model.invoke.call_count == 3

    def test_permanent_error_fails_on_first_attempt_without_retry(self, mocker):
        mocker.patch("time.sleep")
        client, structured_model = _mock_client(
            mocker, GoogleInvalidRequestError("bad request")
        )
        structured_model.invoke.side_effect = GoogleInvalidRequestError("bad request")

        with pytest.raises(GoogleInvalidRequestError):
            summarize_repo(client, REPO, profile="p")

        assert structured_model.invoke.call_count == 1
