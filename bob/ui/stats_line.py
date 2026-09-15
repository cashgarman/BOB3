from __future__ import annotations


def format_meter_label(label: str, value: float) -> str:
    return f"{label} {int(round(float(value) * 100))}%"


def format_usage_stats(
    *,
    detail: str = "",
    gpu: float | None = None,
    vram: float | None = None,
    cpu: float | None = None,
    context: float | None = None,
) -> str:
    """Build a compact usage line for toast/overlay footers."""
    parts: list[str] = []
    if detail:
        parts.append(detail)
    stats: list[str] = []
    for value, name in (
        (gpu, "GPU"),
        (vram, "VRAM"),
        (cpu, "CPU"),
        (context, "CONTEXT"),
    ):
        if value is not None:
            stats.append(format_meter_label(name, value))
    if stats:
        parts.append(" · ".join(stats))
    return " · ".join(parts)
