"""Deciding what to notify about, and sending it."""

from datetime import UTC, datetime, timedelta

import pytest

from lifeline.services.notifier import AppriseSender, Event, Notifier, _redact, build
from tests.conftest import RecordingSender, make_settings, make_site

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
CONFIGURED = "tgram://token/chat"


def settings_with(**overrides: object) -> object:
    """A settings row with a destination configured."""
    return make_settings(apprise_urls=CONFIGURED, **overrides)


class TestDelivery:
    async def test_sends_to_every_configured_destination(
        self, notifier: Notifier, sender: RecordingSender
    ) -> None:
        row = make_settings(apprise_urls="tgram://a/b\nmailto://c:d@e")

        assert await notifier.notify(row, Event.LAPSED, make_site(), "gone", now=NOW) is True
        assert sender.sent[0][0] == ["tgram://a/b", "mailto://c:d@e"]

    async def test_sends_nothing_when_no_destination_is_configured(
        self, notifier: Notifier, sender: RecordingSender
    ) -> None:
        assert await notifier.notify(make_settings(), Event.LAPSED, make_site(), now=NOW) is False
        assert sender.sent == []

    async def test_reports_a_failure_to_deliver(self) -> None:
        sender = RecordingSender(delivers=False)
        notifier = Notifier(sender)

        assert await notifier.notify(settings_with(), Event.LAPSED, make_site(), now=NOW) is False

    async def test_a_failed_send_does_not_start_the_cooldown(self) -> None:
        # Otherwise a transient outage silences the message entirely.
        sender = RecordingSender(delivers=False)
        notifier = Notifier(sender)
        row = settings_with()
        site = make_site()

        await notifier.notify(row, Event.LAPSED, site, now=NOW)
        sender.delivers = True

        assert await notifier.notify(row, Event.LAPSED, site, now=NOW) is True


class TestToggles:
    @pytest.mark.parametrize(
        ("event", "toggle"),
        [
            (Event.LAPSED, "notify_on_lapsed"),
            (Event.RECOVERED, "notify_on_recovered"),
            (Event.ERRORS, "notify_on_errors"),
            (Event.AT_RISK, "notify_on_deadline"),
        ],
    )
    async def test_an_event_can_be_switched_off(
        self, notifier: Notifier, event: Event, toggle: str
    ) -> None:
        row = settings_with(**{toggle: False})

        assert await notifier.notify(row, event, make_site(), "detail", now=NOW) is False

    async def test_a_test_message_ignores_every_toggle(self, notifier: Notifier) -> None:
        # A test button that honours a toggle looks broken rather than configurable.
        row = settings_with(
            notify_on_lapsed=False,
            notify_on_recovered=False,
            notify_on_errors=False,
            notify_on_deadline=False,
        )

        assert await notifier.notify(row, Event.TEST, now=NOW) is True


class TestCooldown:
    async def test_suppresses_a_repeat_within_the_cooldown(
        self, notifier: Notifier, sender: RecordingSender
    ) -> None:
        # A dead session fails every check; one message per check trains you to ignore it.
        row = settings_with(notify_cooldown_hours=24)
        site = make_site()

        await notifier.notify(row, Event.LAPSED, site, now=NOW)
        second = await notifier.notify(row, Event.LAPSED, site, now=NOW + timedelta(hours=23))

        assert second is False
        assert len(sender.sent) == 1

    async def test_sends_again_once_the_cooldown_passes(self, notifier: Notifier) -> None:
        row = settings_with(notify_cooldown_hours=24)
        site = make_site()

        await notifier.notify(row, Event.LAPSED, site, now=NOW)

        assert await notifier.notify(row, Event.LAPSED, site, now=NOW + timedelta(hours=25)) is True

    async def test_cooldowns_are_per_site(self, notifier: Notifier) -> None:
        row = settings_with()

        await notifier.notify(row, Event.LAPSED, make_site(id=1, name="one"), now=NOW)

        sent = await notifier.notify(row, Event.LAPSED, make_site(id=2, name="two"), now=NOW)

        assert sent is True

    async def test_cooldowns_are_per_event(self, notifier: Notifier) -> None:
        row = settings_with()
        site = make_site()

        await notifier.notify(row, Event.LAPSED, site, now=NOW)

        assert await notifier.notify(row, Event.ERRORS, site, "flaky", now=NOW) is True

    async def test_a_test_message_is_never_suppressed(self, notifier: Notifier) -> None:
        row = settings_with()

        await notifier.notify(row, Event.TEST, now=NOW)

        assert await notifier.notify(row, Event.TEST, now=NOW) is True

    async def test_forgetting_a_site_lets_the_next_event_through(self, notifier: Notifier) -> None:
        # Recapturing a session changes the situation; the old cooldown would hide whether
        # the new login actually worked.
        row = settings_with()
        site = make_site(id=7)
        await notifier.notify(row, Event.LAPSED, site, now=NOW)

        notifier.forget(7)

        assert await notifier.notify(row, Event.LAPSED, site, now=NOW) is True

    async def test_forgetting_one_site_leaves_another_alone(self, notifier: Notifier) -> None:
        row = settings_with()
        other = make_site(id=8, name="other")
        await notifier.notify(row, Event.LAPSED, other, now=NOW)

        notifier.forget(7)

        assert await notifier.notify(row, Event.LAPSED, other, now=NOW) is False


class TestMessages:
    def test_a_lapsed_message_says_what_to_do(self) -> None:
        message = build(Event.LAPSED, make_site(name="tracker"), "landed on the login page")

        assert "tracker" in message.title
        assert "log in again" in message.body.lower()
        assert "landed on the login page" in message.body

    def test_a_lapsed_message_without_detail_still_explains_itself(self) -> None:
        message = build(Event.LAPSED, make_site(), None)

        assert "did not accept the stored session" in message.body

    def test_a_recovered_message_says_there_is_nothing_to_do(self) -> None:
        assert "Nothing to do" in build(Event.RECOVERED, make_site()).body

    def test_an_error_message_distinguishes_the_site_from_the_login(self) -> None:
        body = build(Event.ERRORS, make_site(), "503 five times").body

        assert "has not been touched" in body
        assert "503 five times" in body

    def test_an_error_message_without_detail_is_still_sent(self) -> None:
        assert "No further detail" in build(Event.ERRORS, make_site(), None).body

    def test_an_at_risk_message_carries_the_countdown(self) -> None:
        message = build(Event.AT_RISK, make_site(), "the account lapses in 5 day(s)")

        assert "5 day(s)" in message.body

    def test_the_test_message_confirms_the_configuration(self) -> None:
        assert "configured correctly" in build(Event.TEST).body


class TestRedaction:
    def test_hides_the_credentials_in_a_url(self) -> None:
        # An Apprise URL is mostly credential; logging one verbatim writes a working
        # secret into the container log.
        redacted = _redact("tgram://1234567:AAbbCCddEEff/-100987654")

        assert "AAbbCCddEEff" not in redacted
        assert redacted.startswith("tgram://")

    def test_describes_a_url_with_no_scheme(self) -> None:
        assert _redact("not-a-url") == "<malformed url>"

    def test_keeps_a_short_tail_to_tell_destinations_apart(self) -> None:
        assert _redact("mailto://user:secret@example.org").endswith(".org")


class TestAppriseSender:
    async def test_reports_failure_when_no_destination_is_usable(self) -> None:
        # An unparseable URL leaves Apprise with nothing to send to; saying it succeeded
        # would hide a typo in the settings forever.
        assert await AppriseSender().send(["nonsense://x"], "t", "b") is False

    async def test_sends_through_apprise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import apprise

        calls: list[dict[str, str]] = []

        class FakeApprise:
            def __init__(self) -> None:
                self._urls: list[str] = []

            def add(self, url: str) -> bool:
                self._urls.append(url)
                return True

            def __len__(self) -> int:
                return len(self._urls)

            def notify(self, title: str, body: str) -> bool:
                calls.append({"title": title, "body": body})
                return True

        monkeypatch.setattr(apprise, "Apprise", FakeApprise)

        assert await AppriseSender().send(["tgram://a/b"], "title", "body") is True
        assert calls == [{"title": "title", "body": "body"}]
