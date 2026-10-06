from agent_connect.prompts import DEFAULT, get, render_sms


def test_get_known_scenario():
    s = get("appointment-confirmation")
    assert s.key == "appointment-confirmation"
    assert "appointment" in s.system_prompt


def test_get_unknown_returns_default():
    assert get("not-a-scenario") is DEFAULT


def test_render_sms_substitutes_context():
    out = render_sms(
        "appointment-confirmation",
        {"appointment_time": "2026-10-05T15:00:00Z"},
    )
    assert "2026-10-05T15:00:00Z" in out


def test_render_sms_tolerates_missing_keys():
    out = render_sms("payment-reminder", {})
    assert out  # falls back to the raw template; still a string
