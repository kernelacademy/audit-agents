"""AI감사팀 화면(assets/AI감사팀.html)을 claude.ai 아티팩트로 올릴 게시용 파일로 만든다.

원본 HTML 의 그림 칸(__MASCOT__ · __HERO__)에 assets/img 의 그림을 data URI 로 넣는다.
화면의 고객사 · 인차지 · 세션 · 답변은 아티팩트 저장소(db)에 있고 이 파일에는 없다.
디자인은 Kernel Academy 「오늘의 AI 비타민」 을 따른다(2026-11-13)."""
from __future__ import annotations

import base64
from pathlib import Path

from paths import find_case
from status import get_publish_url, set_publish_url

ASSETS = Path(__file__).resolve().parents[1] / "assets"
PAGE = ASSETS / "AI감사팀.html"
IMAGES = {"__MASCOT__": "img/mascot.webp", "__HERO__": "img/hero.webp"}
PUBLISH_NAME = "_AI감사팀_게시.html"
URL_KEY = "team_artifact_url"


def build_page() -> str:
    """그림을 넣은 게시용 HTML. 문서 머리(doctype · html · head · body) 없이 title 부터 시작한다."""
    t = PAGE.read_text(encoding="utf-8")
    for key, rel in IMAGES.items():
        if key not in t:
            raise ValueError(f"그림 칸이 없습니다: {key}")
        t = t.replace(key, base64.b64encode((ASSETS / rel).read_bytes()).decode("ascii"))
    return t


def write_team_publish(root, cwd=None) -> Path:
    """회사 세션에서 돌리면 그 회사 폴더 _작업 아래, 아니면 감사 루트에 쓴다(세션 작업 폴더 안이라 올릴 수 있다)."""
    case = find_case(cwd) if cwd else None
    p = (case / "_작업" / "AI감사팀_게시.html") if case else Path(root).resolve() / PUBLISH_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build_page(), encoding="utf-8", newline="\n")
    return p


def get_team_url(root) -> str:
    return get_publish_url(root, URL_KEY)


def set_team_url(root, url: str) -> None:
    set_publish_url(root, url, URL_KEY)
