"""회사제시 시산표로 정산표(WTB)를 만든다. 같은 입력이면 같은 숫자가 나온다.

읽기 · 계정 맞춤 · 합계 · 검산은 전부 이 스크립트가 한다. 엑셀에는 살아 있는 수식(SUMIF · SUM)을 쓰고,
엑셀이 있으면 한 번 계산시켜 스크립트 값과 대조한다. 엑셀 2010 함수만 쓴다.

    python wtb.py --시산표 TB.xlsx [--전기 전기WTB.xlsx] [--계정 계정과목표.xlsx]
                  [--분개장 JE.xlsx ...] [--수정 수정.csv] [--회사 이름] [--결산일 2025-12-31] --출력 폴더
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BS_KINDS = ("자산", "부채", "자본")
PL_KINDS = ("수익", "비용")
SIGN = {"자산": 1, "비용": 1, "부채": -1, "자본": -1, "수익": -1}  # 화면에 + 로 보이게 곱하는 값
CODE_RE = re.compile(r"^\s*\[?\s*(\d{3,7})\s*\]?\s*(.*)$")
NUM_FMT = '#,##0;[Red]-#,##0;"-"'


def norm(name) -> str:
    """계정 이름 비교용. 공백 · 점 · 괄호 안 영문 · 로마숫자 표시를 지운다."""
    s = re.sub(r"[\s.·]", "", str(name or ""))
    return s


def num(v) -> int:
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return round(v)
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return 0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = round(float(s))
    except ValueError:
        return 0
    return -x if neg else x


def rows_of(path: Path, sheet: str | None = None):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            return [tuple(r) for r in csv.reader(f)]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    out = [tuple(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return out


def header_labels(rows, n_head: int) -> list[str]:
    width = max(len(r) for r in rows[:n_head])
    labels = []
    for c in range(width):
        parts = []
        for r in rows[:n_head]:
            v = r[c] if c < len(r) else None
            if v is not None:
                t = re.sub(r"\s+", "", str(v))
                if t and t not in parts:
                    parts.append(t)
        labels.append(" ".join(parts))
    return labels


# ---------------------------------------------------------------- 시산표

@dataclass
class TBLine:
    order: int
    raw: str
    name: str
    code: int | None
    section: str  # 자산 · 부채 · 자본 · 손익
    sub: str      # 손익 안의 소제목(매출액 · 매출원가 …)
    debit: int
    credit: int

    @property
    def bal(self) -> int:
        return self.debit - self.credit


@dataclass
class TB:
    lines: list[TBLine]
    total_debit: int | None
    total_credit: int | None
    notes: list[str] = field(default_factory=list)


def read_tb(path: Path) -> TB:
    """합계잔액시산표. 머리글 두 줄(차변 잔액 · 합계 · 계정과목 · 대변 합계 · 잔액)이나 한 줄을 받는다.
    계정과목 칸이 「[10300]제예금」 이면 코드도 읽는다. 「<< 자산 >>」 · 「[ 유동자산 ]」 · 「< 당좌자산 >」 은 묶음 줄이다."""
    rows = rows_of(path)
    hi = next((i for i, r in enumerate(rows[:15]) if any("계정" in str(v or "") for v in r)), None)
    if hi is None:
        raise SystemExit(f"시산표에서 「계정과목」 머리글을 찾지 못했습니다: {path}")
    n_head = 2 if hi + 1 < len(rows) and any(k in norm(v) for v in rows[hi + 1] for k in ("잔액", "합계", "금액")) else 1
    labels = header_labels(rows[hi:], n_head)
    name_c = next(c for c, l in enumerate(labels) if "계정" in l and "코드" not in l)
    code_c = next((c for c, l in enumerate(labels) if "코드" in l), None)
    dr = [c for c, l in enumerate(labels) if "차" in l and "잔" in l]
    cr = [c for c, l in enumerate(labels) if "대" in l and "잔" in l]
    if not dr or not cr:  # 잔액 칸이 하나뿐인 표: 차변 · 대변 또는 잔액
        bal_c = next((c for c, l in enumerate(labels) if "잔액" in l), None)
        dr = [c for c, l in enumerate(labels) if l.startswith("차변")] or ([bal_c] if bal_c is not None else [])
        cr = [c for c, l in enumerate(labels) if l.startswith("대변")]
    if not dr:
        raise SystemExit(f"시산표에서 잔액 칸을 찾지 못했습니다: {labels}")
    dr_c, cr_c = dr[0], (cr[-1] if cr else None)
    lines, tot_d, tot_c = [], None, None
    section, sub = "", ""
    for r in rows[hi + n_head:]:
        raw = r[name_c] if name_c < len(r) else None
        if raw is None or str(raw).strip() == "":
            continue
        s = str(raw).strip()
        compact = norm(s)
        d = num(r[dr_c]) if dr_c < len(r) else 0
        c = num(r[cr_c]) if cr_c is not None and cr_c < len(r) else 0
        if compact in ("합계", "총계"):
            tot_d, tot_c = d, c
            continue
        m = CODE_RE.match(s)
        code = None
        if code_c is not None and code_c < len(r) and r[code_c] not in (None, ""):
            try:
                code = int(str(r[code_c]).strip())
            except ValueError:
                code = None
        if m and m.group(2):
            code, s = int(m.group(1)), m.group(2).strip()
            compact = norm(s)
        elif s[:1] in "<[《〈【":
            inner = compact.strip("<>[]《》〈〉【】")
            if s.startswith("<<") or s.startswith("《"):
                section = next((k for k in ("자산", "부채", "자본", "손익") if k in inner), section)
                sub = ""
            else:
                sub = inner
            continue
        lines.append(TBLine(len(lines), str(raw).strip(), compact, code, section, sub, d, c))
    tb = TB(lines, tot_d, tot_c)
    return tb


# ---------------------------------------------------------------- 계정 정보

@dataclass
class Acct:
    code: int
    name: str
    disp: str = ""
    kind: str = ""
    prior: int = 0          # 전기 최종(차변 +)
    prior_given: bool = False
    parent: int | None = None


def read_prior_wtb(path: Path) -> dict[int, Acct]:
    """전기 정산표에서 계정코드 · 계정과목 · 표시과목 · 구분 · 최종을 읽는다. 머리글에 「계정코드」 와 「표시과목」 이 있는 시트."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
            for i, r in enumerate(rows[:15]):
                labels = [re.sub(r"\s+", "", str(v or "")) for v in r]
                if "계정코드" in labels and "표시과목" in labels:
                    ix = {l: j for j, l in enumerate(labels) if l}
                    fin = ix.get("최종", ix.get("Final"))
                    out: dict[int, Acct] = {}
                    for row in rows[i + 1:]:
                        try:
                            code = int(str(row[ix["계정코드"]]).strip())
                        except (TypeError, ValueError):
                            continue
                        out[code] = Acct(code, norm(row[ix.get("계정과목", ix["계정코드"] + 1)]),
                                         str(row[ix["표시과목"]] or "").strip(),
                                         str(row[ix["구분"]] or "").strip() if "구분" in ix else "",
                                         num(row[fin]) if fin is not None else 0, fin is not None)
                    return out
    finally:
        wb.close()
    raise SystemExit(f"전기 정산표에서 「계정코드」 · 「표시과목」 머리글이 있는 시트를 찾지 못했습니다: {path}")


def read_chart(path: Path) -> dict[int, Acct]:
    """계정과목표: 계정코드 · 계정과목(명) · (상위 코드 LINK_CD)."""
    rows = rows_of(path)
    hi = next(i for i, r in enumerate(rows[:10]) if any("코드" in str(v or "") for v in r))
    labels = [re.sub(r"\s+", "", str(v or "")) for v in rows[hi]]
    code_c = next(j for j, l in enumerate(labels) if "코드" in l and "LINK" not in l.upper() and "상위" not in l)
    name_c = next(j for j, l in enumerate(labels) if "과목" in l or "계정명" in l)
    par_c = next((j for j, l in enumerate(labels) if "LINK" in l.upper() or "상위" in l), None)
    out = {}
    for r in rows[hi + 1:]:
        try:
            code = int(str(r[code_c]).strip())
        except (TypeError, ValueError):
            continue
        par = None
        if par_c is not None:
            try:
                par = int(str(r[par_c]).strip())
            except (TypeError, ValueError):
                par = None
        out[code] = Acct(code, norm(r[name_c]), parent=par)
    return out


def kind_of(line: TBLine) -> str:
    if line.section in BS_KINDS:
        return line.section
    sub = line.sub
    if any(k in sub for k in ("매출원가", "판매", "관리비", "영업외비용", "법인세", "비용")):
        return "비용"
    if any(k in sub for k in ("매출", "수익")):
        return "수익"
    return "비용" if line.bal >= 0 else "수익"


def kind_by_code(code: int) -> str:
    """더존 코드대역. 이름과 시산표 묶음으로 못 정할 때만 쓴다."""
    k = code // 100 if code >= 10000 else code
    if k <= 250:
        return "자산"
    if k <= 330:
        return "부채"
    if k <= 400:
        return "자본"
    if k <= 450 or 901 <= k <= 930:
        return "수익"
    return "비용"


@dataclass
class Row:
    code: int
    name: str
    disp: str
    kind: str
    given: int
    prior: int
    flags: list[str] = field(default_factory=list)


def map_accounts(tb: TB, prior: dict[int, Acct], chart: dict[int, Acct]) -> list[Row]:
    """시산표 계정마다 코드를 정한다. 이름이 같은 계정이 여럿이면(감가상각누계액) 바로 앞 계정보다 큰 코드 가운데 가장 작은 것."""
    by_name: dict[str, list[int]] = {}
    for src in (prior, chart):
        for code, a in sorted(src.items()):
            if code not in by_name.setdefault(a.name, []):
                by_name[a.name].append(code)
    rows: dict[int, Row] = {}
    prev = 0
    for ln in tb.lines:
        flags = []
        code = ln.code
        if code is None:
            cands = sorted(c for c in by_name.get(ln.name, []) if c not in rows)
            if len(cands) == 1:
                code = cands[0]
            elif cands:
                after = [c for c in cands if c > prev]
                code = after[0] if after else cands[0]
                flags.append(f"이름이 같은 계정 {len(cands)}개 중 바로 앞 계정 다음 코드로 맞춤")
            else:
                code = 990000 + ln.order
                flags.append("계정코드를 찾지 못함: 계정과목표나 전기 정산표에 이 이름이 없다")
        prev = code
        p = prior.get(code)
        kind = kind_of(ln) if ln.section else (p.kind if p and p.kind else kind_by_code(code))
        if p and p.kind and p.kind != kind:
            flags.append(f"구분이 전기({p.kind})와 다름")
        disp = p.disp if p and p.disp else ln.raw if not ln.code else ln.raw.split("]", 1)[-1].strip()
        if not (p and p.disp):
            flags.append("새 계정: 표시과목을 계정과목 이름으로 두었다")
        if code in rows:
            rows[code].given += ln.bal
            rows[code].flags.append("시산표에 같은 코드가 두 번 나와 더함")
        else:
            rows[code] = Row(code, re.sub(r"\s+", "", ln.raw.split("]", 1)[-1]), disp, kind, ln.bal,
                             p.prior if p else 0, flags)
    for code, p in prior.items():  # 전기에만 있는 계정도 줄을 둔다(전기 열이 빠지지 않게)
        if code not in rows and p.prior != 0:
            rows[code] = Row(code, p.name, p.disp or p.name, p.kind or kind_by_code(code), 0, p.prior,
                             ["당기 시산표에 없는 계정(전기에만 잔액)"])
    return [rows[c] for c in sorted(rows)]


# ---------------------------------------------------------------- 분개장 · 수정분개

def read_journal(paths: list[Path], codes: set[int], chart: dict[int, Acct], name_to_code: dict[str, int]):
    """분개장에서 계정별 차변 · 대변 합계. (가) 한 줄 한 계정(계정 · 차변 · 대변) (나) 차변 계정 · 대변 계정이 다른 칸."""
    dr: dict[int, int] = {}
    cr: dict[int, int] = {}
    unknown: dict[str, int] = {}
    n = 0

    def to_code(cell) -> int | None:
        if cell in (None, ""):
            return None
        m = CODE_RE.match(str(cell))
        if m and m.group(2):
            c = int(m.group(1))
        else:
            c = name_to_code.get(norm(cell))
            if c is None:
                unknown[str(cell)] = unknown.get(str(cell), 0) + 1
                return None
        seen = set()
        while c not in codes and c not in seen:
            seen.add(c)
            par = chart.get(c).parent if c in chart else None
            c = par if par and par >= 10000 else (c // 100) * 100
        return c if c in codes else None

    for p in paths:
        rows = rows_of(p)
        hi = next(i for i, r in enumerate(rows[:15]) if sum("변" in str(v or "") for v in r) >= 2)
        n_head = 2 if any(k in norm(v) for v in rows[hi + 1] for k in ("금액", "계정")) else 1
        lab = header_labels(rows[hi:], n_head)
        dra = next((c for c, l in enumerate(lab) if "차변" in l and "금액" in l), None)
        dac = next((c for c, l in enumerate(lab) if "차변" in l and "계정" in l), None)
        cac = next((c for c, l in enumerate(lab) if "대변" in l and "계정" in l), None)
        cra = next((c for c, l in enumerate(lab) if "대변" in l and "금액" in l), None)
        if None in (dra, cra):
            dra = next(c for c, l in enumerate(lab) if l.startswith("차변"))
            cra = next(c for c, l in enumerate(lab) if l.startswith("대변"))
        if dac is None or cac is None:  # (가) 한 줄 한 계정
            acc = next(c for c, l in enumerate(lab) if "계정" in l and "코드" not in l)
            dac = cac = acc
        for r in rows[hi + n_head:]:
            if not any(v not in (None, "") for v in r):
                continue
            n += 1
            d, c = num(r[dra]), num(r[cra])
            if d:
                k = to_code(r[dac])
                if k is not None:
                    dr[k] = dr.get(k, 0) + d
            if c:
                k = to_code(r[cac])
                if k is not None:
                    cr[k] = cr.get(k, 0) + c
    return dr, cr, unknown, n


def read_adjustments(path: Path | None) -> list[dict]:
    """수정분개: 계정코드 · 차변 · 대변 · 내역 · 근거(· 번호 · 구분). 한 줄에 계정 하나."""
    if not path:
        return []
    rows = rows_of(path)
    hi = next(i for i, r in enumerate(rows[:10]) if any("코드" in str(v or "") for v in r))
    lab = [re.sub(r"\s+", "", str(v or "")) for v in rows[hi]]

    def col(*keys):
        return next((j for j, l in enumerate(lab) if any(k in l for k in keys)), None)
    c_code, c_dr, c_cr = col("코드"), col("차변"), col("대변")
    c_desc, c_basis, c_no, c_kind = col("내역", "적요"), col("근거"), col("번호", "No"), col("구분")
    out = []
    for r in rows[hi + 1:]:
        try:
            code = int(str(r[c_code]).strip())
        except (TypeError, ValueError):
            continue
        g = lambda c: (r[c] if c is not None and c < len(r) else None)
        out.append({"no": g(c_no), "kind": g(c_kind) or "AJE", "desc": g(c_desc) or "", "code": code,
                    "dr": num(g(c_dr)), "cr": num(g(c_cr)), "basis": g(c_basis) or ""})
    return out


# ---------------------------------------------------------------- 계산

def compute(rows: list[Row], adj: list[dict], journal=None, prior_pl_sum: int = 0):
    adr, acr = {}, {}
    for a in adj:
        adr[a["code"]] = adr.get(a["code"], 0) + a["dr"]
        acr[a["code"]] = acr.get(a["code"], 0) + a["cr"]
    final = {r.code: r.given + adr.get(r.code, 0) - acr.get(r.code, 0) for r in rows}
    tot = lambda f: sum(f(r) for r in rows)
    kinds = {k: sum(final[r.code] for r in rows if r.kind == k) for k in SIGN}
    ni = -(kinds["수익"] + kinds["비용"])  # 당기순이익(이익 +)
    res = {
        "회사제시 합계": tot(lambda r: r.given),
        "수정 차변": sum(adr.values()), "수정 대변": sum(acr.values()),
        "최종 합계": sum(final.values()),
        "전기 최종 합계": tot(lambda r: r.prior),
        "자산": kinds["자산"], "부채": -kinds["부채"], "자본(당기순이익 전)": -kinds["자본"], "당기순이익": ni,
    }
    res["자산 - (부채 + 자본 + 당기순이익)"] = res["자산"] - res["부채"] - res["자본(당기순이익 전)"] - ni
    recon = []
    if journal is not None:
        jdr, jcr = journal
        ret_code = next((r.code for r in rows if r.kind == "자본" and ("결손금" in r.name or "이익잉여금" in r.name)), None)
        for r in rows:
            opening = 0 if r.kind in PL_KINDS else r.prior
            if r.code == ret_code:
                opening += prior_pl_sum
            calc = opening + jdr.get(r.code, 0) - jcr.get(r.code, 0)
            recon.append({"code": r.code, "name": r.name, "opening": opening, "dr": jdr.get(r.code, 0),
                          "cr": jcr.get(r.code, 0), "calc": calc, "given": r.given, "diff": calc - r.given})
    return final, res, recon


def fingerprint(rows: list[Row], final: dict[int, int]) -> str:
    s = "\n".join(f"{r.code}\t{r.disp}\t{r.kind}\t{r.given}\t{final[r.code]}\t{r.prior}" for r in rows)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- 워크북

HEAD = Font(bold=True)
FILL_HEAD = PatternFill("solid", fgColor="DDE7F3")
FILL_IN = PatternFill("solid", fgColor="FFF5CC")
FILL_FLAG = PatternFill("solid", fgColor="FCE4E4")


def _head(ws, row: int, labels: list[str], widths: list[int] | None = None):
    for j, l in enumerate(labels, 1):
        c = ws.cell(row, j, l)
        c.font, c.fill = HEAD, FILL_HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row + 1, 1)


def _money(ws, cells):
    for c in cells:
        c.number_format = NUM_FMT


def write_workbook(out: Path, title: str, rows: list[Row], adj: list[dict], recon, res, tb: TB, fp: str):
    wb = openpyxl.Workbook()
    # 검산 시트는 맨 앞, 수식은 다른 시트를 본다
    ws_chk = wb.active
    ws_chk.title = "검산"
    ws = wb.create_sheet("TB")
    n = len(rows)
    first, last = 5, 4 + n
    ws["A1"] = f"정산표(WTB) · {title}"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "회사제시는 회사가 낸 합계잔액시산표(차변 +, 대변 -). 수정 차변 · 대변은 AJE 시트를 계정코드로 SUMIF 한다. 숫자는 스크립트가 넣고 손으로 고치지 않는다. 수정은 AJE 시트에 줄을 더한다."
    _head(ws, 4, ["계정코드", "계정과목", "표시과목", "구분", "회사제시", "수정 차변", "수정 대변", "최종", "전기 최종", "증감", "확인"],
          [10, 18, 22, 7, 17, 15, 15, 17, 17, 16, 46])
    for i, r in enumerate(rows):
        x = first + i
        ws.cell(x, 1, r.code)
        ws.cell(x, 2, r.name)
        ws.cell(x, 3, r.disp)
        ws.cell(x, 4, r.kind)
        ws.cell(x, 5, r.given)
        ws.cell(x, 6, f"=SUMIF(AJE!$E:$E,$A{x},AJE!$G:$G)")
        ws.cell(x, 7, f"=SUMIF(AJE!$E:$E,$A{x},AJE!$H:$H)")
        ws.cell(x, 8, f"=E{x}+F{x}-G{x}")
        ws.cell(x, 9, r.prior)
        ws.cell(x, 10, f"=H{x}-I{x}")
        if r.flags:
            ws.cell(x, 11, " / ".join(r.flags)).fill = FILL_FLAG
        _money(ws, [ws.cell(x, j) for j in range(5, 11)])
    t = last + 1
    ws.cell(t, 2, "합계").font = HEAD
    for j in range(5, 11):
        L = get_column_letter(j)
        ws.cell(t, j, f"=SUM({L}{first}:{L}{last})").font = HEAD
        _money(ws, [ws.cell(t, j)])
    rng = lambda L: f"TB!${L}${first}:${L}${last}"

    # AJE
    wa = wb.create_sheet("AJE")
    wa["A1"] = "감사 수정분개(AJE) · 재분류(RJE)"
    wa["A1"].font = Font(bold=True, size=13)
    wa["A2"] = "한 줄에 계정 하나. 노란 칸에 적고 TB 시트가 계정코드로 가져간다. 반영 여부는 회계사가 정한다."
    _head(wa, 4, ["번호", "구분", "내역", "계정과목", "계정코드", "근거", "차변", "대변"], [7, 7, 40, 18, 10, 40, 15, 15])
    names = {r.code: r.name for r in rows}
    a_first = 5
    for i, a in enumerate(adj):
        x = a_first + i
        for j, v in enumerate([a["no"], a["kind"], a["desc"], names.get(a["code"], "(정산표에 없는 코드)"), a["code"], a["basis"], a["dr"], a["cr"]], 1):
            wa.cell(x, j, v)
        _money(wa, [wa.cell(x, 7), wa.cell(x, 8)])
    a_last = a_first + max(len(adj), 1) - 1 + 30  # 회계사가 더 적을 칸
    for x in range(a_first + len(adj), a_last + 1):
        for j in (1, 2, 3, 5, 6, 7, 8):
            wa.cell(x, j).fill = FILL_IN
        wa.cell(x, 4, f'=IF(E{x}="","",IFERROR(INDEX(TB!$B:$B,MATCH(E{x},TB!$A:$A,0)),"(정산표에 없는 코드)"))')
        _money(wa, [wa.cell(x, 7), wa.cell(x, 8)])
    at = a_last + 1
    wa.cell(at, 3, "합계").font = HEAD
    wa.cell(at, 7, f"=SUM(G{a_first}:G{a_last})")
    wa.cell(at, 8, f"=SUM(H{a_first}:H{a_last})")
    _money(wa, [wa.cell(at, 7), wa.cell(at, 8)])

    # 재무상태표 · 손익계산서
    def statement(name: str, kinds: tuple[str, ...], ni_line: bool):
        s = wb.create_sheet(name)
        s["A1"] = f"{name} · 정산표 표시과목으로 묶음"
        s["A1"].font = Font(bold=True, size=13)
        s["A2"] = "TB 시트를 표시과목으로 SUMIF 한다. 자산 · 비용은 차변, 부채 · 자본 · 수익은 대변을 + 로 보인다."
        _head(s, 4, ["표시과목", "구분", "회사제시", "최종", "전기 최종", "증감", "증감률"], [26, 7, 17, 17, 17, 16, 9])
        x = 5
        subtot = {}
        for k in kinds:
            disps = []
            for r in rows:
                if r.kind == k and r.disp not in disps:
                    disps.append(r.disp)
            start = x
            for d in disps:
                sg = SIGN[k]
                s.cell(x, 1, d)
                s.cell(x, 2, k)
                for j, L in ((3, "E"), (4, "H"), (5, "I")):
                    s.cell(x, j, f'=SUMIFS({rng(L)},{rng("C")},$A{x},{rng("D")},$B{x})*{sg}')
                s.cell(x, 6, f"=D{x}-E{x}")
                s.cell(x, 7, f'=IF(E{x}=0,"",F{x}/ABS(E{x}))').number_format = "0.0%"
                _money(s, [s.cell(x, j) for j in range(3, 7)])
                x += 1
            s.cell(x, 1, f"{k} 합계").font = HEAD
            for j in range(3, 7):
                L = get_column_letter(j)
                s.cell(x, j, f"=SUM({L}{start}:{L}{x - 1})" if x > start else 0).font = HEAD
                _money(s, [s.cell(x, j)])
            subtot[k] = x
            x += 2
        if ni_line:
            s.cell(x, 1, "당기순이익").font = HEAD
            for j in range(3, 7):
                L = get_column_letter(j)
                s.cell(x, j, f"={L}{subtot['수익']}-{L}{subtot['비용']}").font = HEAD
                _money(s, [s.cell(x, j)])
            subtot["당기순이익"] = x
        return s, subtot

    _, bs_tot = statement("재무상태표", BS_KINDS, False)
    _, pl_tot = statement("손익계산서", PL_KINDS, True)

    # 분개장 대사
    if recon:
        wj = wb.create_sheet("분개장 대사")
        wj["A1"] = "분개장 대사: 기초 + 분개장 차변 - 대변 = 시산표 회사제시"
        wj["A1"].font = Font(bold=True, size=13)
        wj["A2"] = "기초는 전기 최종(손익 계정은 0, 결손금 · 이익잉여금 계정에는 전기 손익을 더함). 차이가 있으면 전기 수정분개가 회사 장부에 안 들어갔거나, 분개장이 빠졌거나, 시산표가 다른 판이다."
        _head(wj, 4, ["계정코드", "계정과목", "기초", "분개장 차변", "분개장 대변", "계산 기말", "시산표 회사제시", "차이"], [10, 18, 17, 17, 17, 17, 17, 16])
        for i, rc in enumerate(recon):
            x = 5 + i
            for j, v in enumerate([rc["code"], rc["name"], rc["opening"], rc["dr"], rc["cr"]], 1):
                wj.cell(x, j, v)
            wj.cell(x, 6, f"=C{x}+D{x}-E{x}")
            wj.cell(x, 7, f"=INDEX(TB!$E:$E,MATCH(A{x},TB!$A:$A,0))")
            wj.cell(x, 8, f"=F{x}-G{x}")
            if rc["diff"]:
                wj.cell(x, 8).fill = FILL_FLAG
            _money(wj, [wj.cell(x, j) for j in range(3, 9)])
        j_last = 4 + len(recon)

    # 검산
    ws_chk["A1"] = f"검산 · {title}"
    ws_chk["A1"].font = Font(bold=True, size=13)
    ws_chk["A2"] = f"값 지문 {fp} (계정 · 표시과목 · 구분 · 회사제시 · 최종 · 전기가 하나라도 다르면 바뀐다)"
    _head(ws_chk, 4, ["검산", "엑셀 수식 값", "스크립트 값", "판정", "뜻"], [36, 18, 18, 9, 60])
    checks = [
        ("시산표 회사제시 합계 = 0", f"=SUM({rng('E')})", res["회사제시 합계"], "차변 잔액 합계와 대변 잔액 합계가 같다"),
        ("수정 차변 - 수정 대변 = 0", f"=SUM(AJE!G{a_first}:G{a_last})-SUM(AJE!H{a_first}:H{a_last})", res["수정 차변"] - res["수정 대변"], "수정분개가 차대 일치한다"),
        ("최종 합계 = 0", f"=SUM({rng('H')})", res["최종 합계"], "수정 후에도 차대 일치한다"),
        ("자산 - (부채 + 자본 + 당기순이익) = 0",
         f"=재무상태표!D{bs_tot['자산']}-재무상태표!D{bs_tot['부채']}-재무상태표!D{bs_tot['자본']}-손익계산서!D{pl_tot['당기순이익']}",
         res["자산 - (부채 + 자본 + 당기순이익)"], "마감 전 시산표라 당기순이익을 자본에 더해 본다"),
        ("전기 최종 합계 = 0", f"=SUM({rng('I')})", res["전기 최종 합계"], "전기 정산표를 빠짐없이 읽었다"),
    ]
    if recon:
        checks.append(("분개장 대사 차이 계정 수", f"=COUNTIF('분개장 대사'!H5:H{j_last},\"<>0\")",
                       sum(1 for rc in recon if rc["diff"]), "0 이 아니면 분개장 대사 시트의 빨간 칸을 본다"))
    for i, (label, formula, val, mean) in enumerate(checks):
        x = 5 + i
        ws_chk.cell(x, 1, label)
        ws_chk.cell(x, 2, formula)
        ws_chk.cell(x, 3, val)
        ws_chk.cell(x, 4, f'=IF(AND(B{x}=0,C{x}=0),"OK","확인")')
        ws_chk.cell(x, 5, mean)
        _money(ws_chk, [ws_chk.cell(x, 2), ws_chk.cell(x, 3)])
    x = 6 + len(checks)
    ws_chk.cell(x, 1, "시산표 읽기").font = HEAD
    ws_chk.cell(x + 1, 1, "읽은 계정 줄 차변 잔액 합계")
    ws_chk.cell(x + 1, 3, sum(l.debit for l in tb.lines))
    ws_chk.cell(x + 2, 1, "시산표 합계 줄 차변 잔액")
    ws_chk.cell(x + 2, 3, tb.total_debit)
    ws_chk.cell(x + 3, 1, "읽은 계정 줄 대변 잔액 합계")
    ws_chk.cell(x + 3, 3, sum(l.credit for l in tb.lines))
    ws_chk.cell(x + 4, 1, "시산표 합계 줄 대변 잔액")
    ws_chk.cell(x + 4, 3, tb.total_credit)
    _money(ws_chk, [ws_chk.cell(x + k, 3) for k in range(1, 5)])
    wb.properties.creator = "audit-agents WTB정산표"
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return {"checks": [(c[0], c[2]) for c in checks]}


# ---------------------------------------------------------------- 엑셀 재계산 대조

def excel_check(path: Path, rows: list[Row], final: dict[int, int]) -> str:
    """엑셀로 한 번 계산시켜 TB 최종 열과 검산 판정을 스크립트 값과 대조한다. 엑셀이 없으면 「재계산 못 함」."""
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return "재계산 못 함(엑셀 연동 모듈 없음)"
    xl = None
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(str(path.resolve()))
        xl.CalculateFull()
        ws = wb.Worksheets("TB")
        bad = []
        for i, r in enumerate(rows):
            v = ws.Cells(5 + i, 8).Value
            if v is None or round(v) != final[r.code]:
                bad.append(f"{r.code} 엑셀 {v} · 스크립트 {final[r.code]}")
        chk = wb.Worksheets("검산")
        verdicts = []
        x = 5
        while chk.Cells(x, 1).Value:
            verdicts.append((chk.Cells(x, 1).Value, chk.Cells(x, 4).Value))
            x += 1
        wb.Save()
        wb.Close(False)
        if bad:
            return "엑셀 대조 FAIL: " + "; ".join(bad[:5])
        nok = [a for a, v in verdicts if v != "OK"]
        return "엑셀 대조 PASS" + (f" (검산 확인: {', '.join(nok)})" if nok else "")
    except Exception as e:  # 엑셀 창이 막혀 있거나 라이선스 문제
        return f"재계산 못 함({type(e).__name__}: {e})"
    finally:
        if xl is not None:
            try:
                xl.Quit()
            except Exception:
                pass


# ---------------------------------------------------------------- 실행

def run(a) -> int:
    tb = read_tb(Path(a.시산표))
    prior = read_prior_wtb(Path(a.전기)) if a.전기 else {}
    chart = read_chart(Path(a.계정)) if a.계정 else {}
    rows = map_accounts(tb, prior, chart)
    adj = read_adjustments(Path(a.수정) if a.수정 else None)
    have = {r.code for r in rows}
    for code in sorted({x["code"] for x in adj} - have):  # 수정분개로 처음 생기는 계정(미수금 · 선급금 …)
        src = prior.get(code) or chart.get(code)
        nm = src.name if src else f"계정{code}"
        rows.append(Row(code, nm, (prior[code].disp if code in prior and prior[code].disp else nm),
                        (prior[code].kind if code in prior and prior[code].kind else kind_by_code(code)), 0,
                        prior[code].prior if code in prior else 0,
                        ["수정분개로 생긴 계정" + ("" if src else ": 계정과목표에 없는 코드")]))
    rows.sort(key=lambda r: r.code)
    journal, unknown, n_je = None, {}, 0
    if a.분개장:
        name_to_code = {r.name: r.code for r in rows}
        for code, ac in chart.items():
            name_to_code.setdefault(ac.name, code)
        jdr, jcr, unknown, n_je = read_journal([Path(p) for p in a.분개장], {r.code for r in rows}, chart, name_to_code)
        journal = (jdr, jcr)
    prior_pl = sum(p.prior for p in prior.values() if p.kind in PL_KINDS)
    final, res, recon = compute(rows, adj, journal, prior_pl)
    fp = fingerprint(rows, final)
    title = " · ".join(x for x in (a.회사, a.결산일) if x) or Path(a.시산표).stem
    out_dir = Path(a.출력)
    stem = f"WTB_{a.회사 or 'company'}_{(a.결산일 or '').replace('-', '')}".rstrip("_")
    out = out_dir / f"{stem}.xlsx"
    write_workbook(out, title, rows, adj, recon, res, tb, fp)

    read_ok = tb.total_debit is None or (sum(l.debit for l in tb.lines) == tb.total_debit and sum(l.credit for l in tb.lines) == tb.total_credit)
    zero_ok = res["회사제시 합계"] == 0 and res["수정 차변"] == res["수정 대변"] and res["최종 합계"] == 0 \
        and res["자산 - (부채 + 자본 + 당기순이익)"] == 0
    diffs = [rc for rc in recon if rc["diff"]]
    flagged = [r for r in rows if r.flags]
    xl = "재계산 안 함" if a.재계산없음 else excel_check(out, rows, final)
    summary = {
        "출력": str(out), "값 지문": fp, "계정 수": len(rows), "시산표 줄": len(tb.lines),
        "시산표 읽기": "PASS" if read_ok else "FAIL", "차대 검산": "PASS" if zero_ok else "FAIL",
        "검산 값": res, "엑셀": xl,
        "확인할 계정": [{"코드": r.code, "계정": r.name, "확인": r.flags} for r in flagged],
        "분개장": {"줄": n_je, "차이 계정": [{k: rc[k] for k in ("code", "name", "calc", "given", "diff")} for rc in diffs],
                 "코드 못 찾은 계정": unknown} if journal else None,
    }
    (out_dir / f"검증_{stem}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"출력 {out}")
    print(f"계정 {len(rows)}개 · 확인할 계정 {len(flagged)}개 · 값 지문 {fp}")
    if journal:
        print(f"분개장 {n_je}줄 · 대사 차이 계정 {len(diffs)}개" + (f" · 코드 못 찾은 계정 {len(unknown)}개" if unknown else ""))
    print(f"시산표 읽기 {summary['시산표 읽기']}  차대 검산 {summary['차대 검산']}  {xl}")
    return 0 if read_ok and zero_ok and not xl.startswith("엑셀 대조 FAIL") else 1


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="wtb.py", description="회사제시 시산표로 정산표(WTB)를 만든다")
    ap.add_argument("--시산표", required=True, help="회사제시 합계잔액시산표 xlsx")
    ap.add_argument("--전기", help="전기 정산표(WTB) xlsx. 계정코드 · 표시과목 · 구분 · 전기 최종을 가져온다")
    ap.add_argument("--계정", help="계정과목표 xlsx(계정코드 · 계정과목명 · 상위 코드)")
    ap.add_argument("--분개장", nargs="*", help="당기 분개장 xlsx. 주면 분개장 대사 시트를 만든다")
    ap.add_argument("--수정", help="수정분개 csv · xlsx(계정코드 · 차변 · 대변 · 내역 · 근거)")
    ap.add_argument("--회사", default="")
    ap.add_argument("--결산일", default="")
    ap.add_argument("--출력", required=True)
    ap.add_argument("--재계산없음", action="store_true", help="엑셀 재계산 대조를 건너뛴다")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
