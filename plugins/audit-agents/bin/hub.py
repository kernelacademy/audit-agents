"""감사에이전트 명령줄: setup · newcase · status · check."""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import run_checks  # noqa: E402
from paths import find_root  # noqa: E402
from setup import make_root, new_case, repair_settings  # noqa: E402
from status import get_publish_url, set_publish_url, write_publish, write_status  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PBC = PLUGIN_ROOT / "skills" / "PBC요청자료" / "scripts" / "run.py"
BAD_NAME_CHARS = set('<>:"/|?*') | {chr(92)}


def _print_checks(plugin_root: Path, root) -> int:
    results = run_checks(plugin_root, root)
    for ok, name, detail in results:
        print(f"{'통과' if ok else '실패'}  {name}  {detail}".rstrip())
    return 0 if all(ok for ok, _, _ in results) else 1


def _bad_company(company: str) -> bool:
    return (not company or company in (".", "..") or company != Path(company).name
            or company[-1] in ". " or any(ch in BAD_NAME_CHARS for ch in company))


def _bad_date(value: str) -> bool:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return True
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return True
    return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="hub.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--root")
    n = sub.add_parser("newcase")
    n.add_argument("--root")
    n.add_argument("--company", required=True)
    n.add_argument("--fy-end", required=True)
    n.add_argument("--pbc", default=str(PBC))
    t = sub.add_parser("status")
    t.add_argument("--root")
    t.add_argument("--open", action="store_true")
    t.add_argument("--publish", action="store_true", help="아티팩트로 올릴 게시용 파일을 만든다")
    t.add_argument("--set-url", help="게시한 아티팩트 주소를 감사 루트에 적어 둔다")
    c = sub.add_parser("check")
    c.add_argument("--root")
    args = p.parse_args(argv)

    if args.cmd == "newcase":
        if _bad_company(args.company):
            print("회사 이름이 비었거나 폴더 이름으로 쓸 수 없는 글자가 있습니다. 경로 구분 글자와 < > : \" | ? * 는 뺍니다.",
                  file=sys.stderr)
            return 2
        if _bad_date(args.fy_end):
            print("결산일은 YYYY-MM-DD 형식으로 적어 주십시오.", file=sys.stderr)
            return 2

    root = Path(args.root).expanduser().resolve() if args.root else find_root(Path.cwd())
    if args.cmd == "setup":
        root = root or Path.home() / "감사"
        for w in make_root(root):
            print(f"만듦  {w}")
        for w in repair_settings(root):
            print(f"권한 파일  {w}")
        return _print_checks(PLUGIN_ROOT, root)
    if root is None:
        print("감사 루트를 찾지 못했습니다. --root 로 주거나 /audit-agents:설치 를 먼저 돌려 주십시오")
        return 2
    if args.cmd == "newcase":
        print(json.dumps(new_case(root, args.company, args.fy_end, args.pbc), ensure_ascii=False, indent=1))
    elif args.cmd == "status" and args.set_url:
        try:
            set_publish_url(root, args.set_url)
        except ValueError as e:
            print(f"{e}: {args.set_url}", file=sys.stderr)
            return 2
        print(f"게시 주소  {args.set_url}")
    elif args.cmd == "status" and args.publish:
        print(f"게시용 파일  {write_publish(root, cwd=Path.cwd())}")
        print(f"게시 주소  {get_publish_url(root) or '없음'}")
    elif args.cmd == "status":
        page = write_status(root)
        print(page)
        if args.open:
            webbrowser.open(page.as_uri())
    elif args.cmd == "check":
        return _print_checks(PLUGIN_ROOT, root)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
