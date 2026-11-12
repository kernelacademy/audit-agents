"""훅 입력을 기록 줄로 바꾸고, 세션 시작 때 넣을 글과 진행메모 확인을 만든다."""
from __future__ import annotations

from pathlib import Path

from facts import case_line
from paths import MEMO, find_case, find_root, list_cases
from tokens import session_usage


def to_record(payload: dict, now: str) -> dict | None:
    ev = payload.get("hook_event_name")
    rec = {"t": now, "session": payload.get("session_id") or "", "event": ev}
    if ev == "SessionStart":
        rec.update(kind="시작", detail=payload.get("source") or "")
    elif ev == "UserPromptSubmit":
        rec.update(kind="지시", detail=(payload.get("prompt") or "")[:120])
    elif ev == "PostToolUse":
        rec.update(kind="파일", detail=(payload.get("tool_input") or {}).get("file_path") or "")
    elif ev == "Stop":
        rec.update(kind="끝", detail=(payload.get("last_assistant_message") or "")[:200],
                   tokens=session_usage(payload.get("transcript_path")))
    else:
        return None
    return rec


def start_context(cwd) -> str | None:
    case = find_case(cwd)
    if case:
        return (f"[감사에이전트] {case_line(case)}\n"
                f"{MEMO} 의 남은 일을 보고 오늘 할 일을 세 줄 안으로 제안한다. 다른 고객사 폴더는 읽지 않는다.")
    root = find_root(cwd)
    if root and Path(cwd).resolve() == root:
        cases = list_cases(root)
        lines = "\n".join(f"- {case_line(c)}  ({c})" for c in cases)
        return (f"[감사에이전트] 감사 루트. 회사 {len(cases)}곳.\n{lines}\n"
                "회사 일은 그 회사 폴더에서 새 세션을 열라고 경로와 함께 안내한다.")
    return None


def needs_memo(records: list[dict], session: str) -> bool:
    files = [r.get("detail") or "" for r in records if r.get("session") == session and r.get("kind") == "파일"]
    return bool(files) and not any(f.replace("\\", "/").endswith(MEMO) for f in files)
