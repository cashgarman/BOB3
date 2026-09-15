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
    assert sessions[0]["title"] == ""
    assert sessions[0]["count"] == 2
    assert store.session_message_count(sid) == 2
    assert store.session_title_generated(sid) is False

    other = store.new_session()
    assert other != sid
    assert store.current_session() == other
    store.close()


def test_chat_store_does_not_auto_title_from_user(tmp_path: Path):
    store = ChatStore(tmp_path / "chat.db")
    sid = store.new_session()
    store.add_message(sid, "user", "Real title that is long " + ("x" * 100))
    store.add_message(sid, "assistant", "ok")
    assert store.session_title(sid) == ""
    store.close()


def test_chat_store_update_title_and_updated_at_order(tmp_path: Path):
    store = ChatStore(tmp_path / "chat.db")
    older = store.new_session()
    newer = store.new_session()
    store.add_message(older, "user", "first")
    store.update_session_title(older, "Older chat", generated=True)
    store.add_message(newer, "user", "second")
    with store._lock:
        store._conn.execute("UPDATE sessions SET updated_at = '2026-01-01 00:00:00' WHERE id = ?", (newer,))
        store._conn.execute("UPDATE sessions SET updated_at = '2026-01-02 00:00:00' WHERE id = ?", (older,))
        store._conn.commit()
    sessions = store.list_sessions()
    assert [row["id"] for row in sessions][:2] == [older, newer]
    assert sessions[0]["title"] == "Older chat"
    assert sessions[0]["title_generated"] is True
    store.close()
