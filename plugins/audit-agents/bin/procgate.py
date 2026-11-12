"""회사 폴더에서 4000 영역 조서 설계 · 초안(md)을 쓰면 절차점검 검사를 돌리고, 문제를 대화에 넣을 글로 돌려준다.

규칙 파일에 「끝내기 전에 절차점검을 돌린다」 고 적어 두기만 하면 네 번 가운데 두 번은 건너뛰었다(2026-11-12 시험).
그래서 파일을 쓸 때마다 훅이 검사를 직접 돌린다. 검사 코드와 절차 목록은 skills/4000절차점검 의 것을 그대로 쓴다.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

from paths import MEMO

SKILL = Path(__file__).resolve().parents[1] / "skills" / "4000절차점검"
KIND = "검사"
MAX_NAGS = 4          # 같은 세션 · 같은 파일에 문제를 알리는 횟수. 넘으면 조용히 기록만 한다
SHOW = 8              # 한 번에 보이는 문제 수
COLUMNS = "번호 | 절차 | 해당 여부 | 시트 | 쓸 받은자료 | 수행 방법 · 사유"
_check = None


def _module():
    global _check
    if _check is None:
        spec = importlib.util.spec_from_file_location("proccheck", SKILL / "scripts" / "check.py")
        _check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_check)
    return _check


def areas() -> dict[str, str]:
    """{영역 번호: 영역 이름}. 절차 목록 파일이 있는 영역만."""
    out = {}
    for p in sorted((SKILL / "procedures").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out[d["area"]] = d.get("name") or ""
    return out


def area_of(path: Path, text: str, known: dict[str, str]) -> str | None:
    """파일 이름이나 앞쪽 제목 줄에 영역 번호가 있거나, 파일 이름에 영역 이름과 「조서」 · 「설계」 가 있으면 그 영역."""
    heads = [l for l in text.splitlines()[:40] if l.startswith("#")]
    for code, name in known.items():
        base = re.split(r"[(（]", name)[0].strip()
        if code in path.name or any(code in h for h in heads):
            return code
        if base and base in path.name and ("조서" in path.name or "설계" in path.name):
            return code
    return None


def gate(payload: dict, case: Path, records: list[dict]) -> tuple[dict | None, str | None]:
    """(기록 줄에 더할 것, 대화에 넣을 글). 대상 파일이 아니면 (None, None)."""
    fp = (payload.get("tool_input") or {}).get("file_path") or ""
    if not fp.lower().endswith(".md") or not SKILL.is_dir():
        return None, None
    path = Path(fp)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or ".") / path
    path = path.resolve()
    case = Path(case).resolve()
    if case not in path.parents or path.name == MEMO or "00 받은자료" in path.relative_to(case).parts or not path.is_file():
        return None, None
    text = path.read_text(encoding="utf-8", errors="replace")
    area = area_of(path, text, areas())
    if not area:
        return None, None
    m = _module()
    problems = m.check(text, m.load(area))
    sig = hashlib.md5("\n".join(problems).encode("utf-8")).hexdigest()[:8] if problems else ""
    rec = {"kind": KIND, "detail": str(path), "area": area, "problems": len(problems), "sig": sig}
    if not problems:
        return rec, None
    session = payload.get("session_id") or ""
    mine = [r for r in records if r.get("kind") == KIND and r.get("session") == session and r.get("detail") == str(path)]
    # 글을 여러 번 나눠 쓰는 동안 같은 문제를 되풀이해 알리지 않는다. 문제가 바뀌었을 때만, MAX_NAGS 번까지 알린다
    if (mine and mine[-1].get("sig") == sig) or sum(1 for r in mine if r.get("told")) >= MAX_NAGS:
        return rec, None
    rec["told"] = True
    check = SKILL / "scripts" / "check.py"
    shown = "\n".join(f"- {x}" for x in problems[:SHOW]) + (f"\n- 그 밖에 {len(problems) - SHOW}개" if len(problems) > SHOW else "")
    msg = (f"[절차점검] {path.name} 은 {area} 조서 글인데 절차 검사에서 문제 {len(problems)}개가 나왔습니다.\n{shown}\n"
           f"글을 다 쓴 뒤 4000절차점검 스킬을 Skill 도구로 불러 그 순서대로 고치십시오. 본문(시트 · 열 · 쓸 받은자료)을 먼저 고치고 "
           f"끝에 「절차 대조」 절을 두어 표를 맞춥니다. 표 머리는 「{COLUMNS}」 이고 번호는 절차 목록의 번호({area[4:]}-1 …)입니다. "
           f"절차 목록: python \"{check}\" --list {area}. 검사: python \"{check}\" \"{path}\" --area {area}. "
           f"표의 글자만 바꿔 통과시키지 않습니다. 이 회사에 없는 절차는 「해당 없음」 과 사유로 적고 회계사에게 묻는 목록에 올립니다.")
    return rec, msg
