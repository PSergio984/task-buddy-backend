"""SC-4 contract: transactional email failure semantics.

Every sender chain in ``app/tasks.py`` (confirmation / password_reset /
password_changed) must, per the phase 4 best-effort email contract:

- log EXACTLY ONE ERROR-level structured line when the whole
  Brevo -> SMTP delivery chain exhausts. The line names the email class,
  both channels tried (``channels=brevo,smtp``), and a PII-redacted
  recipient;
- never expose a bare ``local@domain`` address in ANY emitted record —
  recipients flow through ``app.logging_conf.obfuscated()`` plus the
  ``extra={"email": ...}`` field that ``EmailObfuscationFilter`` rewrites;
- keep an intermediate Brevo-stage failure at WARNING only (zero ERROR
  records while SMTP still succeeds);
- preserve each chain's ``suppress_exceptions`` semantics (default
  ``False`` raises :class:`app.tasks.APIResponseError` chained from the
  SMTP error after logging).

Records are captured with pytest's ``caplog`` after temporarily enabling
propagation on the non-propagating ``app`` / ``app.tasks`` loggers.
"""

import logging
import re
from typing import Any

import pytest
from pytest import LogCaptureFixture, MonkeyPatch

from app.logging_conf import obfuscated
from app.tasks import (
    APIResponseError,
    _send_confirmation_email_async,
    _send_password_changed_confirmation_async,
    _send_password_reset_email_async,
)

BARE_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@pytest.fixture()
def task_logs(caplog: LogCaptureFixture, monkeypatch: MonkeyPatch) -> LogCaptureFixture:
    """Route app.tasks records into caplog despite the non-propagating 'app' logger."""
    monkeypatch.setattr(logging.getLogger("app"), "propagate", True)
    monkeypatch.setattr(logging.getLogger("app.tasks"), "propagate", True)
    with caplog.at_level(logging.INFO, logger="app.tasks"):
        yield caplog


def _assert_single_redacted_error(
    task_logs: LogCaptureFixture, recipient: str, email_class: str
) -> None:
    errors = [record for record in task_logs.records if record.levelno == logging.ERROR]
    assert len(errors) == 1, f"expected exactly one ERROR record, got {len(errors)}"
    message = errors[0].getMessage()
    assert f"class={email_class}" in message
    assert "channels=brevo,smtp" in message
    assert obfuscated(recipient) in message

    for record in task_logs.records:
        text = record.getMessage()
        assert recipient not in text, f"raw recipient leaked in log record: {text!r}"
        assert BARE_ADDRESS_RE.search(text) is None, f"bare address in record: {text!r}"


@pytest.mark.anyio
async def test_confirmation_dual_failure_single_redacted_error(
    mock_httpx_client: Any, task_logs: LogCaptureFixture
) -> None:
    """Brevo HTTP AND SMTP send both fail -> exactly one redacted ERROR, then raise."""
    mock_httpx_client.post.side_effect = Exception("brevo api unavailable")
    mock_httpx_client.smtp_client.send_message.side_effect = Exception("smtp relay down")
    recipient = "jane.doe@example.com"

    with pytest.raises(APIResponseError) as excinfo:
        await _send_confirmation_email_async(recipient, "Subject", "Body")

    assert isinstance(excinfo.value.__cause__, Exception)

    _assert_single_redacted_error(task_logs, recipient, "confirmation")


@pytest.mark.anyio
async def test_confirmation_brevo_only_failure_stays_warning(
    mock_httpx_client: Any, task_logs: LogCaptureFixture
) -> None:
    """Only the Brevo stage fails, SMTP succeeds -> zero ERROR records, WARNING present."""
    mock_httpx_client.post.side_effect = Exception("brevo api unavailable")
    recipient = "john.smith@example.com"

    # Default suppress_exceptions=False must NOT raise on an intermediate stage.
    await _send_confirmation_email_async(recipient, "Subject", "Body")

    errors = [record for record in task_logs.records if record.levelno == logging.ERROR]
    warnings = [record for record in task_logs.records if record.levelno == logging.WARNING]
    assert errors == []
    assert len(warnings) == 1
    text = warnings[0].getMessage()
    assert obfuscated(recipient) in text
    assert recipient not in text


@pytest.mark.anyio
async def test_password_reset_dual_failure_single_redacted_error(
    mock_httpx_client: Any, task_logs: LogCaptureFixture
) -> None:
    """Password-reset chain logs through the same one-ERROR contract (class=password_reset)."""
    mock_httpx_client.post.side_effect = Exception("brevo api unavailable")
    mock_httpx_client.smtp_client.send_message.side_effect = Exception("smtp relay down")
    recipient = "reset.me@example.com"

    with pytest.raises(APIResponseError):
        await _send_password_reset_email_async(recipient, "https://example.com/reset?t=1")

    _assert_single_redacted_error(task_logs, recipient, "password_reset")


@pytest.mark.anyio
async def test_password_changed_dual_failure_single_redacted_error(
    mock_httpx_client: Any, task_logs: LogCaptureFixture
) -> None:
    """Password-changed chain logs through the same one-ERROR contract (class=password_changed)."""
    mock_httpx_client.post.side_effect = Exception("brevo api unavailable")
    mock_httpx_client.smtp_client.send_message.side_effect = Exception("smtp relay down")
    recipient = "changed.pw@example.com"

    with pytest.raises(APIResponseError):
        await _send_password_changed_confirmation_async(recipient)

    _assert_single_redacted_error(task_logs, recipient, "password_changed")
