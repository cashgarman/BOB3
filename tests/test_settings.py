from __future__ import annotations

from pathlib import Path

from bob.settings import Settings, load_settings


def test_settings_defaults():
    s = Settings()
    assert s.llm_model == "qwen3:4b"
    assert s.stt_model == "parakeet-tdt-0.6b-v3"
    assert s.hotkey == "ctrl+shift+space"
    assert s.show_overlay is False
    assert s.tools_enabled is True
    assert s.auto_endpoint is True
    assert s.theme == "midnight"


def test_settings_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "config.yaml"
    s = Settings(llm_model="llama3.1", tts_speed=1.25, theme="ocean", auto_endpoint=True)
    s.theme_overrides = {"accent": "#ff8800"}
    s.save(path)

    loaded = load_settings(path)
    assert loaded.llm_model == "llama3.1"
    assert loaded.tts_speed == 1.25
    assert loaded.theme == "ocean"
    assert loaded.theme_overrides["accent"] == "#ff8800"
    assert loaded.auto_endpoint is True


def test_settings_update_persists(tmp_path: Path):
    path = tmp_path / "config.yaml"
    s = Settings()
    s.save(path)
    s.update(tts_voice="af_bella", show_overlay=False, unknown_field=1)
    # dataclass update() saves to the module default path; persist explicitly for the test file
    s.save(path)
    reloaded = load_settings(path)
    assert reloaded.tts_voice == "af_bella"
    assert reloaded.show_overlay is False


def test_settings_update_normalizes_hotkey(tmp_path: Path):
    path = tmp_path / "config.yaml"
    s = Settings()
    s.save(path)
    s.update(hotkey=" CTRL+Shift+Alt+F5 ")
    s.save(path)
    reloaded = load_settings(path)
    assert reloaded.hotkey == "ctrl+shift+alt+f5"


def test_load_settings_migrates_max_silence(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("max_silence_sec: 1.5\nllm_model: qwen2.5:latest\n", encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.endpoint_silence_ms == 1500
    assert loaded.auto_endpoint is True


def test_load_settings_ignores_unknown_and_bad_overrides(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "llm_model: demo\ntheme_overrides: not-a-dict\nweird: 1\ntts_mood: excited\n",
        encoding="utf-8",
    )
    loaded = load_settings(path)
    assert loaded.llm_model == "demo"
    assert loaded.theme_overrides == {}
    assert loaded.tts_mood == "excited"
