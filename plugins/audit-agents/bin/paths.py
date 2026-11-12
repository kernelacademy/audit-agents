"""감사 루트 · 회사 폴더 찾기와 권한 규칙 경로."""
from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath

ROOT_MARK = "감사루트.json"
CASE_MARK = Path("_색인") / "감사건.json"
CONTEXT_DIR = "_맥락"
LOG = Path("_기록") / "기록.jsonl"
MEMO = "진행메모.md"


def gamsa_home() -> Path:
    return Path(os.environ.get("GAMSA_HOME") or Path.home() / ".감사에이전트")


def to_rule_path(p) -> str:
    """절대 경로를 권한 규칙 꼴(//c/Users/... · //Users/...)로 바꾼다."""
    s = str(p)
    w = PureWindowsPath(s)
    if len(w.drive) == 2 and w.drive[1] == ":":
        return f"//{w.drive[0].lower()}/" + "/".join(w.parts[1:])
    return "/" + Path(s).as_posix()


def _up(start, n: int) -> list[Path]:
    p = Path(start).resolve()
    return [p, *p.parents][:n]


def find_root(start) -> Path | None:
    for c in _up(start, 8):
        if (c / ROOT_MARK).is_file():
            return c
    return None


def find_case(start) -> Path | None:
    for c in _up(start, 6):
        if (c / CASE_MARK).is_file():
            return c
    return None


def list_cases(root) -> list[Path]:
    return sorted(p.parent.parent for p in Path(root).glob("*/*/" + CASE_MARK.as_posix()))


def case_info(case) -> dict:
    try:
        d = json.loads((Path(case) / CASE_MARK).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        d = {}
    company = d.get("company")
    name = company.get("name") if isinstance(company, dict) else company
    return {"company": name or Path(case).parent.name, "fy_end": d.get("fiscal_year_end") or ""}
