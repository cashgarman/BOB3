from __future__ import annotations

from unittest.mock import patch

import customtkinter as ctk

from bob.settings import Settings
from bob.ui import theme as theming
from bob.ui.memories import MemoriesWindow
from bob.ui.settings_dialog import SettingsDialog, _validate
from bob.ui.theme_dialog import ThemeDialog
from tests.fakes import FakeMemory, ImmediateRecorder, sample_memories
from tests.helpers import find_widget, pump, transcript_text


def test_settings_dialog_loads_current_values(ui):
    settings = Settings(llm_model="qwen2.5:latest", hotkey="ctrl+shift+space", tts_speed=1.2)
    saved = []
    dialog = SettingsDialog(
        ui,
        settings,
        on_save=saved.append,
        llm_models=["qwen2.5:latest", "llama3.1"],
        inputs=["Mic A"],
        outputs=["Speakers"],
        on_open_theme=lambda: None,
    )
    pump(ui)
    assert dialog.vars["llm_model"].get() == "qwen2.5:latest"
    assert dialog.vars["hotkey"].get() == "ctrl+shift+space"
    assert dialog.vars["tts_speed"].get() == "1.2"
    assert dialog.vars["llm_num_ctx"].get() == str(settings.llm_num_ctx)
    assert "BOB" in dialog.prompt.get("1.0", "end")
    assert find_widget(dialog, ctk.CTkButton, text="Customize theme…")
    assert find_widget(dialog, ctk.CTkButton, text="Preview")
    dialog.destroy()


def test_settings_dialog_voice_preview_callback(ui):
    previews = []
    dialog = SettingsDialog(
        ui,
        Settings(),
        on_save=lambda _v: None,
        llm_models=["qwen2.5:latest"],
        inputs=[],
        outputs=[],
        on_preview_voice=lambda voice, speed: previews.append((voice, speed)),
    )
    pump(ui)
    dialog.vars["tts_voice"].set("af_bella")
    dialog.vars["tts_speed"].set("1.1")
    find_widget(dialog, ctk.CTkButton, text="Preview").invoke()
    assert previews == [("af_bella", 1.1)]
    dialog.destroy()


def test_settings_dialog_save_valid_changes(ui):
    settings = Settings()
    saved = []
    dialog = SettingsDialog(
        ui,
        settings,
        on_save=saved.append,
        llm_models=["qwen2.5:latest"],
        inputs=[],
        outputs=[],
    )
    pump(ui)
    dialog.vars["tts_speed"].set("1.4")
    dialog.vars["auto_endpoint"].set(True)
    dialog.vars["llm_num_ctx"].set("4096")
    dialog.prompt.delete("1.0", "end")
    dialog.prompt.insert("1.0", "Be brief.")
    find_widget(dialog, ctk.CTkButton, text="Save").invoke()
    pump(ui)
    assert len(saved) == 1
    assert saved[0]["tts_speed"] == 1.4
    assert saved[0]["auto_endpoint"] is True
    assert saved[0]["system_prompt"] == "Be brief."
    assert not dialog.winfo_exists()


def test_settings_dialog_rejects_out_of_range(ui):
    settings = Settings()
    saved = []
    dialog = SettingsDialog(
        ui,
        settings,
        on_save=saved.append,
        llm_models=["qwen2.5:latest"],
        inputs=[],
        outputs=[],
    )
    pump(ui)
    dialog.vars["tts_speed"].set("9")
    find_widget(dialog, ctk.CTkButton, text="Save").invoke()
    pump(ui)
    assert saved == []
    assert "tts speed" in dialog.error.cget("text").lower()
    dialog.destroy()


def test_settings_dialog_hotkey_capture(ui):
    settings = Settings()
    recording = []
    saved_hotkeys = []
    dialog = SettingsDialog(
        ui,
        settings,
        on_save=lambda _v: None,
        llm_models=["qwen2.5:latest"],
        inputs=[],
        outputs=[],
        on_recording=recording.append,
        on_hotkey_changed=saved_hotkeys.append,
    )
    pump(ui)
    with patch("bob.ui.settings_dialog.HotkeyRecorder", ImmediateRecorder):
        dialog._hotkey_btn.invoke()
        pump(ui)
        assert recording == [True]
        assert "Press any key" in dialog._hotkey_btn.cget("text")
        assert isinstance(dialog._recorder, ImmediateRecorder)
        dialog._recorder.callback("alt+f")
        pump(ui)
        assert dialog.vars["hotkey"].get() == "alt+f"
        assert saved_hotkeys == ["alt+f"]
        assert recording[-1] is False
    dialog._close()
    pump(ui)
    assert saved_hotkeys == ["alt+f", "ctrl+shift+space"]


def test_settings_dialog_save_persists_hotkey_and_llm(ui):
    settings = Settings()
    saved = []
    dialog = SettingsDialog(
        ui,
        settings,
        on_save=saved.append,
        llm_models=["qwen2.5:latest", "llama3.1"],
        inputs=[],
        outputs=[],
    )
    pump(ui)
    dialog.vars["hotkey"].set("alt+f9")
    dialog.vars["llm_model"].set("llama3.1")
    find_widget(dialog, ctk.CTkButton, text="Save").invoke()
    pump(ui)
    assert len(saved) == 1
    assert saved[0]["hotkey"] == "alt+f9"
    assert saved[0]["llm_model"] == "llama3.1"
    assert not dialog.winfo_exists()


def test_settings_dialog_refresh_llm_models_keeps_user_pick(ui):
    settings = Settings(llm_model="qwen2.5:latest")
    dialog = SettingsDialog(
        ui,
        settings,
        on_save=lambda _v: None,
        llm_models=["qwen2.5:latest", "llama3.1"],
        inputs=[],
        outputs=[],
    )
    pump(ui)
    dialog.vars["llm_model"].set("llama3.1")
    dialog.refresh_llm_models(["qwen2.5:latest", "llama3.1", "mistral"])
    assert dialog.vars["llm_model"].get() == "llama3.1"
    dialog.destroy()


def test_settings_dialog_open_theme_callback(ui):
    opened = []
    dialog = SettingsDialog(
        ui,
        Settings(),
        on_save=lambda _v: None,
        llm_models=["qwen2.5:latest"],
        inputs=[],
        outputs=[],
        on_open_theme=lambda: opened.append(True),
    )
    pump(ui)
    find_widget(dialog, ctk.CTkButton, text="Customize theme…").invoke()
    assert opened == [True]
    dialog.destroy()


def test_settings_validate_ranges_and_hotkey():
    bad = _validate({"tts_speed": 3.0, "llm_num_ctx": 10, "hotkey": "not-a-key"})
    assert any("tts speed" in m for m in bad)
    assert any("llm num ctx" in m for m in bad)
    assert any("Unknown hotkey" in m or "hotkey" in m.lower() for m in bad)

    good = _validate({"tts_speed": 1.0, "llm_num_ctx": 4096, "hotkey": "ctrl+shift+space"})
    assert good == []


def test_theme_dialog_preview_and_save(ui):
    settings = Settings(theme="midnight")
    previews = []
    saved = []

    dialog = ThemeDialog(
        ui,
        settings,
        on_preview=previews.append,
        on_save=saved.append,
    )
    pump(ui)
    assert dialog.preset_var.get() == "Midnight"
    assert "LISTENING" in dialog.preview_status.cget("text")

    dialog.preset_box.set("Ocean")
    dialog._preset_changed("Ocean")
    pump(ui)
    assert dialog._preset_key == "ocean"
    assert previews[-1].key == "ocean" or previews[-1].accent == theming.preset("ocean").accent

    dialog._hex_vars["accent"].set("#ff8800")
    dialog._hex_typed("accent")
    pump(ui)
    assert dialog._draft.accent == "#ff8800"

    find_widget(dialog, ctk.CTkButton, text="Save").invoke()
    pump(ui)
    assert len(saved) == 1
    assert saved[0]["theme"] == "ocean"
    assert saved[0]["theme_overrides"].get("accent") == "#ff8800"
    assert not dialog.winfo_exists()


def test_theme_dialog_cancel_reverts(ui):
    settings = Settings(theme="midnight")
    previews = []
    dialog = ThemeDialog(ui, settings, on_preview=previews.append, on_save=lambda _v: None)
    pump(ui)
    dialog._preset_changed("Ember")
    pump(ui)
    find_widget(dialog, ctk.CTkButton, text="Cancel").invoke()
    pump(ui)
    assert previews[-1].key == "midnight" or previews[-1].accent == theming.preset("midnight").accent
    assert not dialog.winfo_exists()


def test_theme_dialog_reset_to_preset(ui):
    settings = Settings(theme="forest")
    dialog = ThemeDialog(ui, settings, on_preview=lambda _t: None, on_save=lambda _v: None)
    pump(ui)
    dialog._hex_vars["accent"].set("#112233")
    dialog._hex_typed("accent")
    find_widget(dialog, ctk.CTkButton, text="Reset to preset").invoke()
    pump(ui)
    assert dialog._draft.accent == theming.preset("forest").accent
    dialog.destroy()


def test_memories_window_list_search_edit_toggle_delete(ui):
    memory = FakeMemory(sample_memories())
    autosave_calls = []
    win = MemoriesWindow(
        ui,
        rows_provider=memory.list_memories,
        on_toggle=memory.set_enabled,
        on_edit=memory.edit,
        on_delete=memory.delete,
        on_forget_all=memory.forget_all,
        autosave=True,
        on_autosave=lambda on: autosave_calls.append(on),
    )
    pump(ui)
    buttons = [w for w in win.listbox.winfo_children() if isinstance(w, ctk.CTkButton)]
    assert len(buttons) == 3

    win.search.insert(0, "portland")
    win.refresh()
    pump(ui)
    buttons = [w for w in win.listbox.winfo_children() if isinstance(w, ctk.CTkButton)]
    assert len(buttons) == 1
    assert "Portland" in buttons[0].cget("text")

    buttons[0].invoke()
    pump(ui)
    assert win._selected == "b2"
    win.editor.delete("1.0", "end")
    win.editor.insert("1.0", "Lives in Seattle")
    find_widget(win, ctk.CTkButton, text="Save edit").invoke()
    assert memory.edited == [("b2", "Lives in Seattle")]

    find_widget(win, ctk.CTkButton, text="Enable/disable").invoke()
    assert memory.toggled == [("b2", True)]

    find_widget(win, ctk.CTkButton, text="Delete").invoke()
    assert memory.deleted == ["b2"]
    assert win._selected is None

    win.auto.set(False)
    win._auto()
    assert autosave_calls == [False]
    win.destroy()


def test_memories_forget_all_confirms(ui):
    memory = FakeMemory(sample_memories())
    win = MemoriesWindow(
        ui,
        rows_provider=memory.list_memories,
        on_toggle=memory.set_enabled,
        on_edit=memory.edit,
        on_delete=memory.delete,
        on_forget_all=memory.forget_all,
        autosave=True,
        on_autosave=lambda _on: None,
    )
    pump(ui)
    with patch("tkinter.messagebox.askyesno", return_value=True):
        find_widget(win, ctk.CTkButton, text="Forget all").invoke()
    assert memory.forgot == 1
    assert memory.rows == []
    win.destroy()


def test_memories_forget_all_cancel(ui):
    memory = FakeMemory(sample_memories())
    win = MemoriesWindow(
        ui,
        rows_provider=memory.list_memories,
        on_toggle=memory.set_enabled,
        on_edit=memory.edit,
        on_delete=memory.delete,
        on_forget_all=memory.forget_all,
        autosave=True,
        on_autosave=lambda _on: None,
    )
    pump(ui)
    with patch("tkinter.messagebox.askyesno", return_value=False):
        find_widget(win, ctk.CTkButton, text="Forget all").invoke()
    assert memory.forgot == 0
    assert len(memory.rows) == 3
    win.destroy()
