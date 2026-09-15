from __future__ import annotations

from bob.llm_recommend import CATALOG, GpuInfo, recommend_llm


def test_no_gpu_picks_smallest():
    rec = recommend_llm(gpu=GpuInfo(name=None, total_vram_mb=None))
    assert rec.recommended == "qwen2.5:1.5b"
    assert rec.free_for_llm_mb is None
    assert rec.choice_fits("qwen2.5:1.5b")
    assert not rec.choice_fits("qwen3:4b")
    assert "No NVIDIA GPU" in rec.reason


def test_10gb_recommends_qwen3_4b():
    rec = recommend_llm(gpu=GpuInfo(name="RTX 3080", total_vram_mb=10240))
    assert rec.recommended == "qwen3:4b"
    assert rec.choice_fits("qwen3:4b")
    assert rec.choice_fits("qwen2.5:3b")
    assert not rec.choice_fits("qwen3:8b")
    assert "10 GB" in rec.reason
    assert "RTX 3080" in rec.reason


def test_8gb_recommends_3b():
    rec = recommend_llm(total_vram_mb=8192)
    assert rec.recommended == "qwen2.5:3b"


def test_6gb_recommends_1_5b():
    rec = recommend_llm(total_vram_mb=6144)
    assert rec.recommended == "qwen2.5:1.5b"


def test_16gb_recommends_8b():
    rec = recommend_llm(total_vram_mb=16384)
    assert rec.recommended == "qwen3:8b"
    assert all(item.fits(16384) for item in CATALOG)
