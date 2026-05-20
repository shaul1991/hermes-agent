"""Tests for gateway bot-to-bot loop guard."""

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource


def _runner(monkeypatch, cfg):
    import gateway.run as gateway_run

    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: cfg)
    runner = GatewayRunner.__new__(GatewayRunner)
    runner._bot_loop_guard_state = {}
    return runner


def _event(*, user_id="bot-a", is_bot=True, text="<@bot> your turn"):
    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="channel-1",
        chat_type="group",
        user_id=user_id,
        user_name=user_id,
        is_bot=is_bot,
        guild_id="guild-1",
    )
    return MessageEvent(text=text, source=source)


def test_bot_loop_guard_allows_until_budget_then_returns_one_closeout(monkeypatch):
    runner = _runner(
        monkeypatch,
        {
            "gateway": {
                "group_chat": {
                    "bot_loop_guard": {
                        "enabled": True,
                        "max_rounds": 0,
                        "max_bot_messages_without_human": 2,
                        "max_handoffs": 0,
                        "on_exhausted": "final_summary",
                    }
                }
            }
        },
    )

    assert runner._apply_bot_loop_guard(_event(user_id="bot-a")) is None
    assert runner._apply_bot_loop_guard(_event(user_id="bot-b")) is None

    third = _event(user_id="bot-c")
    response = runner._apply_bot_loop_guard(third)
    assert response is not None
    assert "제한에 도달" in response
    assert getattr(third, "_bot_loop_guard_suppressed") is True

    fourth = _event(user_id="bot-a")
    assert runner._apply_bot_loop_guard(fourth) is None
    assert getattr(fourth, "_bot_loop_guard_suppressed") is True


def test_bot_loop_guard_human_message_resets_budget(monkeypatch):
    runner = _runner(
        monkeypatch,
        {
            "gateway": {
                "group_chat": {
                    "bot_loop_guard": {
                        "enabled": True,
                        "max_rounds": 0,
                        "max_bot_messages_without_human": 1,
                        "max_handoffs": 0,
                    }
                }
            }
        },
    )

    assert runner._apply_bot_loop_guard(_event(user_id="bot-a")) is None
    exhausted = _event(user_id="bot-b")
    assert runner._apply_bot_loop_guard(exhausted) is not None

    human = _event(user_id="human", is_bot=False, text="다시 시작")
    assert runner._apply_bot_loop_guard(human) is None
    assert getattr(human, "_bot_loop_guard_suppressed") is False

    after_reset = _event(user_id="bot-a")
    assert runner._apply_bot_loop_guard(after_reset) is None
    assert getattr(after_reset, "_bot_loop_guard_suppressed") is False


def test_bot_loop_guard_key_ignores_sender_so_handoffs_share_budget(monkeypatch):
    runner = _runner(
        monkeypatch,
        {
            "gateway": {
                "group_chat": {
                    "bot_loop_guard": {
                        "enabled": True,
                        "max_rounds": 0,
                        "max_bot_messages_without_human": 0,
                        "max_handoffs": 2,
                    }
                }
            }
        },
    )

    assert runner._apply_bot_loop_guard(_event(user_id="bot-a")) is None
    assert runner._apply_bot_loop_guard(_event(user_id="bot-b")) is None
    exhausted = _event(user_id="bot-c")
    assert runner._apply_bot_loop_guard(exhausted) is not None

    # One shared conversation state, not one entry per bot sender.
    assert len(runner._bot_loop_guard_state) == 1


def test_bot_loop_guard_hard_stop_from_bot_is_silent(monkeypatch):
    runner = _runner(monkeypatch, {"gateway": {"group_chat": {"bot_loop_guard": {"enabled": True}}}})

    event = _event(user_id="bot-a", text="그만. 봇 침묵")
    assert runner._apply_bot_loop_guard(event) is None
    assert getattr(event, "_bot_loop_guard_suppressed") is True


def test_bot_loop_guard_does_not_apply_to_dms(monkeypatch):
    runner = _runner(monkeypatch, {"gateway": {"group_chat": {"bot_loop_guard": {"enabled": True}}}})
    event = _event(user_id="bot-a")
    event.source.chat_type = "dm"

    assert runner._apply_bot_loop_guard(event) is None
    assert getattr(event, "_bot_loop_guard_suppressed") is False
    assert runner._bot_loop_guard_state == {}
