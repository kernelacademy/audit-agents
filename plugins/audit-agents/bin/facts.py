"""회사 폴더의 사실: 요청 받음 · 빠짐, 받은자료 수, 진행메모 남은 일, 훅 기록."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from paths import LOG, MEMO, case_info


def read_records(case) -> list[dict]:
    p = Path(case) / LOG
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("t") and d.get("kind"):
            out.append(d)
    return out


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# 엔진(director.base_item)이 빠진 자료 글 끝에 붙이는 꼬리: 「(빠진 것: …)」, 「(10~12월분)」 같은 모자란 기간
_TAIL = re.compile(r"( \((빠진 것: [^()]*|[^()]*(월분|월말 기준|결산일 후분))\))+$")
# 엔진(director.period_words)은 「(1~12월)」 을 감사 기간의 달로 바꾼다. 견줄 때는 되돌린다
_MONTHS = re.compile(r"[0-9]{1,2}~[0-9]{1,2}월")


def _item_key(text: str) -> str:
    return _MONTHS.sub("1~12월", _TAIL.sub("", str(text))).strip()


def pbc_counts(case) -> dict:
    """요청 목록(시작자료.json pbc)의 상태별 수.

    시작자료.json 은 엔진의 start 만 다시 쓴다. next 는 문서목록.json 의 missing 만 고치고, 엔진은 그것을
    빠진 자료의 정본으로 본다. 그래서 문서목록.json 에 missing 이 있으면 빠짐은 missing 의 수로 내고,
    start 때 빠짐이던 요청 줄이 missing 에서 사라졌으면 받음으로 센다. missing 에는 요청 줄 말고도
    분석 · 이슈가 낸 요청이 들어 있어, 빠짐이 요청 줄 수보다 클 수 있다."""
    start = _read_json(Path(case) / "_색인" / "시작자료.json")
    if not isinstance(start, dict):
        return {}
    rows = start.get("pbc") or []
    docs = _read_json(Path(case) / "_색인" / "문서목록.json")
    missing = docs.get("missing") if isinstance(docs, dict) else None
    if not isinstance(missing, list):
        return dict(Counter(str(p.get("status")) for p in rows))
    gone = {_item_key(m.get("item", "")) for m in missing if isinstance(m, dict)}
    out = Counter()
    for p in rows:
        status = str(p.get("status"))
        if _item_key(p.get("item", "")) in gone:
            continue                       # 아래에서 missing 수로 센다
        out["받음" if status == "빠짐" else status] += 1
    out["빠짐"] = len(missing)
    return {k: v for k, v in out.items() if v or k == "빠짐"}


def received_files(case) -> int:
    base = Path(case) / "00 받은자료"
    return sum(1 for p in base.rglob("*") if p.is_file() and not p.name.startswith("~$")) if base.is_dir() else 0


def open_items(case) -> list[str]:
    p = Path(case) / MEMO
    if not p.is_file():
        return []
    items, inside = [], False
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## 남은 일"
        elif inside and line.strip().startswith("- [ ]"):
            items.append(line.strip()[5:].strip())
    return items


def case_line(case) -> str:
    info = case_info(case)
    pbc = pbc_counts(case)
    req = f"요청 받음 {pbc.get('받음', 0)} · 빠짐 {pbc.get('빠짐', 0)}" if pbc else "요청 목록 없음"
    return (f"{info['company']} (결산일 {info['fy_end']}) · {req} · 받은자료 {received_files(case)}개 · "
            f"남은 일 {len(open_items(case))}")
