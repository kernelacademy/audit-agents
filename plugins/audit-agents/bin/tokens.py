"""Claude Code 전사(jsonl)의 응답별 usage 를 더한다. 같은 응답이 여러 줄로 나뉘므로 message.id 마다 마지막 줄만 센다.

usd 는 토큰을 API 단가로 환산한 추정값이다. 구독 요금제는 토큰마다 돈을 내지 않으므로 실제 청구액이 아니다.
단가는 prices.json(100만 토큰당 달러)에 있고, 값이 바뀌면 그 파일만 고친다."""
from __future__ import annotations

import json
from pathlib import Path

FIELDS = {"input": "input_tokens", "cache_write": "cache_creation_input_tokens",
          "cache_read": "cache_read_input_tokens", "output": "output_tokens"}
PRICES = json.loads((Path(__file__).with_name("prices.json")).read_text(encoding="utf-8"))
BASIS_USD = 100  # 환산 금액을 견줄 기준: Max 요금제 한 달 요금(대표 지정, 2026-11-13)


def price_of(model: str | None) -> dict:
    """모델 이름으로 단가를 찾는다. 가장 길게 맞는 앞머리를 쓰고, 모르는 모델은 기본 모델 단가로 본다."""
    m = (model or "").lower()
    hits = [k for k in PRICES["models"] if m.startswith(k)]
    return PRICES["models"][max(hits, key=len)] if hits else PRICES["models"][PRICES["default"]]


def usd_of_usage(usage: dict, model: str | None = None) -> float:
    """응답 하나의 usage(API 필드 이름)를 달러로 환산한다. 캐시 쓰기는 5분 1.25배, 1시간 2배."""
    p = price_of(model)
    cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    w1h = int(cc.get("ephemeral_1h_input_tokens") or 0)
    w_all = int(usage.get("cache_creation_input_tokens") or 0)
    w5m = max(w_all - w1h, 0)
    m = PRICES["cache_write_multiplier"]
    return (int(usage.get("input_tokens") or 0) * p["in"]
            + int(usage.get("output_tokens") or 0) * p["out"]
            + int(usage.get("cache_read_input_tokens") or 0) * p["cache_read"]
            + w5m * p["in"] * m["5m"] + w1h * p["in"] * m["1h"]) / 1_000_000


def usd_of_totals(tokens: dict) -> float:
    """기록에 남은 합계(input · cache_write · cache_read · output)를 달러로 환산한다. usd 가 있으면 그 값을 쓴다."""
    if not isinstance(tokens, dict):
        return 0.0
    if isinstance(tokens.get("usd"), (int, float)):
        return float(tokens["usd"])
    return usd_of_usage({src: tokens.get(k, 0) for k, src in FIELDS.items()})


def session_usage(transcript_path) -> dict:
    total = {k: 0 for k in FIELDS}
    if not transcript_path or not Path(transcript_path).is_file():
        return {**total, "total": 0, "usd": 0.0}
    last: dict[str, tuple[dict, str | None]] = {}
    with open(transcript_path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            msg = d.get("message") or {}
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if isinstance(usage, dict):
                last[msg.get("id") or d.get("requestId") or f"줄{n}"] = (usage, msg.get("model"))
    usd = 0.0
    for usage, model in last.values():
        for k, src in FIELDS.items():
            total[k] += int(usage.get(src) or 0)
        usd += usd_of_usage(usage, model)
    return {**total, "total": sum(total.values()), "usd": round(usd, 4)}
