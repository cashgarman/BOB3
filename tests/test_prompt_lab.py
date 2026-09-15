from __future__ import annotations

from bob.prompt_lab.graph import maybe_improve_prompt, maybe_rollback
from bob.prompt_lab.scorer import heuristic_scores, parse_score_json
from bob.prompt_lab.versioning import (
    apply_prompt,
    load_state,
    prompt_preserves_spoken_style,
    rollback_prompt,
    snapshot_current,
)


GOOD_PROMPT = (
    "You are BOB, a local voice assistant. Speak in two or three natural sentences "
    "meant to be heard aloud. No markdown or bullet lists unless asked."
)
BETTER_PROMPT = (
    "You are BOB, a local voice assistant. Speak in two or three natural sentences "
    "meant to be heard aloud. Lead with the answer. No markdown or bullet lists unless asked."
)


def test_heuristic_scores_and_parse():
    good = heuristic_scores("Russia is the largest country by area.", "What's the biggest country?")
    bad = heuristic_scores("Okay, the user is asking for the time. Let me think.", "What time is it?")
    assert good["overall"] > bad["overall"]
    parsed = parse_score_json('{"spoken_quality": 0.9, "grounding": 0.8, "overall": 0.85, "leak_risk": 0.1}')
    assert parsed["overall"] == 0.85


def test_prompt_style_lint():
    assert prompt_preserves_spoken_style(GOOD_PROMPT)
    assert not prompt_preserves_spoken_style("You are a helpful assistant.")


def test_apply_and_rollback(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "system.txt").write_text(GOOD_PROMPT + "\n", encoding="utf-8")
    monkeypatch.setattr("bob.prompt_lab.versioning.PROMPTS_DIR", prompts)
    monkeypatch.setattr("bob.prompts.PROMPTS_DIR", prompts)
    snapshot_current(tmp_path)
    apply_prompt(BETTER_PROMPT, score=0.9, data_dir=tmp_path)
    assert "Lead with the answer" in (prompts / "system.txt").read_text(encoding="utf-8")
    rolled = rollback_prompt(cooldown_hours=1, data_dir=tmp_path)
    assert rolled is not None
    assert rolled.pinned is True
    assert "Lead with the answer" not in (prompts / "system.txt").read_text(encoding="utf-8")


def test_shadow_eval_rejects_worse_prompt(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "system.txt").write_text(GOOD_PROMPT + "\n", encoding="utf-8")
    monkeypatch.setattr("bob.prompt_lab.versioning.PROMPTS_DIR", prompts)
    monkeypatch.setattr("bob.prompts.PROMPTS_DIR", prompts)
    transcripts = [("What's 2 plus 2?", "4", 0.9)] * 30

    def generate(instruction, user_text, num_predict=256):
        if "Lead with" in (user_text + instruction) or instruction.startswith("You are BOB") and "Lead" in instruction:
            return "Okay, the user is asking a question and I should plan the answer."
        if "rewrite" in instruction.lower() or "scored voice" in instruction.lower():
            return BETTER_PROMPT
        return "Four."

    result = maybe_improve_prompt(
        generate=generate,
        transcripts=transcripts,
        holdout=[("What's 2 plus 2?", "4")],
        min_turns=30,
        min_improve=0.05,
        auto_improve=True,
        data_dir=tmp_path,
    )
    assert result["applied"] is False


def test_auto_apply_when_shadow_score_improves(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "system.txt").write_text(GOOD_PROMPT + "\n", encoding="utf-8")
    monkeypatch.setattr("bob.prompt_lab.versioning.PROMPTS_DIR", prompts)
    monkeypatch.setattr("bob.prompts.PROMPTS_DIR", prompts)
    transcripts = [("Hello", "Hi there, I can help.", 0.6)] * 30

    def generate(instruction, user_text, num_predict=256):
        blob = f"{instruction}\n{user_text}"
        if "scored voice" in blob.lower() or "rewrite" in instruction.lower():
            return BETTER_PROMPT
        if "Lead with the answer" in instruction:
            return "Hi there. I can help with that."
        return "Okay, the user is asking something. Let me think about tools."

    result = maybe_improve_prompt(
        generate=generate,
        transcripts=transcripts,
        holdout=[("Hello", "Hi there, I can help.")],
        min_turns=30,
        min_improve=0.05,
        auto_improve=True,
        data_dir=tmp_path,
    )
    assert result.get("applied") is True
    assert "Lead with the answer" in (prompts / "system.txt").read_text(encoding="utf-8")


def test_rollback_when_live_window_drops(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "system.txt").write_text(GOOD_PROMPT + "\n", encoding="utf-8")
    monkeypatch.setattr("bob.prompt_lab.versioning.PROMPTS_DIR", prompts)
    monkeypatch.setattr("bob.prompts.PROMPTS_DIR", prompts)
    snapshot_current(tmp_path)
    apply_prompt(BETTER_PROMPT, score=0.9, data_dir=tmp_path)
    dropped = [{"overall": 0.5, "leak_risk": 0.0} for _ in range(8)]
    assert maybe_rollback(dropped, rollback_delta=0.08, cooldown_hours=1, data_dir=tmp_path)
    state = load_state(tmp_path)
    assert state.pinned is True
    assert state.current_version == 1
