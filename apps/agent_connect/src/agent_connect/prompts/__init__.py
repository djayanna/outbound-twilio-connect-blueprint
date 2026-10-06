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
    # Only used when `job.context.on_machine_answer == "leave_voicemail"` and
    # Twilio AMD says a machine picked up. Should instruct the model to leave
    # ONE sentence and end — not try to have a conversation with the beep.
    voicemail_prompt: str | None = None


_BASE_STYLE = (
    "Keep responses short and conversational — a sentence or two. "
    "Do not use markdown, asterisks, bullets, or emojis; your words will "
    "be spoken aloud or sent as plain text."
)

_VOICEMAIL_STYLE = (
    "You are leaving a brief voicemail — the recipient is NOT on the line. "
    "Say one short sentence stating who you are and why you called, then stop. "
    "Do not ask questions. Do not say 'hello', 'is anyone there', or wait "
    "for a response. End with a clear sign-off."
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
            "Hi, this is an automated reminder about your upcoming appointment "
            "on {appointment_time}. I can confirm it, help you reschedule, "
            "or cancel. What would you like to do?"
        ),
        voicemail_prompt=(
            "Leave a voicemail reminding the recipient about their appointment "
            "and asking them to call back to confirm. " + _VOICEMAIL_STYLE
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
            "Hi, this is an automated reminder about a balance due on your "
            "account. I can walk you through paying now or arranging a payment "
            "plan. Which would you like?"
        ),
        voicemail_prompt=(
            "Leave a voicemail noting there is an outstanding balance on "
            "the account and asking the recipient to call back. Do NOT state "
            "the amount or any account details. " + _VOICEMAIL_STYLE
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
        voice_welcome=(
            "Hi, this is an automated follow-up on an offer you signed up for. "
            "Reply STOP at any time to opt out — is now a good time to share "
            "the details?"
        ),
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


def voicemail_prompt_for(key: str) -> str:
    """Return the scenario's voicemail persona, or a generic fallback."""
    scenario = get(key)
    if scenario.voicemail_prompt:
        return scenario.voicemail_prompt
    return (
        "Leave a brief voicemail saying this is a follow-up and asking the "
        "recipient to call back when convenient. " + _VOICEMAIL_STYLE
    )


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

__all__ = [
    "Scenario",
    "DEFAULT",
    "get",
    "render_sms",
    "voicemail_prompt_for",
    "SYSTEM_INSTRUCTIONS",
]
