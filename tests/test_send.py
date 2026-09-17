import logging

import pytest
from resend.exceptions import (
    ApplicationError,
    MissingApiKeyError,
    RateLimitError,
    ResendError,
    ValidationError,
)

from src.send import _is_transient_send_error, send_digest


def _http_client_error():
    return ResendError(500, "HttpClientError", "boom", "retry the request")


def _config_error():
    return ResendError(500, "ConfigError", "bad config", "fix the configuration")


class TestIsTransientSendError:
    def test_rate_limit_error_is_transient(self):
        assert _is_transient_send_error(RateLimitError("slow down", "rate_limit_exceeded", 429)) is True

    def test_application_error_is_transient(self):
        assert _is_transient_send_error(ApplicationError("server error", "internal_server_error", 500)) is True

    def test_resend_error_http_client_error_is_transient(self):
        assert _is_transient_send_error(_http_client_error()) is True

    def test_resend_error_other_type_is_not_transient(self):
        assert _is_transient_send_error(_config_error()) is False

    def test_validation_error_is_not_transient(self):
        assert _is_transient_send_error(ValidationError("bad", "validation_error", 422)) is False

    def test_unrelated_exception_is_not_transient(self):
        assert _is_transient_send_error(ValueError("not a resend error")) is False


class TestSendDigest:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "test-key")
        monkeypatch.setenv("DEFAULT_FROM_EMAIL", "digest@example.com")
        monkeypatch.setenv("DIGEST_TO_EMAIL", "me@example.com")

    def test_sends_on_first_success(self, mocker):
        send = mocker.patch("src.send.resend.Emails.send")

        send_digest("<p>digest</p>", "python")

        assert send.call_count == 1

    def test_retries_transient_failure_then_succeeds(self, mocker, caplog):
        mocker.patch("time.sleep")
        send = mocker.patch("src.send.resend.Emails.send")
        send.side_effect = [_http_client_error(), None]

        with caplog.at_level(logging.WARNING, logger="zeitgeist"):
            send_digest("<p>digest</p>", "python")

        assert send.call_count == 2
        assert any(
            "send: attempt 1 failed, retrying" in record.message
            for record in caplog.records
        )

    def test_exhausts_all_three_attempts_then_reraises_original_error(self, mocker):
        mocker.patch("time.sleep")
        send = mocker.patch("src.send.resend.Emails.send")
        send.side_effect = RateLimitError("still limited", "rate_limit_exceeded", 429)

        with pytest.raises(RateLimitError):
            send_digest("<p>digest</p>", "python")

        assert send.call_count == 3

    def test_permanent_error_fails_on_first_attempt_without_retry(self, mocker):
        mocker.patch("time.sleep")
        send = mocker.patch("src.send.resend.Emails.send")
        send.side_effect = ValidationError("bad html", "validation_error", 422)

        with pytest.raises(ValidationError):
            send_digest("<p>digest</p>", "python")

        assert send.call_count == 1

    def test_missing_api_key_error_is_not_retried(self, mocker):
        mocker.patch("time.sleep")
        send = mocker.patch("src.send.resend.Emails.send")
        send.side_effect = MissingApiKeyError("missing key", "missing_api_key", 401)

        with pytest.raises(MissingApiKeyError):
            send_digest("<p>digest</p>", "python")

        assert send.call_count == 1
