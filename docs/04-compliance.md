# Compliance posture

The blueprint **demonstrates** these guardrails. Each one needs real backing data and sign-off from your compliance team before production.

## TCPA quiet hours

Enforced in `scheduler/policy/quiet_hours.py`. Timezone is resolved from the recipient's E.164 number (country → primary IANA zone) and overridden by `job.constraints.timezone` when the upstream system knows better. Window is `job.constraints.allowed_hours_local` (`("HH:MM","HH:MM")`); supports cross-midnight ranges like `("22:00","08:00")`.

**Known gap:** the primary-zone map in `policy/timezones.py` picks one zone per country. For multi-zone countries (US, CA, AU, BR) the conservative default is the latest sunset — set `job.constraints.timezone` on every outreach for accuracy.

## Consent

`scheduler/policy/consent.py` refuses marketing SMS without `job.consent`. The Job model requires `consent.source` + `consent.captured_at`. The blueprint does **not** verify freshness; add that upstream of `POST /jobs` if your jurisdiction demands it (e.g. 365-day refresh for CTIA).

## Do-not-contact

`scheduler/policy/dnc_repository.py` is a SQLite-backed suppression list in the same database as Jobs. Ops endpoints:

- `POST /dnc` — body `{phone, reason?}`
- `DELETE /dnc/{phone}` — 404 if not present
- `GET /dnc` — list

Both writes audit as `dnc.added` / `dnc.removed`. All three are gated by `X-Blueprint-Key`.

## Answering Machine Detection (AMD)

Every outbound voice call ships with Twilio AMD enabled. When a machine picks up, the behavior is per-Job via `context.on_machine_answer`:

- `"hangup"` (default) — scheduler hangs up the call, marks the run `failed` with `terminal_reason=voicemail`, and the fallback engine queues an SMS attempt automatically. **Pick this when you cannot leave AI-generated voicemails under your jurisdiction's rules** (TCPA interpretations vary — many legal teams insist AI voicemails are "artificial or prerecorded voice" and require prior express written consent to leave).
- `"leave_voicemail"` — scheduler tags the run with the AMD verdict; agent-connect's `on_message_ready` swaps the scenario's conversational system prompt for a one-sentence voicemail persona (`voicemail_prompt_for(scenario)` in `agent_connect/prompts/__init__.py`). Tools are disabled during voicemail turns. **Confirm with your compliance team before enabling.**

`unknown` (AMD timeout) is treated as `human` — ConversationRelay proceeds normally.

## PCI DSS

**ConversationRelay is used in modes compatible with PCI patterns** — audio never flows through our process; it's handled by Twilio's media layer. The sample scenarios **do not** capture payment card details. For a scenario that does, use Twilio `<Pay>` or `<Gather partialResultCallback>` with proper DTMF redaction configured on the Twilio side; do not route card data through the LLM.

## HIPAA

The blueprint is **not** HIPAA-enabled. Enabling HIPAA requires:

- A Business Associate Agreement with Twilio.
- Marking your Twilio account as HIPAA-enabled (via Twilio support).
- Using only HIPAA-eligible Twilio products — see the `twilio-security-compliance-hipaa` skill.
- Redacting PHI in all logs. Audit entries in this sample include free-form `data` fields that may carry PHI; add redaction before writing audit if HIPAA applies.

## GDPR

Not addressed in the sample. Right-to-deletion requires reaching into Conversation Memory + the audit log + Twilio call recordings + the DNC list. Build a per-identity delete tool that iterates each.
