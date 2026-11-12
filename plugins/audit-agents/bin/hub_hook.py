"""훅 진입점. 회사 폴더 세션이면 _기록/기록.jsonl 에 한 줄을 남긴다. 늘 0 으로 끝난다."""
from __future__ import annotations

import datetime
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import STOP_MODE  # noqa: E402
from events import needs_memo, start_context, to_record  # noqa: E402
from facts import read_records  # noqa: E402
from paths import LOG, MEMO, find_case, gamsa_home  # noqa: E402
from procgate import gate  # noqa: E402


def memo_reason(case: Path) -> str:
    """절대 경로를 적어야 모델이 메모를 엉뚱한 곳(scratchpad)에 쓰지 않는다(PROBE.md 3)."""
    return (f"이번 세션에서 파일을 고쳤는데 {case / MEMO} 를 고치지 않았습니다. "
            "Edit 도구로 고쳐 오늘 한 것, 회계사가 정한 것, 회사 답변, 남은 일을 적고 끝내십시오. "
            "python 으로 파일을 고치면 기록이 남지 않아 이 알림이 다시 뜹니다.")


def main(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        payload = json.loads(stdin.read() or "{}")
        cwd = payload.get("cwd") or "."
        ev = payload.get("hook_event_name")
        case = find_case(cwd)
        if case:
            rec = to_record(payload, datetime.datetime.now().isoformat(timespec="seconds"))
            if rec:
                (case / LOG).parent.mkdir(parents=True, exist_ok=True)
                with open(case / LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out = None
        if ev == "PostToolUse" and case:
            now = datetime.datetime.now().isoformat(timespec="seconds")
            extra, msg = gate(payload, case, read_records(case))
            if extra:
                with open(case / LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"t": now, "session": payload.get("session_id") or "", "event": ev, **extra}, ensure_ascii=False) + "\n")
            if msg:
                out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}
        if ev == "SessionStart":
            ctx = start_context(cwd)
            if ctx:
                out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}
        elif (ev == "Stop" and case and STOP_MODE != "none" and not payload.get("stop_hook_active")
              and needs_memo(read_records(case), payload.get("session_id") or "")):
            reason = memo_reason(case)
            out = ({"decision": "block", "reason": reason} if STOP_MODE == "block" else
                   {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}})
        if out:
            stdout.write(json.dumps(out, ensure_ascii=False))
    except Exception:  # 훅은 세션을 막지 않는다
        try:
            home = gamsa_home()
            home.mkdir(parents=True, exist_ok=True)
            with open(home / "hook-errors.log", "a", encoding="utf-8") as f:
                f.write(datetime.datetime.now().isoformat() + "\n" + traceback.format_exc() + "\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
