"""4000 계정별 조서 설계 · 초안의 「절차 대조」 표를 영역 절차 목록과 견줘 빠진 절차를 찾는다.

  python check.py --list 4000C            절차 목록을 보인다
  python check.py <파일.md> --area 4000C   「절차 대조」 표를 검사한다. 문제가 없으면 종료 코드 0, 있으면 1

검사는 표의 꼴과 낱말만 본다. 절차가 이 회사에 맞는지, 해당 여부가 옳은지는 회계사가 본다.
표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROCS = Path(__file__).resolve().parents[1] / "procedures"
STATES = ("해당 없음", "회계사 확인", "해당")      # 긴 말부터 견준다
SECTION = "절차 대조"
MIN_HOW = 30          # 해당 줄의 수행 방법 글자 수
MIN_WHY = 15          # 해당 없음 · 회계사 확인 줄의 사유 글자 수
OTHER_WP = re.compile(r"^\d{4}[A-Z]*(-[A-Z0-9가-힣]+)?$")
STDS = Path(__file__).resolve().parents[1] / "standards.json"
CITE_STOP = re.compile(r"[·,|/;:\n)）」\]]|제\s*\d+\s*장|감사기준서|일반기업회계기준")


def load(area: str) -> dict:
    p = PROCS / f"{area}.json"
    if not p.is_file():
        have = ", ".join(sorted(x.stem for x in PROCS.glob("*.json"))) or "없음"
        raise SystemExit(f"절차 목록이 없는 영역입니다: {area} (있는 영역: {have})")
    return json.loads(p.read_text(encoding="utf-8"))


def _clean(s: str) -> str:
    return re.sub(r"[`*]", "", s).strip()


def split_doc(text: str) -> tuple[list[str], str]:
    """(절차 대조 절의 줄들, 그 절을 뺀 나머지 글). 절은 제목 줄에 「절차 대조」 가 든 곳부터 같은 수준 이상의 다음 제목 앞까지다."""
    lines = text.splitlines()
    start = level = None
    for i, l in enumerate(lines):
        m = re.match(r"^(#+)\s", l)
        if m and SECTION in l.replace(" ", "").replace("절차대조", SECTION):
            start, level = i, len(m.group(1))
            break
    if start is None:
        return [], text
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(#+)\s", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return lines[start:end], "\n".join(lines[:start] + lines[end:])


def parse_table(section: list[str]) -> tuple[dict, dict[str, dict]]:
    """(열 이름 → 위치, 절차 번호 → 칸들). 표 머리는 「번호」 가 든 첫 표 줄이다."""
    cols, rows = {}, {}
    for l in section:
        if not l.lstrip().startswith("|"):
            continue
        cells = [_clean(c) for c in l.strip().strip("|").split("|")]
        if not cols:
            if any("번호" in c for c in cells):
                for i, c in enumerate(cells):
                    key = ("no" if "번호" in c else "state" if "해당" in c else "sheet" if "시트" in c
                           else "docs" if "자료" in c else "how" if ("방법" in c or "사유" in c) else None)
                    if key and key not in cols:
                        cols[key] = i
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        no = cells[cols["no"]] if cols.get("no", 99) < len(cells) else ""
        m = re.match(r"^([A-Z]+)-?(\d+)", no)
        if m:
            rows[f"{m.group(1)}-{int(m.group(2))}"] = {k: (cells[i] if i < len(cells) else "") for k, i in cols.items()}
    return cols, rows


def _tail(text: str, end: int) -> str:
    """인용 번호 바로 뒤에 붙은 이름. 여는 괄호는 떼고, 구분 글자나 다음 인용 앞에서 끊는다."""
    t = re.sub(r"^\s*[(（「\[]?\s*", "", text[end:end + 28])
    m = CITE_STOP.search(t)
    return (t[:m.start()] if m else t).strip()


def check_citations(text: str) -> list[str]:
    """글 전체에서 「제N장」 · 「감사기준서 NNN」 을 찾아, 없는 번호와 뒤에 붙인 이름이 다른 기준서의 것인 곳을 낸다.

    번호 뒤에 이름을 붙이지 않았거나 문단 번호가 이어지면 보지 않는다. 문단 내용이 맞는지도 보지 않는다."""
    if not STDS.is_file():
        return []
    table = json.loads(STDS.read_text(encoding="utf-8"))
    body = _clean(text)
    out = []
    for dom, pat, label in (("kgaap", r"제\s*(\d+)\s*장", "일반기업회계기준 제{}장"), ("audit", r"감사기준서\s*(\d{3,4})", "감사기준서 {}")):
        stds = table[dom]
        for m in re.finditer(pat, body):
            no, name = m.group(1), label.format(m.group(1))
            if no not in stds:
                msg = f"인용: {name} 은 기준서 목록에 없는 번호입니다. 번호를 확인해 고치거나 비웁니다"
            else:
                tail, own = _tail(body, m.end()), stds[no]
                mine = [own["title"]] + own["keys"] + own.get("own_only", [])
                named = bool(tail) and not tail.startswith("문단")
                if named and any(k in tail for k in mine):
                    continue
                other = next(((n, v) for n, v in stds.items() if n != no and any(tail.startswith(k) for k in v["keys"])), None) if named else None
                what = tail
                if not other:
                    # 표의 줄에서 이름 칸과 번호 칸이 따로 있을 때: 같은 줄의 칸이 다른 기준서 이름과 같으면 본다
                    line = body[body.rfind("\n", 0, m.start()) + 1:(body.find("\n", m.end()) + 1 or len(body) + 1) - 1]
                    cells = [c.strip() for c in line.split("|")] if "|" in line else []
                    if not cells or any(k in line for k in mine):
                        continue
                    hit = next(((n, v, c) for n, v in stds.items() if n != no for c in cells if c and (c == v["title"] or c in v["keys"])), None)
                    if not hit:
                        continue
                    other, what = (hit[0], hit[1]), hit[2]
                msg = (f"인용: {name} 은 「{own['title']}」 입니다. 함께 적은 「{what}」 은 {label.format(other[0])}"
                       f"(「{other[1]['title']}」) 쪽입니다. 번호를 확인해 고칩니다")
            if msg not in out:
                out.append(msg)
    return out


def check(text: str, defs: dict) -> list[str]:
    return check_table(text, defs) + check_citations(text)


def check_table(text: str, defs: dict) -> list[str]:
    section, rest = split_doc(text)
    if not section:
        return [f"「{SECTION}」 절이 없습니다. 제목에 「{SECTION}」 를 넣은 절을 만들고 그 아래 표를 씁니다"]
    cols, rows = parse_table(section)
    need = [k for k, label in (("no", "번호"), ("state", "해당 여부"), ("sheet", "시트"), ("docs", "쓸 받은자료"), ("how", "수행 방법 · 사유")) if k not in cols]
    if need:
        label = {"no": "번호", "state": "해당 여부", "sheet": "시트", "docs": "쓸 받은자료", "how": "수행 방법 · 사유"}
        return ["표 머리에 열이 없습니다: " + ", ".join(label[k] for k in need)]
    flat = re.sub(r"\s+", "", _clean(rest))
    out = []
    for p in defs["procedures"]:
        pid, r = p["id"], rows.get(p["id"])
        if r is None:
            out.append(f"{pid} {p['title']}: 표에 줄이 없습니다. 할 일: {p['what']}")
            continue
        state = next((s for s in STATES if r["state"].replace(" ", "").startswith(s.replace(" ", ""))), None)
        if state is None:
            out.append(f"{pid} {p['title']}: 해당 여부는 「해당」 · 「해당 없음」 · 「회계사 확인」 가운데 하나로 시작합니다(지금: {r['state'] or '빈 칸'})")
            continue
        if state != "해당":
            if len(r["how"]) < MIN_WHY:
                out.append(f"{pid} {p['title']}: {state} 의 사유를 이 회사 자료의 사실로 적습니다({MIN_WHY}자 이상)")
            continue
        names = [n.strip() for n in re.split(r"[·,/]|<br>", r["sheet"]) if n.strip()]
        own = [n for n in names if not (OTHER_WP.match(n) and n != defs["area"])]
        if not own:
            out.append(f"{pid} {p['title']}: 이 조서의 시트 이름이 없습니다. 다른 조서({r['sheet'] or '빈 칸'})로만 넘기지 않고, 이 조서에서 할 일을 맡는 시트를 적습니다")
        elif not any(re.sub(r"\s+", "", n) in flat for n in own):
            out.append(f"{pid} {p['title']}: 시트 「{' · '.join(own)}」 가 본문에 없습니다. 본문에 그 시트를 정의하거나 표의 시트 이름을 본문과 맞춥니다")
        if not r["docs"]:
            out.append(f"{pid} {p['title']}: 쓸 받은자료가 비었습니다. 파일 이름을 적거나 「요청 필요: <자료>」 로 적습니다")
        if len(r["how"]) < MIN_HOW:
            out.append(f"{pid} {p['title']}: 수행 방법이 짧습니다({MIN_HOW}자 이상). 무엇을 무엇과 견주는지 적습니다")
        body = " ".join(r.values())
        for pt in p["points"]:
            if not any(k in body for k in pt["any"]):
                out.append(f"{pid} {p['title']}: 「{pt['name']}」 내용이 없습니다. 수행 방법에 넣거나, 이 회사에 없으면 그 사실을 적습니다")
    return out


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="절차 대조 표 검사")
    ap.add_argument("file", nargs="?", help="조서 설계 · 초안 md")
    ap.add_argument("--area", help="영역 조서번호(예: 4000C)")
    ap.add_argument("--list", metavar="AREA", help="영역 절차 목록을 보인다")
    a = ap.parse_args(argv)
    if a.list:
        d = load(a.list)
        print(f"{d['area']} {d['name']} 절차 {len(d['procedures'])}개")
        for p in d["procedures"]:
            print(f"- {p['id']} {p['title']}: {p['what']} (주장 {' · '.join(p['assertions'])})")
            print("    꼭 다룰 것: " + " / ".join(pt["name"] for pt in p["points"]))
            for r in p.get("refs") or []:
                print(f"    근거: {r['cite']} ({r['about']})")
        rc = d.get("refs_checked")
        if rc:
            print(f"근거는 {rc['date']} {rc['source']}로 확인했다. {rc['note']}. 목록에 없는 기준서 · 장 · 문단 번호는 확인한 것만 쓰고, 확인하지 못했으면 번호를 비운다.")
        return 0
    if not a.file or not a.area:
        ap.error("파일과 --area 를 줍니다")
    d = load(a.area)
    problems = check(Path(a.file).read_text(encoding="utf-8"), d)
    if problems:
        print(f"문제 {len(problems)}개 ({d['area']} 절차 {len(d['procedures'])}개 가운데)")
        for x in problems:
            print("- " + x)
        return 1
    print(f"통과: {d['area']} 절차 {len(d['procedures'])}개가 모두 표에 있습니다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
