from __future__ import annotations

from bob.prompts import PROMPTS_DIR, load_system_prompt, load_tool_guidance


def test_prompt_files_exist():
    assert (PROMPTS_DIR / "system.txt").is_file()
    assert (PROMPTS_DIR / "tool_guidance.txt").is_file()


def test_load_system_prompt():
    text = load_system_prompt()
    assert "Bob" in text
    assert "voice assistant" in text


def test_load_tool_guidance():
    text = load_tool_guidance()
    assert "tools" in text.lower()
    assert "set_speech_mood" in text


def test_system_prompt_reloads_on_each_system_build(tmp_path, monkeypatch):
    from bob.llm import OllamaChat

    monkeypatch.setattr("bob.prompts.PROMPTS_DIR", tmp_path)
    (tmp_path / "system.txt").write_text("Version A", encoding="utf-8")
    (tmp_path / "tool_guidance.txt").write_text("Tool tips", encoding="utf-8")
    llm = OllamaChat("http://localhost", "test", 4096, "ignored", 12)
    assert llm._system() == "Version A"
    assert llm._system(with_tools=True) == "Version A\n\nTool tips"
    (tmp_path / "system.txt").write_text("Version B", encoding="utf-8")
    (tmp_path / "tool_guidance.txt").write_text("Updated tips", encoding="utf-8")
    assert llm._system() == "Version B"
    assert llm._system(with_tools=True) == "Version B\n\nUpdated tips"
