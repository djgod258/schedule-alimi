# 단발성(1회) 일정 저장소 — oneoff.json (git 공유)
#
# 형식:
# { "items": [ {"id": "20260615T1400-ab12", "datetime": "2026-06-15T14:00", "title": "치과예약"} ] }
#
# 완료 상태는 state.json(occ_id="oneoff:<id>")에서 관리한다. 여기엔 '정의'만 저장.

from __future__ import annotations

import re
import json
import secrets
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ONEOFF_FILE = Path(__file__).parent / "oneoff.json"
DEFAULT_HHMM = (8, 30)   # 시각 미지정 시 아침 08:30


def load_items() -> list[dict]:
    if ONEOFF_FILE.exists():
        try:
            return json.loads(ONEOFF_FILE.read_text(encoding="utf-8")).get("items", [])
        except Exception:
            return []
    return []


def save_items(items: list[dict]) -> None:
    ONEOFF_FILE.write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")


def add_item(dt_iso: str, title: str) -> str:
    items = load_items()
    iid = datetime.fromisoformat(dt_iso).strftime("%Y%m%dT%H%M") + "-" + secrets.token_hex(2)
    items.append({"id": iid, "datetime": dt_iso, "title": title})
    save_items(items)
    return iid


def remove_item(key: str) -> int:
    """id 전체 또는 끝부분(예: 마지막 4자리)으로 삭제. 삭제 개수 반환."""
    items = load_items()
    kept = [x for x in items if not (x["id"] == key or x["id"].endswith(key))]
    save_items(kept)
    return len(items) - len(kept)


def prune(keep_days: int = 1) -> int:
    """지난 일정 자동 삭제 — 일정 시각 + keep_days(기본 1일, catchup 14h 여유분 포함)
    가 지나면 더 이상 알림이 울리지 않으므로 oneoff.json에서 제거. 삭제 개수 반환."""
    cutoff = datetime.now(KST) - timedelta(days=keep_days)
    items = load_items()
    kept = []
    for x in items:
        try:
            dt = datetime.fromisoformat(x["datetime"]).replace(tzinfo=KST)
        except Exception:
            continue
        if dt >= cutoff:
            kept.append(x)
    removed = len(items) - len(kept)
    if removed:
        save_items(kept)
    return removed


def format_list() -> str:
    items = sorted(load_items(), key=lambda x: x["datetime"])
    if not items:
        return "📌 등록된 단발성 일정이 없습니다."
    lines = ["📌 <b>단발성 일정</b>"]
    for x in items:
        try:
            dt = datetime.fromisoformat(x["datetime"])
            when = f"{dt:%m/%d(%a) %H:%M}"
        except Exception:
            when = x["datetime"]
        lines.append(f"• {when}  {x['title']}  <code>[{x['id'][-4:]}]</code>")
    return "\n".join(lines)


def list_keyboard() -> list[list[dict]]:
    """/list 메시지에 붙일 인라인 버튼: 항목별 삭제 + 새로고침. 타이핑 없이 탭만으로 관리."""
    items = sorted(load_items(), key=lambda x: x["datetime"])
    rows = []
    for x in items:
        try:
            dt = datetime.fromisoformat(x["datetime"])
            when = f"{dt:%m/%d %H:%M}"
        except Exception:
            when = x["datetime"]
        title = x["title"][:14]
        rows.append([{"text": f"🗑 {when} {title}", "callback_data": f"ondel:{x['id']}"}])
    rows.append([{"text": "🔄 새로고침", "callback_data": "onlist"}])
    return rows


# ── 날짜/시각 파싱 ────────────────────────────────────────────────────────────
# 허용: "6/15 14:00", "2026-6-15 14:00", "6/15"(→08:30), "6-15 9시", "0615 1400"

_DT_PATTERNS = [
    r"(?P<y>\d{4})[-/.](?P<mo>\d{1,2})[-/.](?P<d>\d{1,2})",   # 2026-06-15
    r"(?P<mo>\d{1,2})[-/.](?P<d>\d{1,2})",                     # 6/15
]


def parse_datetime(s: str, now: datetime | None = None) -> tuple[str, str]:
    """'6/15 14:00 치과예약' → ("2026-06-15T14:00", "치과예약").

    연도 생략 시 올해(이미 지난 날짜면 내년). 시각 생략 시 08:30.
    실패하면 ValueError.
    """
    now = now or datetime.now(KST)
    s = s.strip()

    mdt = None
    for pat in _DT_PATTERNS:
        m = re.match(pat, s)
        if m:
            mdt = m
            break
    if not mdt:
        raise ValueError("날짜를 못 읽었어요. 예: /add 6/15 14:00 치과예약")

    rest = s[mdt.end():].strip()
    gd = mdt.groupdict()
    year = int(gd["y"]) if gd.get("y") else now.year
    month, day = int(gd["mo"]), int(gd["d"])

    # 시각: "14:00", "1400", "9시", "9시30분", 없으면 기본
    hh, mm = DEFAULT_HHMM
    tm = re.match(r"(?P<h>\d{1,2})(?::(?P<mi>\d{2})|시\s*(?:(?P<mi2>\d{1,2})분?)?|(?P<mi3>\d{2}))?", rest)
    if tm and tm.group("h"):
        hh = int(tm.group("h"))
        mi = tm.group("mi") or tm.group("mi2") or tm.group("mi3")
        mm = int(mi) if mi else 0
        rest = rest[tm.end():].strip()

    title = rest.strip() or "일정"
    try:
        dt = datetime(year, month, day, hh, mm, tzinfo=KST)
    except ValueError:
        raise ValueError("날짜/시각이 올바르지 않아요.")
    # 연도 생략했는데 이미 지난 날짜면 내년으로
    if not gd.get("y") and dt < now - timedelta(hours=12):
        dt = dt.replace(year=dt.year + 1)
    return dt.strftime("%Y-%m-%dT%H:%M"), title


HELP = (
    "📌 <b>단발성 일정 명령</b>\n"
    "• <code>/add 6/15 14:00 치과예약</code> — 추가(시각 생략 시 08:30)\n"
    "• <code>/list</code> — 목록 보기\n"
    "• <code>/del 끝4자리</code> — 삭제(목록의 [xxxx])"
)


def handle_command(text: str) -> str | None:
    """텔레그램/콘솔 명령 처리 → 답장 텍스트. (oneoff.json 변경 포함)"""
    text = text.strip()
    low = text.lower()

    if low.startswith("/help"):
        return HELP

    if low.startswith("/list"):
        return format_list()

    if low.startswith("/del"):
        key = text[4:].strip().lstrip(":").strip()
        if not key:
            return "삭제할 항목: <code>/del 끝4자리</code> (목록의 [xxxx])"
        n = remove_item(key)
        return f"🗑 {n}건 삭제됨." if n else f"'{key}'에 해당하는 일정이 없어요."

    if low.startswith("/add"):
        body = text[4:].strip()
        if not body:
            return "사용법: <code>/add 6/15 14:00 치과예약</code>"
        try:
            dt_iso, title = parse_datetime(body)
        except ValueError as e:
            return f"⚠️ {e}"
        add_item(dt_iso, title)
        dt = datetime.fromisoformat(dt_iso)
        return f"✅ 등록: {dt:%m/%d(%a) %H:%M}  {title}"

    return None
