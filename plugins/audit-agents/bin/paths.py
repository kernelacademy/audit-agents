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


SETUP_SKILL = "감사세팅-setup"


def base_dir() -> Path:
    """bin 의 부모. 플러그인이면 플러그인 루트, 스킬만 설치했으면 감사세팅 스킬 폴더."""
    return Path(__file__).resolve().parents[1]


def as_plugin() -> bool:
    """플러그인으로 설치됐는가. 스킬만 설치한 배포본(tools/build_skills.py)에는 .claude-plugin 이 없다."""
    return (base_dir() / ".claude-plugin").is_dir()


def skills_dir() -> Path:
    """다른 스킬이 있는 폴더. 플러그인이면 <루트>/skills, 스킬만 설치했으면 감사세팅 스킬의 형제 폴더."""
    return base_dir() / "skills" if as_plugin() else base_dir().parent


def say(name: str) -> str:
    """안내 문장에 쓰는 부르는 법. 플러그인은 명령, 스킬만 설치했으면 감사세팅 스킬에 하는 말."""
    return f"/audit-agents:{name}" if as_plugin() else f"「{name}」(감사세팅 스킬)"


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
