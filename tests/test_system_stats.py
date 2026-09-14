from __future__ import annotations

import subprocess

from bob.system_stats import UsageSampler, _nvidia_smi_usage, _nvidia_usage


def test_nvidia_usage_parses_csv(monkeypatch):
    def fake_check_output(cmd, **kwargs):
        assert "utilization.gpu" in " ".join(cmd)
        assert kwargs.get("creationflags") in {None, getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), 0x08000000}
        return "42, 6144, 12288"

    monkeypatch.setattr("bob.system_stats._nvml_usage", lambda: (None, None))
    monkeypatch.setattr("bob.system_stats.subprocess.check_output", fake_check_output)
    gpu, vram, source = _nvidia_usage()
    assert source == "nvidia-smi"
    assert gpu == 0.42
    assert abs(vram - 0.5) < 1e-6


def test_nvidia_smi_hides_console(monkeypatch):
    seen = {}

    def fake_check_output(cmd, **kwargs):
        seen.update(kwargs)
        return "10, 1, 2"

    monkeypatch.setattr("bob.system_stats.subprocess.check_output", fake_check_output)
    gpu, vram = _nvidia_smi_usage()
    assert gpu == 0.1
    assert seen.get("creationflags") in {
        getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        0x08000000,
    }
    assert seen.get("startupinfo") is not None


def test_sampler_throttles(monkeypatch):
    monkeypatch.setattr("bob.system_stats._nvidia_usage", lambda: (0.1, 0.2, "nvml"))
    monkeypatch.setattr("bob.system_stats._cpu_usage", lambda _s: 0.3)
    sampler = UsageSampler(interval_sec=10.0)
    first = sampler.sample()
    second = sampler.sample()
    assert first == second
    assert first.gpu == 0.1
    assert first.vram == 0.2
    assert first.cpu == 0.3
