"""설치 점검. 항목마다 (통과 여부, 이름, 고칠 방법)."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

from paths import CONTEXT_DIR, LOG, ROOT_MARK, case_info, list_cases

SKILLS_REQUIRED = ("PBC요청자료", "분개테스트", "DSD푸팅", "감사대시보드", "수령확인", "4000절차점검")
# 함께 싣는 스킬(PBC요청자료 · 분개테스트 · DSD푸팅)의 requirements.txt 에서 시험용(pytest)을 뺀 것. {import 이름: pip 패키지}
PIP_MODULES = {"openpyxl": "openpyxl", "yaml": "pyyaml", "jsonschema": "jsonschema", "docx": "python-docx",
               "fitz": "pymupdf", "xlrd": "xlrd"}
PYTHON_FIX = "python.org 설치 프로그램에서 Add python.exe to PATH 를 켜고 다시 설치합니다"


def _python_check() -> tuple[bool, str, str]:
    """스킬 명령은 `python ...` 으로 돈다. PATH 에 없거나 Microsoft Store 바로가기(WindowsApps)면 실패."""
    exe = shutil.which("python")
    ok = bool(exe) and "windowsapps" not in exe.lower()
    return ok, "python 명령", exe if ok else f"{exe or 'PATH 에 없음'}. {PYTHON_FIX}"


def _modules_check(modules: dict) -> tuple[bool, str, str]:
    lack = [pkg for mod, pkg in modules.items() if importlib.util.find_spec(mod) is None]
    return (not lack, "파이썬 패키지",
            "" if not lack else f"빠짐 {' · '.join(lack)}. python -m pip install {' '.join(lack)} 로 설치합니다")


def _deny_ok(settings: Path) -> bool:
    try:
        deny = json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False
    return any(r.startswith("Edit(//") and "00 받은자료" in r for r in deny)


def run_checks(plugin_root, root, modules: dict | None = None) -> list[tuple[bool, str, str]]:
    r: list[tuple[bool, str, str]] = [(sys.version_info >= (3, 11), "파이썬 3.11 이상", sys.version.split()[0]),
                                      _python_check(), _modules_check(PIP_MODULES if modules is None else modules)]
    for s in SKILLS_REQUIRED:
        ok = (Path(plugin_root) / "skills" / s / "SKILL.md").is_file()
        r.append((ok, f"스킬 {s}", "" if ok else "플러그인을 다시 설치해 주십시오"))
    root_ok = bool(root) and all((Path(root) / x).exists() for x in (ROOT_MARK, "CLAUDE.md", CONTEXT_DIR))
    r.append((root_ok, "감사 루트", str(root) if root_ok else "/audit-agents:설치 로 만들어 주십시오"))
    if not root_ok:
        return r
    cases = list_cases(root)
    r.append((True, "회사 폴더", f"{len(cases)}곳" if cases else "아직 없음. /audit-agents:새회사 로 만듭니다"))
    for case in cases:
        name = case_info(case)["company"]
        ok = _deny_ok(case / ".claude" / "settings.json")
        r.append((ok, f"{name} 권한 파일", "" if ok else "/audit-agents:설치 를 다시 돌려 주십시오"))
        log = case / LOG
        ok = log.is_file() and '"kind": "시작"' in log.read_text(encoding="utf-8")
        r.append((ok, f"{name} 훅 기록", "" if ok else f"{case} 에서 세션을 한 번 열어 주십시오. 그래도 실패하면 python 이 PATH 에 있는지 봅니다"))
    return r
