from __future__ import annotations

from unittest.mock import patch

from bob.ui.theme import PRESET_KEYS, PRESETS
from bob.ui.tray import Tray, _icon_image
from bob.voice_mood import MOOD_NAMES
from tests.fakes import FakeApp
from tests.helpers import click_menu, find_menu_item, iter_menu_items


def test_icon_image_fallback_without_file(tmp_path):
    with patch("bob.win32_app.icon_path", return_value=tmp_path / "missing.ico"):
        img = _icon_image()
    assert img.size == (64, 64)
    assert img.mode == "RGBA"


def test_tray_menu_top_actions():
    app = FakeApp()
    tray = Tray(app)
    click_menu(tray, "Open Bob")
    click_menu(tray, "Toggle listen")
    click_menu(tray, "Stop talking")
    click_menu(tray, "New conversation")
    click_menu(tray, "Memories…")
    click_menu(tray, "All settings…")
    click_menu(tray, "Quit")
    assert ("open_main_ui",) in app.calls
    assert ("toggle_listen",) in app.calls
    assert ("stop_speaking",) in app.calls
    assert ("new_chat",) in app.calls
    assert ("open_memories",) in app.calls
    assert ("open_settings",) in app.calls
    assert ("quit",) in app.calls


def test_tray_show_overlay_toggle():
    app = FakeApp()
    app.settings.show_overlay = False
    tray = Tray(app)
    item = find_menu_item(tray.icon.menu, "Show overlay")
    assert item.checked is False
    click_menu(tray, "Show overlay")
    assert ("set_overlay_visible", True) in app.calls


def test_tray_voice_and_model_radios():
    app = FakeApp()
    tray = Tray(app)
    click_menu(tray, "Voice", "TTS voice", "af_bella")
    click_menu(tray, "Voice", "Speech mood", MOOD_NAMES[1])
    click_menu(tray, "Voice", "TTS speed", "1.2×")
    click_menu(tray, "Voice", "Wake word", "alexa")
    click_menu(tray, "Models", "LLM", "qwen2.5:latest")
    click_menu(tray, "Models", "STT model", "medium")
    click_menu(tray, "Models", "Context", "8192")
    click_menu(tray, "Models", "Reconnect Ollama")
    assert ("apply_setting", "tts_voice", "af_bella") in app.calls
    assert ("apply_setting", "tts_mood", MOOD_NAMES[1]) in app.calls
    assert ("apply_setting", "tts_speed", 1.2) in app.calls
    assert ("apply_setting", "wake_word", "alexa") in app.calls
    assert ("apply_setting", "llm_model", "qwen2.5:latest") in app.calls
    assert ("apply_setting", "stt_model", "medium") in app.calls
    assert ("apply_setting", "llm_num_ctx", 8192) in app.calls
    assert ("reconnect_ollama",) in app.calls


def test_tray_bool_items_and_memory_menu():
    app = FakeApp()
    tray = Tray(app)
    click_menu(tray, "Voice", "Auto-endpoint")
    click_menu(tray, "Voice", "Voice barge-in")
    click_menu(tray, "Memory", "Autosave")
    click_menu(tray, "Memory", "Max facts", "12")
    click_menu(tray, "Startup", "Start with Windows")
    assert any(c[:2] == ("apply_setting", "auto_endpoint") for c in app.calls)
    assert any(c[:2] == ("apply_setting", "barge_in") for c in app.calls)
    assert any(c[:2] == ("apply_setting", "memory_autosave") for c in app.calls)
    assert ("apply_setting", "memory_max_inject", 12) in app.calls
    assert any(c[0] == "set_start_with_windows" for c in app.calls)


def test_tray_appearance_presets_and_customize():
    app = FakeApp()
    tray = Tray(app)
    for key in PRESET_KEYS[:3]:
        click_menu(tray, "Appearance", PRESETS[key].title)
        assert ("apply_setting", "theme", key) in app.calls
    click_menu(tray, "Appearance", "Customize…")
    assert ("open_theme",) in app.calls


def test_tray_conversations_submenu():
    sessions = [
        {"id": 3, "title": "Morning chat", "count": 4},
        {"id": 2, "title": "", "count": 0},
    ]
    app = FakeApp(sessions=sessions)
    app._session_id = 3
    tray = Tray(app)
    item = find_menu_item(tray.icon.menu, "Conversations", "Morning chat  (4)")
    assert item.checked is True
    click_menu(tray, "Conversations", "Untitled")
    assert ("load_session", 2) in app.calls


def test_tray_conversations_empty():
    app = FakeApp(sessions=[])
    tray = Tray(app)
    item = find_menu_item(tray.icon.menu, "Conversations", "No saved chats")
    assert item.enabled is False


def test_tray_no_ollama_models():
    app = FakeApp(models=[])
    tray = Tray(app)
    item = find_menu_item(tray.icon.menu, "Models", "LLM", "No Ollama models")
    assert item.enabled is False


def test_tray_refresh_rebuilds_menu():
    app = FakeApp()
    tray = Tray(app)
    app.settings.tts_voice = "bm_george"
    tray.refresh()
    item = find_menu_item(tray.icon.menu, "Voice", "TTS voice", "bm_george")
    assert item.checked is True


def test_tray_notify_no_crash_without_support():
    app = FakeApp()
    tray = Tray(app)
    tray.notify("")
    tray.notify("Hello from tests")
    tray.stop()


def test_tray_menu_contains_expected_sections():
    app = FakeApp()
    tray = Tray(app)
    labels = [item.text for item in iter_menu_items(tray.icon.menu)]
    for needed in ("Open Bob", "Voice", "Models", "Memory", "Startup", "Appearance", "Quit"):
        assert needed in labels
