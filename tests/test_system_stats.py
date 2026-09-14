from __future__ import annotations

from bob.system_stats import UsageSampler, _nvidia_usage


def test_nvidia_usage_parses_csv(monkeypatch):
    def fake_check_output(cmd, **kwargs):
        assert "utilization.gpu" in " ".join(cmd)
        return "42, 6144, 12288"

    monkeypatch.setattr("bob.system_stats.subprocess.check_output", fake_check_output)
    gpu, vram = _nvidia_usage()
    assert gpu == 0.42
    assert abs(vram - 0.5) < 1e-6


def test_sampler_throttles(monkeypatch):
    monkeypatch.setattr("bob.system_stats._nvidia_usage", lambda: (0.1, 0.2))
    monkeypatch.setattr("bob.system_stats._cpu_usage", lambda _s: 0.3)
    sampler = UsageSampler(interval_sec=10.0)
    first = sampler.sample()
    second = sampler.sample()
    assert first == second
    assert first.gpu == 0.1
    assert first.vram == 0.2
    assert first.cpu == 0.3
