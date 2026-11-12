"""감사 루트의 회사 전부를 HTML 한 파일(_현황.html)로 모은다.

게시용(_현황_게시.html)은 claude.ai 아티팩트로 그대로 올리는 판이다. 문서 머리 없이 본문만 쓰고,
밝은 · 어두운 테마를 모두 정하고, 작업 로그의 PC 절대 경로를 지운다."""
from __future__ import annotations

import datetime
import html
import json
import re
from pathlib import Path

from facts import open_items, pbc_counts, read_records, received_files
from paths import ROOT_MARK, case_info, find_case, list_cases
from tokens import BASIS_USD, usd_of_totals

CSS = """:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2433;--mute:#667085;--line:#e4e7ec;--warn:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#0f1420;--card:#171e2d;--ink:#e6e9ef;--mute:#98a2b3;--line:#2a3345;--warn:#f59e0b}}
*{box-sizing:border-box}
body{margin:0;font-family:"Pretendard","Malgun Gothic",sans-serif;background:var(--bg);color:var(--ink)}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0}h2{font-size:15px;margin:24px 0 8px}h3{font-size:14px;margin:12px 0 4px}
.meta{color:var(--mute);font-size:12px}
.tok{display:flex;gap:16px;flex-wrap:wrap;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:13px}
.wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;background:var(--card);font-size:13px}
td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;white-space:nowrap}
td.text{white-space:normal}
.miss{color:var(--warn);font-weight:600}
ul{margin:0;padding-left:18px;font-size:13px}"""

# 게시용 색은 AI감사팀(허브) 화면의 색을 따른다.
_DARK = ("--bg:#0e131b;--card:#161d29;--ink:#e6ebf3;--mute:#93a1b8;--line:#2a3548;--warn:#f0b04a;"
         "--accent:#7ea2ff;color-scheme:dark")
CSS_PUBLISH = f"""/* 한 장짜리 현황: 토큰 요약, 회사 표, 남은 일, 작업 로그 */
:root{{--bg:#f3f5f8;--card:#ffffff;--ink:#16202e;--mute:#5d6b80;--line:#d9dfe8;--warn:#a85f00;--accent:#1f4fd8}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{_DARK}}}}}
:root[data-theme="dark"]{{{_DARK}}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:"Noto Sans KR","Malgun Gothic",system-ui,sans-serif;font-size:14px;line-height:1.5;background:var(--bg);color:var(--ink)}}
main{{max-width:1100px;margin:0 auto;padding-block:16px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}}
h1{{font-size:19px;margin:8px 0}}h2{{font-size:15px;margin:24px 0 8px}}h3{{font-size:14px;margin:12px 0 4px}}
.meta{{color:var(--mute);font-size:12px}}
.tok{{display:flex;gap:16px;flex-wrap:wrap;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 16px;font-size:13px;font-variant-numeric:tabular-nums}}
.tok b{{color:var(--accent)}}
.wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px}}
table{{width:100%;border-collapse:collapse;background:var(--card);font-size:13px}}
td,th{{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top;white-space:nowrap}}
th{{color:var(--mute);font-weight:500}}
tr:last-child td{{border-bottom:0}}
td.text{{white-space:normal;min-width:240px;overflow-wrap:anywhere}}
.miss{{color:var(--warn);font-weight:700}}
ul{{margin:0;padding-left:18px;font-size:13px}}"""

PUBLISH_NAME = "_현황_게시.html"
URL_KEY = "status_artifact_url"
URL_OK = re.compile(r"https://claude\.ai/(code/)?artifact/[A-Za-z0-9_-]+")
_ABS = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home)/)[^\s<>\"'|]*")


def collect(root, today: str | None = None) -> dict:
    today = today or datetime.date.today().isoformat()
    out = {"cases": [], "log": [], "tokens": {"today": 0, "by_case": {}, "usd_today": 0.0, "usd_by_case": {}},
           "made_at": datetime.datetime.now().isoformat(timespec="seconds")}
    for case in list_cases(root):
        info = case_info(case)
        name = f"{info['company']} {info['fy_end'][:4]}".strip()
        recs = read_records(case)
        out["cases"].append({"name": name, "path": str(case), "fy_end": info["fy_end"], "pbc": pbc_counts(case),
                             "files": received_files(case), "open": open_items(case),
                             "last_t": max((r["t"] for r in recs), default="")})
        out["log"] += [{**r, "case": name, "case_path": str(case)} for r in recs]
        last: dict[str, dict] = {}
        for r in sorted(recs, key=lambda r: r["t"]):
            if r.get("kind") == "끝" and r.get("tokens"):
                last[r.get("session") or "?"] = r
        for session, r in last.items():
            if r["t"][:10] != today:
                continue
            t = int(r["tokens"].get("total", 0))
            out["tokens"]["today"] += t
            out["tokens"]["by_case"][name] = out["tokens"]["by_case"].get(name, 0) + t
            u = usd_of_totals(r["tokens"])
            out["tokens"]["usd_today"] += u
            out["tokens"]["usd_by_case"][name] = out["tokens"]["usd_by_case"].get(name, 0.0) + u
    out["log"].sort(key=lambda r: r["t"], reverse=True)
    out["log"] = out["log"][:100]
    return out


def scrub(detail: str, case_path: str) -> str:
    """게시용: PC 절대 경로를 지운다. 회사 폴더 아래는 그 아래 경로만, 그 밖은 파일 이름만 남긴다."""
    s = str(detail or "")
    if case_path:
        for sep in ("\\", "/"):
            s = s.replace(case_path.rstrip("\\/") + sep, "")
        s = s.replace(case_path.rstrip("\\/"), "회사 폴더")
    s = _ABS.sub(lambda m: "(회사 폴더 바깥) " + re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1], s)
    return s.replace("\\", "/")


def _main(data: dict, publish: bool) -> str:
    e = html.escape
    num = lambda v: f"{int(v):,}"  # noqa: E731
    rows = []
    for c in data["cases"]:
        req = (f"<td>{c['pbc'].get('받음', 0)}</td><td class=\"miss\">{c['pbc'].get('빠짐', 0)}</td>"
               if c["pbc"] else '<td colspan="2" class="meta">목록 없음</td>')
        rows.append(f"<tr><td>{e(c['name'])}</td><td>{e(c['fy_end'])}</td>{req}<td>{c['files']}</td>"
                    f"<td>{len(c['open'])}</td><td>{e(c['last_t'][5:16])}</td></tr>")
    todo = "".join(
        f"<h3>{e(c['name'])}</h3><ul>" + ("".join(f"<li>{e(x)}</li>" for x in c["open"]) or "<li>없음</li>") + "</ul>"
        for c in data["cases"])

    def detail(r):
        d = str(r.get("detail") or "")
        return scrub(d, r.get("case_path", "")) if publish else d

    log = "".join(
        f"<tr><td>{e(r['t'][5:16])}</td><td>{e(r['case'])}</td><td>{e(r['kind'])}</td>"
        f"<td class=\"text\">{e(detail(r))}</td></tr>" for r in data["log"])
    t = data["tokens"]
    usd, by_usd = t.get("usd_today", 0.0), t.get("usd_by_case", {})
    tok = (f"<span>오늘 토큰 <b>{num(t['today'])}</b></span>"
           f"<span>API 단가로 환산하면 약 <b>${usd:,.2f}</b> · Max 요금제 월 ${BASIS_USD} 의 {usd / BASIS_USD * 100:.1f}%</span>"
           + "".join(f"<span>{e(k)} {num(v)} (약 ${by_usd.get(k, 0.0):,.2f})</span>" for k, v in t["by_case"].items()))
    title = "AI감사팀 현황" if publish else "감사 현황"
    again = "다시 올리려면 /audit-agents:현황게시" if publish else "다시 만들려면 /audit-agents:현황"
    return f"""<main>
<h1>{title}</h1><p class="meta">만든 시각 {e(data['made_at'])} · {again}</p>
<div class="tok">{tok}</div>
<h2>회사</h2><div class="wrap"><table><tr><th>회사</th><th>결산일</th><th>요청 받음</th><th>빠짐</th><th>받은자료</th><th>남은 일</th><th>마지막 작업</th></tr>{''.join(rows)}</table></div>
<h2>남은 일</h2>{todo or '<p class="meta">회사가 없습니다</p>'}
<h2>작업 로그</h2><div class="wrap"><table><tr><th>시각</th><th>회사</th><th>종류</th><th>내용</th></tr>{log}</table></div>
</main>"""


def render(data: dict) -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>감사 현황</title><style>{CSS}</style></head><body>{_main(data, False)}</body></html>
"""


def render_publish(data: dict) -> str:
    """아티팩트 게시 규칙에 맞는 판: doctype · html · head · body 없이 title · style · 본문."""
    return (f'<title>AI감사팀 현황</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            f"<style>\n{CSS_PUBLISH}\n</style>\n{_main(data, True)}\n")


def write_status(root, today: str | None = None) -> Path:
    p = Path(root).resolve() / "_현황.html"
    p.write_text(render(collect(root, today)), encoding="utf-8")
    return p


def write_publish(root, today: str | None = None, cwd=None) -> Path:
    """게시용 파일을 쓴다. 회사 세션에서 돌리면 그 회사 폴더 _작업 아래에 둔다(세션의 작업 폴더 안이라 올릴 수 있다)."""
    case = find_case(cwd) if cwd else None
    p = (case / "_작업" / "현황_게시.html") if case else Path(root).resolve() / PUBLISH_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_publish(collect(root, today)), encoding="utf-8", newline="\n")
    return p


def _mark(root) -> dict:
    try:
        d = json.loads((Path(root) / ROOT_MARK).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        d = {}
    return d if isinstance(d, dict) else {}


def get_publish_url(root) -> str:
    return str(_mark(root).get(URL_KEY) or "")


def set_publish_url(root, url: str) -> None:
    if not URL_OK.fullmatch(url or ""):
        raise ValueError("claude.ai 아티팩트 주소가 아닙니다")
    d = _mark(root)
    d[URL_KEY] = url
    (Path(root) / ROOT_MARK).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
