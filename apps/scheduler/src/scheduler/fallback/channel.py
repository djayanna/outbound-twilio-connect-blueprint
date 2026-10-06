"""Channel fallback rules.

When a voice attempt ends with an unanswered-type terminal reason we try
SMS on the next attempt. SMS failures do not currently fall back to voice
(the common pattern is voice→SMS, not the reverse). The rule set lives in
code so swapping it for a YAML file later is one function change.
"""
from __future__ import annotations

from voice_blueprint_shared.job import Job

_VOICE_SMS_FALLBACK_REASONS = {"no-answer", "busy", "failed", "canceled", "voicemail"}


def next_channel(job: Job, terminal_reason: str | None) -> str | None:
    """Return the channel to try next, or None if no fallback applies.

    The caller decides whether to actually enqueue a new attempt — this
    just maps (current_channel, reason) → next_channel.
    """
    if job.channel == "voice" and terminal_reason in _VOICE_SMS_FALLBACK_REASONS:
        return "sms"
    return None


__all__ = ["next_channel"]
