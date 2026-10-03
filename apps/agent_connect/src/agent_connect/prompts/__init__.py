"""Scenario registry.

Each entry pairs a system prompt with an SMS "first message" template.
The scheduler attaches `scenario` to every Job; agent-connect looks it up
here to pick the voice welcome greeting + the SMS body.

To add a scenario:
  1. Add an entry below.
  2. If it needs tools, add them in `agent_connect.tools` (populated in T2.7).

The {context} placeholder is substituted at send time with `job.context`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    key: str
    system_prompt: str
    sms_template: str
    voice_welcome: str


_BASE_STYLE = (
    "Keep responses short and conversational — a sentence or two. "
    "Do not use markdown, asterisks, bullets, or emojis; your words will "
    "be spoken aloud or sent as plain text."
)


_SCENARIOS: dict[str, Scenario] = {
    "appointment-confirmation": Scenario(
        key="appointment-confirmation",
        system_prompt=(
            "You are confirming a scheduled appointment with the customer. "
            "Mention the appointment time from the context and ask them to "
            "confirm, reschedule, or cancel. " + _BASE_STYLE
        ),
        sms_template=(
            "Hi — this is a reminder about your appointment on "
            "{appointment_time}. Reply YES to confirm, RESCHEDULE to change, "
            "or CANCEL to cancel."
        ),
        voice_welcome=(
            "Hi, I'm calling about your upcoming appointment. "
            "Is now a good time to confirm?"
        ),
    ),
    "payment-reminder": Scenario(
        key="payment-reminder",
        system_prompt=(
            "You are reminding the customer about an outstanding balance. "
            "State the amount and due date from the context. Offer to help "
            "them pay now or arrange a payment plan. Never attempt to collect "
            "payment card details on this channel. " + _BASE_STYLE
        ),
        sms_template=(
            "Hi — a reminder that ${amount_due} is due on {due_date}. "
            "Reply PAY to receive a secure link, or CALL to speak with us."
        ),
        voice_welcome=(
            "Hi, I'm calling about an outstanding balance on your account. "
            "Do you have a moment to review it?"
        ),
    ),
    "promotion": Scenario(
        key="promotion",
        system_prompt=(
            "You are following up on a marketing promotion the customer "
            "opted into. Reference details from the context, keep it brief, "
            "and respect any opt-out signal. " + _BASE_STYLE
        ),
        sms_template=(
            "Hi — here's an update on the offer you signed up for. "
            "Reply STOP to opt out."
        ),
        voice_welcome="Hi, I'm calling about the offer you signed up for.",
    ),
}


DEFAULT = Scenario(
    key="default",
    system_prompt=(
        "You are a customer service agent speaking with a user over voice "
        "or SMS. " + _BASE_STYLE
    ),
    sms_template="Hi — this is a message from our team. Reply HELP for assistance.",
    voice_welcome="Hello, how can I help?",
)


def get(key: str) -> Scenario:
    """Return the Scenario for `key`, or the default if unknown."""
    return _SCENARIOS.get(key, DEFAULT)


def render_sms(key: str, context: dict) -> str:
    """Render the SMS body for a scenario, substituting {context} placeholders.

    Missing keys fall back to the raw placeholder — the sample runs even when
    the Job's context is sparse.
    """
    scenario = get(key)
    try:
        return scenario.sms_template.format(**context)
    except (KeyError, IndexError):
        return scenario.sms_template


# For back-compat with any lingering imports; now unused by TAC-based handlers.
SYSTEM_INSTRUCTIONS = DEFAULT.system_prompt

__all__ = ["Scenario", "DEFAULT", "get", "render_sms", "SYSTEM_INSTRUCTIONS"]
