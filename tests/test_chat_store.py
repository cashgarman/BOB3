from __future__ import annotations

from pathlib import Path

from bob.chat_store import ChatStore


def test_chat_store_sessions_and_messages(tmp_path: Path):
    store = ChatStore(tmp_path / "chat.db")
    sid = store.current_session()
    assert sid == store.latest_session_id()

    store.add_message(sid, "user", "Hello there friend")
    store.add_message(sid, "assistant", "Hi!")
    messages = store.list_messages(sid)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "Hello there friend"

    sessions = store.list_sessions()
    assert sessions[0]["id"] == sid
    assert sessions[0]["title"] == "Hello there friend"
    assert sessions[0]["count"] == 2

    other = store.new_session()
    assert other != sid
    assert store.current_session() == other
    store.close()


def test_chat_store_title_only_from_first_user(tmp_path: Path):
    store = ChatStore(tmp_path / "chat.db")
    sid = store.new_session()
    store.add_message(sid, "assistant", "Should not title")
    store.add_message(sid, "user", "Real title that is long " + ("x" * 100))
    store.add_message(sid, "user", "Second user")
    sessions = {row["id"]: row for row in store.list_sessions()}
    assert sessions[sid]["title"].startswith("Real title")
    assert len(sessions[sid]["title"]) <= 80
    store.close()
