"""
AgentMail client for ClawBot.

ClawBot's dedicated outbound/inbound inbox — separate from Nate's Outlook.
- Outlook (M365)  → Nate's personal/business email (read-only for ClawBot)
- AgentMail       → ClawBot's own @agentmail.to address for agent-originated mail

Inbox is created idempotently on first use; subsequent calls return the existing one.
"""
import os
import logging
from functools import lru_cache

from agentmail import AgentMail
from agentmail.core.api_error import ApiError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (loaded from Vault or .env via vault_secrets.get_secrets())
# ---------------------------------------------------------------------------
_INBOX_USERNAME = os.getenv("AGENTMAIL_INBOX_USERNAME", "clawbot")
_CLIENT_ID = "clawbot-primary-v1"  # idempotency key — do not change


def _client() -> AgentMail:
    """Return an authenticated AgentMail client."""
    api_key = os.getenv("AGENTMAIL_API_KEY")
    if not api_key:
        raise RuntimeError("AGENTMAIL_API_KEY is not set")
    return AgentMail(api_key=api_key)


@lru_cache(maxsize=1)
def get_agent_inbox_id() -> str:
    """
    Return ClawBot's inbox email address, creating the inbox if it doesn't exist yet.
    Result is cached in-process so subsequent calls are free.
    """
    c = _client()
    inbox = c.inboxes.create(
        username=_INBOX_USERNAME,
        client_id=_CLIENT_ID,
    )
    logger.info("AgentMail inbox ready: %s", inbox.email)
    return inbox.email


def send_email(to: str, subject: str, text: str, html: str | None = None,
               labels: list[str] | None = None) -> dict:
    """
    Send an email from ClawBot's agent inbox.

    Args:
        to:      Recipient address (or comma-separated list).
        subject: Email subject line.
        text:    Plain-text body (required for deliverability).
        html:    Optional HTML body.
        labels:  Optional list of label strings for categorisation.

    Returns:
        The SendMessageResponse as a dict.
    """
    c = _client()
    inbox_id = get_agent_inbox_id()
    kwargs: dict = dict(inbox_id=inbox_id, to=to, subject=subject, text=text)
    if html:
        kwargs["html"] = html
    if labels:
        kwargs["labels"] = labels
    try:
        response = c.inboxes.messages.send(**kwargs)
        logger.info("AgentMail sent → %s | %s", to, subject)
        return response.dict() if hasattr(response, "dict") else vars(response)
    except ApiError as e:
        logger.error("AgentMail send failed: %s %s", e.status_code, e.body)
        raise


def list_messages(limit: int = 10, labels: list[str] | None = None) -> list[dict]:
    """
    List messages received in ClawBot's agent inbox (newest first).

    Returns a list of message dicts with keys: message_id, subject, from_, text, html, labels.
    """
    c = _client()
    inbox_id = get_agent_inbox_id()
    kwargs: dict = dict(inbox_id=inbox_id, limit=limit, ascending=False)
    if labels:
        kwargs["labels"] = labels
    try:
        response = c.inboxes.messages.list(**kwargs)
        messages = response.messages if hasattr(response, "messages") else []
        return [_msg_to_dict(m) for m in messages]
    except ApiError as e:
        logger.error("AgentMail list failed: %s %s", e.status_code, e.body)
        raise


def reply_to_message(message_id: str, text: str, html: str | None = None) -> dict:
    """
    Reply to a message received in ClawBot's agent inbox.

    Args:
        message_id: The ID of the message to reply to.
        text:       Plain-text reply body.
        html:       Optional HTML reply body.
    """
    c = _client()
    inbox_id = get_agent_inbox_id()
    kwargs: dict = dict(inbox_id=inbox_id, message_id=message_id, text=text)
    if html:
        kwargs["html"] = html
    try:
        response = c.inboxes.messages.reply(**kwargs)
        logger.info("AgentMail replied to %s", message_id)
        return response.dict() if hasattr(response, "dict") else vars(response)
    except ApiError as e:
        logger.error("AgentMail reply failed: %s %s", e.status_code, e.body)
        raise


def _msg_to_dict(msg) -> dict:
    """Normalise a Message object to a plain dict."""
    return {
        "message_id": getattr(msg, "message_id", None),
        "subject":    getattr(msg, "subject", ""),
        "from_":      getattr(msg, "from_", None),
        "text":       getattr(msg, "text", ""),
        "html":       getattr(msg, "html", ""),
        "labels":     getattr(msg, "labels", []),
        "created_at": str(getattr(msg, "created_at", "")),
    }
