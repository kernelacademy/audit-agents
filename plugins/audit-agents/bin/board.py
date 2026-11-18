"""회사 한 건의 감사대시보드에 「누가 했나」(스킬 · 에이전트 · 회계사)를 덧입힌다(2026-11-18).

감사대시보드 스킬(scripts/build.py · template.html)은 고치지 않는다. 그 코드를 불러 단계 표만 강의판으로 바꾸고,
훅 기록(_기록/기록.jsonl)과 진행메모로 항목마다 근거를 붙인 뒤, 화면 끝에 덧입히는 스크립트를 넣는다.

  스킬      부른 스킬(기록 kind 스킬)과 스킬 스크립트를 돌린 명령(kind 엔진)
  에이전트  스킬 없이 에이전트가 쓴 파일(kind 파일)과 회사 폴더에 있는 그 파일
  회계사    진행메모 「정한 것」 에 적힌 결정

항목 표(STAGES)는 강의 순서를 따른다. 사무소의 일하는 순서가 다르면 이 표만 고친다.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from facts import open_items, read_records
from paths import MEMO, case_info, skills_dir

SKILL, AGENT, CPA = "스킬", "에이전트", "회계사"
OUT_NAME = Path("_작업") / "감사대시보드.html"
ALWAYS = ("CLAUDE.md", MEMO)

# (항목, 조서번호, 스킬, 맡는 쪽, 에이전트가 쓰는 파일 glob, 진행메모 「정한 것」 에서 찾는 낱말)
STAGES = [
    ("시작", "요청자료 · 계약 · 기업이해", [
        ("요청자료 목록 · 메일", ["PBC"], ["PBC요청자료"], SKILL, [], []),
        ("받은자료 수령 확인", [], ["수령확인"], SKILL, [], ["재요청", "그대로 받", "직접 확인"]),
        ("계약 조서 · 기업이해 초안", ["1100", "1200", "2100"], ["PBC요청자료"], SKILL, [], []),
        ("인차지 설계 카드 · 작년 이슈", [], [], AGENT, ["CLAUDE.md"], ["인차지"]),
        ("독립성 확인", ["1300"], [], CPA, [], ["독립성"]),
    ]),
    ("위험평가", "정산표 · 사전 분석 · 중요성", [
        ("정산표", ["8100B"], ["WTB정산표"], SKILL, [], []),
        ("사전 회사분석", [], [], AGENT, ["2000 위험평가/*사전분석*.md"], []),
        ("받은자료 조서별 정리", [], [], AGENT, ["2000 위험평가/*정리*.md", "_작업/*정리*.md"], []),
        ("중요성 · 위험 계정 결정", ["2700A", "2700B", "2301"], [], CPA, [], ["중요성", "위험 계정", "유의적"]),
    ]),
    ("실행", "계정별 조서 · 분개테스트", [
        ("분개테스트", ["3600-JET"], ["분개테스트"], SKILL, [], []),
        ("현금흐름표", [], ["CF현금흐름표"], SKILL, [], []),
        ("매출채권 조서 설계", ["4000C"], ["4000절차점검"], SKILL, ["_작업/*4000C*.md"], []),
        ("그 밖의 계정 조서 초안", ["4000A", "4000P", "4000G", "4000EE"], [], AGENT, ["_작업/4000[!C]*.md"], []),
        ("해당 여부 · 결론", [], [], CPA, [], ["해당 없음", "해당 여부", "결론"]),
    ]),
    ("보고", "푸팅 · 수정 · 감사의견", [
        ("DSD 푸팅", ["DART"], ["DSD푸팅"], SKILL, [], []),
        ("불일치 메모 · 회사 질문", [], [], AGENT, ["_작업/메일/*", "_작업/*메모*.md"], []),
        ("숫자 고치기(연결 조서)", [], [], AGENT, [], ["고친 곳", "고치지 않", "고쳤"]),
        ("수정 여부 · 감사의견", ["8600"], [], CPA, [], ["수정 제안", "수정 여부", "감사의견"]),
    ]),
    ("종결", "마무리 · 보관", [
        ("세션 마무리(진행메모)", [], [], AGENT, [MEMO], []),
        ("감사 종료 · 보관", ["8700"], [], CPA, [], ["보관", "감사 종료"]),
    ]),
]


def _dashboard():
    """감사대시보드 스킬의 build.py 와 template.html. 없으면 FileNotFoundError."""
    scripts = skills_dir() / "감사대시보드" / "scripts"
    spec = importlib.util.spec_from_file_location("dashboard_build", scripts / "build.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, (scripts / "template.html").read_text(encoding="utf-8")


def decided(case) -> list[str]:
    """진행메모 「정한 것」 의 줄."""
    p = Path(case) / MEMO
    if not p.is_file():
        return []
    out, inside = [], False
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## 정한 것"
        elif inside and line.strip().startswith("-"):
            out.append(line.strip().lstrip("- ").strip())
    return out


def _skill_of(rec: dict) -> str:
    """기록 한 줄이 가리키는 스킬. 수령확인은 PBC요청자료 스크립트의 next 로 돈다."""
    if rec.get("kind") == "엔진" and rec.get("detail") == "PBC요청자료" and " next " in f" {rec.get('cmd') or ''} ":
        return "수령확인"
    return str(rec.get("detail") or "")


# 따옴표 안 경로는 공백이 있어도 통째로, 따옴표가 없으면 공백 앞까지만 줄인다
_SKILL_PATH = re.compile(r"""(?:(?<=")[^"]*|[^"' ]*)[\\/](?=[^\\/"' ]+[\\/]scripts[\\/])""")


def _short(cmd: str) -> str:
    """명령에서 스킬 폴더 앞의 PC 경로를 줄인다(화면에 사용자 폴더 이름을 싣지 않는다)."""
    return _SKILL_PATH.sub("…/", cmd, count=1)


def _rel(case: Path, path: str) -> str | None:
    try:
        return Path(path).resolve().relative_to(case).as_posix()
    except (ValueError, OSError):
        return None


def evidence(case, records: list[dict], skills, globs, keys, notes: list[str]) -> dict:
    """항목 하나의 근거: 스킬 실행 기록, 에이전트가 쓴 파일, 회계사가 정한 줄."""
    case = Path(case).resolve()
    runs = [{"t": r["t"], "kind": r["kind"], "skill": _skill_of(r), "cmd": _short(r.get("cmd") or "")}
            for r in records if r.get("kind") in ("스킬", "엔진") and _skill_of(r) in skills]
    # 회사 CLAUDE.md 와 진행메모는 폴더를 만들 때부터 있다. 있는 것만으로는 세지 않고 고친 기록이 있을 때만 센다
    here = sorted({p.relative_to(case).as_posix() for g in globs if g not in ALWAYS for p in case.glob(g) if p.is_file()})
    wrote: dict[str, str] = {}
    for r in records:
        rel = _rel(case, r.get("detail") or "") if r.get("kind") == "파일" else None
        if rel and any(Path(rel).match(g) or rel == g for g in globs):
            wrote[rel] = r["t"]
    files = [{"path": f, "t": wrote.get(f, "")} for f in sorted(set(here) | set(wrote))]
    return {"runs": runs[-6:], "run_count": len(runs), "files": files,
            "decided": [n for n in notes if any(k in n for k in keys)]}


def _state(mode: str, ev: dict, wps: list[dict]) -> str:
    done = bool(ev["runs"]) if mode == SKILL else bool(ev["files"] or ev["decided"]) if mode == AGENT else bool(ev["decided"])
    return "ok" if done else ""


def build(case) -> str:
    case = Path(case).resolve()
    m, template = _dashboard()
    m.STAGES = [(s, what, [(n, nos, sk, False) for n, nos, sk, *_ in subs]) for s, what, subs in STAGES]
    m.STAGES[0][2][0] = (*m.STAGES[0][2][0][:3], True)      # 요청자료 항목에는 빠진 자료를 전부 보인다
    m.PUBLIC = {}
    data = m.build(case / "_색인", False)
    records, notes = read_records(case), decided(case)
    counts = {SKILL: [0, 0], AGENT: [0, 0], CPA: [0, 0]}
    for (_, _, subs), st in zip(STAGES, data["stages"]):
        for (_, _, skills, mode, globs, keys), it in zip(subs, st["items"]):
            ev = evidence(case, records, skills, globs, keys, notes)
            it.update(mode=mode, lec=ev, state=_state(mode, ev, it["wps"]))
            counts[mode][1] += 1
            counts[mode][0] += it["state"] == "ok"
    tokens = [r.get("tokens") for r in records if r.get("kind") == "끝" and isinstance(r.get("tokens"), dict)]
    data.update(lecture=True, mode_counts=counts, open_items=open_items(case), decided_total=len(notes),
                sessions=len({r.get("session") for r in records if r.get("session")}),
                last=records[-1]["t"] if records else "", turns=len(tokens))
    page = template.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    return page.replace("</body>", OVERLAY + "\n</body>")


def write_board(case) -> Path:
    case = Path(case).resolve()
    out = case / OUT_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(case), encoding="utf-8", newline="\n")
    return out


def summary(case) -> str:
    """보고에 쓰는 한 줄: 맡는 쪽마다 끝난 항목 / 전체."""
    data_counts = {SKILL: [0, 0], AGENT: [0, 0], CPA: [0, 0]}
    records, notes = read_records(case), decided(case)
    for _, _, subs in STAGES:
        for _, _, skills, mode, globs, keys in subs:
            ev = evidence(case, records, skills, globs, keys, notes)
            data_counts[mode][1] += 1
            data_counts[mode][0] += _state(mode, ev, []) == "ok"
    name = case_info(case)["company"]
    return f"{name}: " + " · ".join(f"{k} {a}/{b}" for k, (a, b) in data_counts.items())


# 원본 화면이 그린 뒤 덧입힌다. 원본의 render 를 감싸고, 원본 함수와 클래스(box · badge · chip · mk · cmd)를 그대로 쓴다.
OVERLAY = r"""<style>
.who{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:700;line-height:1.5;border:1px solid currentColor;white-space:nowrap}
.who.sk{color:#1d6fd6}.who.ag{color:#0f8a5f}.who.cp{color:#b25e09}
.sub .who{margin-left:auto;font-size:10px}
.box .d{overflow-wrap:anywhere}
.whobar{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 14px}
.whobar .card{flex:1;min-width:150px}
</style>
<script>
(() => {
  if (!D.lecture) return;
  const CLS = {"스킬": "sk", "에이전트": "ag", "회계사": "cp"};
  const who = m => `<span class="who ${CLS[m]}">${esc(m)}</span>`;
  const hhmm = t => esc(String(t || "").replace("T", " ").slice(5, 16));
  const WHAT = {"스킬": "스킬 스크립트가 계산하고 에이전트는 결과를 옮깁니다.",
                "에이전트": "스킬 없이 맥락(규칙 · 전기조서 · 진행메모)만으로 에이전트가 초안을 씁니다.",
                "회계사": "에이전트는 선택지만 내고 회계사가 정합니다."};
  function boxes(it) {
    const e = it.lec;
    const runs = e.runs.length ? `<ul>${e.runs.map(r => `<li><span class="mk ok">✓</span><span>${esc(r.skill)} ${r.kind === "엔진" ? "스크립트 실행" : "스킬 부름"}<span class="d">${hhmm(r.t)}${r.cmd ? " · " + esc(r.cmd) : ""}</span></span></li>`).join("")}</ul>`
      : `<p class="empty">${it.skills.length ? "아직 이 스킬을 돌린 기록이 없습니다." : "이 항목은 스킬을 쓰지 않습니다."}</p>`;
    const files = e.files.length ? `<ul>${e.files.map(f => `<li><span class="mk ok">✓</span><span>${esc(f.path)}<span class="d">${f.t ? "이번 기록에서 씀 " + hhmm(f.t) : "폴더에 있음"}</span></span></li>`).join("")}</ul>`
      : `<p class="empty">${it.mode === "에이전트" ? "아직 에이전트가 쓴 파일이 없습니다." : "에이전트가 따로 쓰는 파일이 없습니다."}</p>`;
    const dec = e.decided.length ? `<ul>${e.decided.map(x => `<li><span class="mk ok">✓</span><span>${esc(x)}</span></li>`).join("")}</ul>`
      : `<p class="empty">${it.mode === "회계사" ? "진행메모 「정한 것」 에 아직 적힌 결정이 없습니다." : "이 항목에 걸린 결정이 없습니다."}</p>`;
    return `<div class="box"><h3>스킬 <span class="badge ${e.runs.length ? "pass" : "none"}">${e.run_count ? "실행 " + e.run_count : it.skills.length ? "아직" : "없음"}</span></h3>${runs}</div>
      <div class="box"><h3>에이전트 <span class="badge ${e.files.length ? "pass" : "none"}">${e.files.length ? "파일 " + e.files.length : "없음"}</span></h3>${files}</div>
      <div class="box"><h3>회계사 <span class="badge ${e.decided.length ? "pass" : it.mode === "회계사" ? "req" : "none"}">${e.decided.length ? "정한 것 " + e.decided.length : it.mode === "회계사" ? "정할 것" : "없음"}</span></h3>${dec}</div>`;
  }
  function deco() {
    document.querySelectorAll("#side .sub").forEach(b => {
      const it = D.stages[+b.dataset.s].items[+b.dataset.i];
      const sd = b.querySelector(".sd");
      if (sd) sd.className = "sd " + it.state;
      b.insertAdjacentHTML("beforeend", who(it.mode));
    });
    const main = document.querySelector("#main");
    if (state.view === "home") {
      const c = D.mode_counts;
      const lede = main.querySelector(".lede");
      if (lede) lede.textContent = "항목마다 스킬이 계산하는 일, 스킬 없이 에이전트가 쓰는 일, 회계사가 정하는 일을 나눠 보입니다. 근거는 훅 기록과 진행메모입니다.";
      const bar = `<h2>누가 했나</h2><div class="whobar">` + ["스킬", "에이전트", "회계사"].map(m =>
        `<div class="card"><div class="k">${who(m)}</div><div class="v">${c[m][0]} / ${c[m][1]}</div><div class="s">${esc(WHAT[m])}</div></div>`).join("") +
        `</div><p class="small muted">세션 ${D.sessions}번 · 마지막 기록 ${hhmm(D.last) || "없음"} · 진행메모 정한 것 ${D.decided_total} · 남은 일 ${D.open_items.length}</p>`;
      const cards = main.querySelector(".cards");
      if (cards) cards.insertAdjacentHTML("afterend", bar);
    } else if (state.view === "stage") {
      const s = D.stages[state.s];
      main.querySelectorAll("tbody tr.row").forEach((tr, j) => {
        const it = s.items[j], td = tr.children[2];
        if (it && td) td.innerHTML = who(it.mode) + (it.skills.length ? " " + it.skills.map(esc).join(" · ") : "");
      });
      const th = main.querySelector("thead th:nth-child(3)");
      if (th) th.textContent = "맡는 쪽 · 스킬";
    } else {
      const it = D.stages[state.s].items[state.i];
      const h1 = main.querySelector("h1");
      if (h1) h1.insertAdjacentHTML("beforeend", who(it.mode));
      if (h1) h1.insertAdjacentHTML("afterend", `<p class="lede">${esc(WHAT[it.mode])}</p>`);
      const cs = main.querySelectorAll(".cards .card");
      if (cs.length >= 3) {
        cs[1].innerHTML = `<div class="k">스킬 실행</div><div class="v">${it.lec.run_count}</div><div class="s">훅 기록</div>`;
        cs[2].innerHTML = `<div class="k">회계사가 정한 것</div><div class="v">${it.lec.decided.length}</div><div class="s">진행메모</div>`;
      }
      const grid = main.querySelector(".grid3");
      if (grid) grid.innerHTML = boxes(it);
      const chips = main.querySelector(".skills");
      if (chips && !it.skills.length) chips.innerHTML = `<span class="small muted">스킬 없이 하는 항목입니다.</span>`;
      main.querySelectorAll("h2").forEach(h => { if (h.textContent.trim() === "스킬 적용 현황") h.textContent = "누가 했나"; });
      main.querySelectorAll("p.empty").forEach(p => { if (p.textContent.startsWith("조서를 만들지 않는 항목")) p.textContent = "조서 파일을 만들지 않는 항목입니다."; });
    }
  }
  const base = render;
  render = function () { base(); deco(); };
  deco();
})();
</script>"""
