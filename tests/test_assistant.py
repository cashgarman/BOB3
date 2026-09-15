from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from bob.settings import Settings
from bob.state import State


def _make_assistant(tmp_path: Path, monkeypatch):
    """Build Assistant with heavy subsystems mocked so UI wiring can be tested."""
    monkeypatch.setattr("bob.app.DATA_DIR", tmp_path)
    monkeypatch.setattr("bob.app.MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr("bob.app.startup_is_enabled", lambda: False)
    monkeypatch.setattr("bob.app.startup_set_enabled", lambda enabled: bool(enabled))

    audio = MagicMock()
    audio.level = 0.0
    audio.is_listening = False
    audio.waveform_bars.return_value = np.zeros(8)

    stt = MagicMock()
    stt.model_name = "parakeet-tdt-0.6b-v3"
    stt.device = "cpu"
    stt.compute_type = "int8"
    stt._model = object()

    tts = MagicMock()
    tts.voice = "af_heart"
    tts.speed = 1.0
    tts.set_mood = MagicMock(return_value="neutral")

    stt_stream = MagicMock()
    stt_stream.total_samples = 16000
    stt_stream.finalize.return_value = "spoken text"

    speech = MagicMock()
    speech.mood = "neutral"
    speech.set_mood.side_effect = lambda m: setattr(speech, "mood", m) or m
    speech.begin.return_value = 1

    llm = MagicMock()
    llm.host = "http://127.0.0.1:11434"
    llm.model = "qwen3:4b"
    llm.history = []
    llm.last_internal_thought = ""
    llm.chat.return_value = iter(["Hello ", "world."])
    llm.list_models.return_value = [{"name": "qwen3:4b", "size": 1}]

    wake = MagicMock()
    wake.enabled = True
    wake.error = None
    wake.model_name = "hey_jarvis"

    endpointer = MagicMock()
    endpointer.feed.return_value = SimpleNamespace(
        in_speech=False, speech_ms=0, heard_speech=False, silence_ms=0
    )
    endpointer.take_speech_seed.return_value = None

    turn = MagicMock()
    turn_gate = MagicMock()

    class FakeMemory:
        def __init__(self, root):
            self.root = root
            self.ready = True
            self.embedder = SimpleNamespace(dim=8)

        def load(self):
            return None

        def retrieve(self, query, limit=8):
            return ""

        def list_memories(self):
            return []

        def ingest(self, *a, **k):
            return []

    class FakeTools:
        def __init__(self, *a, **k):
            self.errors = []

        def load(self):
            return []

        def load_mcp(self, *a, **k):
            return []

        def names(self):
            return ["get_current_time"]

        def schemas(self):
            return []

        def close_mcp(self):
            return None

        def close(self):
            return None

        def context(self, **k):
            return SimpleNamespace()

        def invoke(self, *a, **k):
            return "ok"

    monkeypatch.setattr("bob.app.AudioHub", lambda **k: audio)
    monkeypatch.setattr("bob.app.create_speech_to_text", lambda *a, **k: stt)
    monkeypatch.setattr("bob.app.TextToSpeech", lambda *a, **k: tts)
    monkeypatch.setattr("bob.app.StreamingTranscriber", lambda *a, **k: stt_stream)
    monkeypatch.setattr("bob.app.SpeechStreamer", lambda *a, **k: speech)
    monkeypatch.setattr("bob.app.OllamaChat", lambda *a, **k: llm)
    monkeypatch.setattr("bob.app.WakeWordDetector", lambda *a, **k: wake)
    monkeypatch.setattr("bob.app.Endpointer", lambda **k: endpointer)
    monkeypatch.setattr("bob.app.SmartTurn", lambda **k: turn)
    monkeypatch.setattr("bob.app.TurnGate", lambda **k: turn_gate)
    monkeypatch.setattr("bob.app.MemoryService", FakeMemory)
    monkeypatch.setattr("bob.app.ToolRegistry", FakeTools)
    monkeypatch.setattr(
        "bob.app.GlobalHotkey",
        lambda spec, cb: SimpleNamespace(spec=spec, error=None, start=lambda: None, stop=lambda: None),
    )

    from bob.app import Assistant

    settings = Settings(show_overlay=True)
    assistant = Assistant(settings)
    assistant.audio = audio
    assistant.stt = stt
    assistant.tts = tts
    assistant.stt_stream = stt_stream
    assistant.speech = speech
    assistant.llm = llm
    assistant.wake = wake
    assistant._listen_endpointer = endpointer
    assistant._barge_endpointer = endpointer
    return assistant, audio, stt_stream, speech, llm


def test_assistant_toggle_listen_and_submit_text(ui, tmp_path, monkeypatch):
    assistant, audio, stt_stream, speech, llm = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant.tray = None
    assistant.state = State.IDLE
    assistant._ui = lambda fn: fn()

    started = []
    assistant._start_pipeline = lambda typed_text=None: started.append(typed_text)

    assistant.toggle_listen()
    assert assistant.state == State.LISTENING
    audio.start_listening.assert_called()
    stt_stream.start_turn.assert_called()

    assistant._last_toggle = 0.0
    assistant.toggle_listen()
    assert assistant.state == State.THINKING
    audio.stop_listening.assert_called()
    assert started == [None]

    started.clear()
    assistant.state = State.IDLE
    assistant._last_toggle = 0.0
    assistant.submit_text("  typed hello  ")
    assert assistant.state == State.THINKING
    assert started == ["typed hello"]
    assert assistant._pending_user == "typed hello"


def test_assistant_stop_speaking(ui, tmp_path, monkeypatch):
    assistant, audio, stt_stream, speech, llm = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant._ui = lambda fn: fn()
    assistant.state = State.SPEAKING
    assistant._pending_reply = "Partial answer here."
    assistant._turns = [{"role": "user", "content": "Question?"}]
    assistant.stop_speaking()
    assert assistant.state == State.IDLE
    speech.cancel.assert_called()
    assert assistant._turns[-1] == {"role": "assistant", "content": "Partial answer here."}


def test_assistant_interrupt_listen_preserves_partial_reply(ui, tmp_path, monkeypatch):
    assistant, audio, stt_stream, speech, llm = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant._ui = lambda fn: fn()
    assistant.state = State.SPEAKING
    assistant._pending_reply = "The weather today is sunny and"
    assistant._turns = [{"role": "user", "content": "What's the weather?"}]
    assistant._last_toggle = 0.0
    assistant.toggle_listen()
    assert assistant.state == State.LISTENING
    assert assistant._turns[-1] == {
        "role": "assistant",
        "content": "The weather today is sunny and",
    }
    audio.start_listening.assert_called()


def test_start_speech_mutes_capture_even_with_barge_in(ui, tmp_path, monkeypatch):
    assistant, audio, *_ = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant._ui = lambda fn: fn()
    assistant.settings.barge_in = True
    assistant._start_speech()
    audio.set_capture_muted.assert_called_with(True)
    assert assistant._barge_armed is False
    assert assistant.state == State.SPEAKING


def test_assistant_new_chat_and_load_session(ui, tmp_path, monkeypatch):
    assistant, *_ = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant.tray = MagicMock()
    assistant._ui = lambda fn: fn()
    assistant.state = State.IDLE

    first = assistant._session_id
    assistant.chat.add_message(first, "user", "old")
    assistant._turns = [{"role": "user", "content": "old"}]
    assistant._new_chat()
    assert assistant._session_id != first
    assert assistant._turns == []
    assert assistant._pending_reply == "New conversation."

    empty = assistant._session_id
    assistant._new_chat()
    assert assistant._session_id == empty

    other = assistant.chat.new_session()
    assistant.chat.add_message(other, "user", "from history")
    assistant.load_session(other)
    assert assistant._session_id == other
    assert assistant._turns[0]["content"] == "from history"
    assistant.tray.refresh.assert_called()


def test_assistant_generates_title_after_first_exchange(ui, tmp_path, monkeypatch):
    assistant, *_ = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant.tray = MagicMock()
    assistant._ui = lambda fn: fn()
    assistant.state = State.IDLE

    class ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False, name=""):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr("bob.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("bob.session_title.generate_session_title", lambda *a, **k: "BBC Headlines")
    assistant._commit_turn("user", "What's on the BBC?")
    assistant._commit_turn("assistant", "Here are today's headlines.")
    assert assistant.chat.session_title(assistant._session_id) == "BBC Headlines"
    assert assistant.chat.session_title_generated(assistant._session_id) is True


def test_assistant_apply_setting_live_fields(ui, tmp_path, monkeypatch):
    assistant, audio, stt_stream, speech, llm = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant.tray = MagicMock()
    assistant._ui = lambda fn: fn()
    assistant._restart_hotkey = MagicMock()
    assistant._configure_streaming = MagicMock()
    assistant._reload_wake_word = MagicMock()
    assistant._preload_safe = MagicMock()

    with patch.object(assistant.settings, "save"):
        assistant.apply_setting("tts_voice", "af_bella")
        assert assistant.settings.tts_voice == "af_bella"
        assert assistant.tts.voice == "af_bella"

        assistant.apply_setting("tts_mood", "excited")
        speech.set_mood.assert_called_with("excited")

        assistant.apply_setting("show_overlay", False)
        assert assistant.settings.show_overlay is False

        assistant.apply_setting("stt_model", "small")
        assert assistant.settings.stt_model == "small"

        assistant.apply_setting("hotkey", "ctrl+shift+alt+f5")
        assert assistant.settings.hotkey == "ctrl+shift+alt+f5"
        assistant._restart_hotkey.assert_called()


def test_assistant_apply_settings_dict_theme(ui, tmp_path, monkeypatch):
    assistant, *_ = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant.tray = MagicMock()
    assistant._ui = lambda fn: fn()
    assistant._restart_hotkey = MagicMock()
    assistant._configure_streaming = MagicMock()
    assistant.set_overlay_visible = MagicMock()
    assistant.set_start_with_windows = MagicMock()
    assistant.apply_theme = MagicMock()

    with patch.object(assistant.settings, "save"):
        assistant.apply_settings_dict(
            {
                "theme": "ocean",
                "auto_endpoint": True,
                "endpoint_silence_ms": 800,
                "tts_speed": 1.1,
            }
        )
    assert assistant.settings.theme == "ocean"
    assert assistant.settings.max_silence_sec == 0.8
    assistant.apply_theme.assert_called()


def test_opening_overlay_syncs_current_state(ui, tmp_path, monkeypatch):
    from tests.helpers import pump

    assistant, *_ = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant.tray = MagicMock()
    assistant._ui = lambda fn: fn()
    assistant.state = State.IDLE
    assistant._state_detail = "ready"
    assistant.settings.show_overlay = False
    ui.set_user_visible(False)
    ui.set_state(State.LOADING)
    pump(ui.master, 2)
    assert ui.status.cget("text") == "LOADING"

    assistant.set_overlay_visible(True, persist=False)
    pump(ui.master, 3)
    assert ui.is_user_visible() is True
    assert ui.status.cget("text") == "IDLE"
    from bob.ui.listen_toast import ListenToast
    from tests.helpers import pump

    assistant, *_ = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    toast = ListenToast(ui.master)
    pump(ui, 3)
    assistant.toast = toast
    assistant._ui = lambda fn: fn()

    assistant._set_state(State.LISTENING, "speak")
    pump(ui)
    assert toast.is_open() is True
    assert toast.status.cget("text") == "LISTENING"

    assistant._set_state(State.IDLE, "ready")
    pump(ui)
    assert toast.is_open() is False
    toast.destroy()


def test_assistant_set_state_keeps_pinned_toast_on_idle(ui, tmp_path, monkeypatch):
    from bob.ui.listen_toast import ListenToast
    from tests.helpers import pump

    assistant, *_ = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    toast = ListenToast(ui.master)
    pump(ui, 3)
    assistant.toast = toast
    assistant._ui = lambda fn: fn()

    assistant._set_state(State.SPEAKING, "reply")
    pump(ui)
    toast._toggle_pin()

    assistant._set_state(State.IDLE, "ready")
    pump(ui)
    assert toast.is_open() is True
    assert toast.status.cget("text") == "IDLE"
    toast.destroy()


def test_assistant_pipeline_typed_path(ui, tmp_path, monkeypatch):
    assistant, audio, stt_stream, speech, llm = _make_assistant(tmp_path, monkeypatch)
    assistant.overlay = ui
    assistant.hud = None
    assistant.toast = None
    assistant._ui = lambda fn: fn()
    assistant.state = State.THINKING
    cancel = threading.Event()

    assistant._pipeline(cancel, typed_text="Say hi")
    assert any(t["role"] == "user" and t["content"] == "Say hi" for t in assistant._turns)
    assert any(t["role"] == "assistant" and "Hello" in t["content"] for t in assistant._turns)
    speech.feed.assert_called()
    speech.finish.assert_called()
    assert assistant.state == State.IDLE


def test_load_toast_text_mapping():
    from bob.app import _load_toast_text

    assert _load_toast_text("Ollama") == "Checking Ollama…"
    assert _load_toast_text("Speech recognition") == "Loading speech recognition…"
    assert _load_toast_text("Custom status") == "Custom status"
    assert _load_toast_text("") == ""


def test_run_check_uses_create_speech_to_text():
    root = Path(__file__).resolve().parent.parent
    src = (root / "bob" / "app.py").read_text(encoding="utf-8")
    start = src.index("def run_check")
    body = src[start:]
    assert "create_speech_to_text(" in body
    before_fallback = body.split("from bob.stt import SpeechToText", 1)[0]
    assert "stt = SpeechToText(" not in before_fallback


def test_notify_ready_sends_silent_os_toast(tmp_path, monkeypatch):
    from bob.app import Assistant
    from bob.settings import Settings

    sent: list[tuple[str, str, bool, bool, str | None]] = []

    def capture(msg, title="BOB is loading", *, replace=True, silent=False, tag=None):
        sent.append((title, msg, silent, replace, tag))
        return True

    monkeypatch.setattr("bob.os_toast.show", capture)
    assistant = Assistant(settings=Settings())
    assistant._notify_ready("CTRL+SHIFT+SPACE · qwen3:4b")
    assistant._notify_ready("ignored")
    assert len(sent) == 1
    assert sent[0][0] == "BOB is ready"
    assert "Press" in sent[0][1]
    assert "CTRL+SHIFT+SPACE" in sent[0][1]
    assert sent[0][2] is True
    assert sent[0][3] is False
    assert sent[0][4] == "bob-ready"
    assert assistant._ready_toast_sent is True


def test_notify_ready_falls_back_to_tray_when_os_toast_fails(monkeypatch):
    from bob.app import Assistant
    from bob.settings import Settings

    tray_calls: list[tuple[str, str]] = []

    class FakeTray:
        def notify(self, message: str, title: str = "BOB") -> None:
            tray_calls.append((title, message))

    monkeypatch.setattr("bob.os_toast.show", lambda *args, **kwargs: False)
    assistant = Assistant(settings=Settings())
    assistant.tray = FakeTray()
    assistant._notify_ready("CTRL+SHIFT+SPACE · qwen3:4b")
    assert len(tray_calls) == 1
    assert tray_calls[0][0] == "BOB is ready"
    assert "Press" in tray_calls[0][1]
    assert assistant._ready_toast_sent is True
