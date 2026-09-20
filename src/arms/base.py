"""The arm interface and its data types."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class ArmConfig:
    """One arm's configuration, loaded from config/arms.json."""

    name: str
    arm_config_id: str
    kind: str
    model: str | None = None
    endpoint: str | None = None
    effort: str | None = None
    max_tokens: int | None = None
    timeout_s: float = 30.0
    role: str = ""

    @classmethod
    def from_json(cls, name: str, blob: dict[str, Any]) -> "ArmConfig":
        known = {f for f in cls.__dataclass_fields__ if f != "name"}
        return cls(name=name, **{k: v for k, v in blob.items() if k in known})


@dataclass
class Timing:
    """Decomposed timings, so a slow model can be told from a slow network."""

    dns_ms: float | None = None
    connect_ms: float | None = None
    tls_ms: float | None = None
    ttfb_ms: float | None = None
    total_ms: float = 0.0


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class Run:
    """One (decision_id, arm, question_set_id, attempt) result.

    Failures are Runs too, with ok=False and an error_kind. Dropping them would
    make attrition invisible, which is exactly how a latency distribution gets
    quietly flattered.
    """

    arm: str
    arm_config_id: str
    ok: bool
    answers: dict[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    timing_ms: Timing = field(default_factory=Timing)
    response_model: str | None = None
    error_kind: str | None = None
    error_detail: str | None = None
    raw: Any = None
    attempt: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArmError(Exception):
    """Raised by an arm when the call fails in a way worth classifying."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map an exception onto a stable error_kind for later attrition analysis."""
    if isinstance(exc, ArmError):
        return exc.kind, exc.detail
    name = type(exc).__name__
    text = str(exc)
    lowered = f"{name} {text}".lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout", text
    if "429" in text or "rate" in lowered and "limit" in lowered:
        return "rate_limit", text
    if "ssl" in lowered or "certificate" in lowered:
        return "tls", text
    if "resolve" in lowered or "nodename" in lowered or "dns" in lowered:
        return "dns", text
    if "refused" in lowered or "unreachable" in lowered or "connection" in lowered:
        return "connection", text
    if "json" in lowered or "decode" in lowered:
        return "malformed_response", text
    return name, text


class Clock:
    """Wall-clock helper. Used instead of bare time.perf_counter() so tests can
    assert on timing without sleeping."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0
