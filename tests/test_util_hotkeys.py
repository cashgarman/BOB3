from __future__ import annotations

from bob.hotkeys import parse_hotkey
from bob.util import split_sentences, split_speakable


def test_parse_hotkey_modifiers_and_keys():
    mods, vk = parse_hotkey("ctrl+shift+space")
    assert mods != 0
    assert vk == 0x20
    mods2, vk2 = parse_hotkey("alt+a")
    assert vk2 == ord("A")
    assert mods2 != mods


def test_parse_hotkey_rejects_bad():
    import pytest

    with pytest.raises(ValueError):
        parse_hotkey("ctrl+")
    with pytest.raises(ValueError):
        parse_hotkey("ctrl+notakey")


def test_split_sentences_and_abbreviations():
    done, rest = split_sentences("Hello there. More")
    assert done == ["Hello there."]
    assert rest == "More"

    done, rest = split_sentences("Dr. Smith arrived. Done")
    assert any("Smith arrived." in s for s in done)
    assert rest == "Done"


def test_split_speakable_first_clause():
    pieces, rest = split_speakable("This is a longer clause, then more text.", first=True)
    assert pieces
    assert pieces[0].endswith(",") or "." in "".join(pieces)
    full = " ".join(pieces + ([rest] if rest else [])).replace("  ", " ")
    assert "clause" in full
