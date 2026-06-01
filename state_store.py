# state.json 로드/저장 — occurrence별 알림(stage) 발송 여부 및 완료(done) 상태.
#
# 구조:
# {
#   "occurrences": {
#     "komarketing:2026-06-04": {
#       "stages_sent": ["morning"],
#       "done": true,
#       "done_at": "2026-06-04T09:12:00+09:00",
#       "done_by": "telegram"        # telegram / local
#     }
#   },
#   "tg_last_update_id": 12345        # 텔레그램 getUpdates offset
# }

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
STATE_FILE = Path(__file__).parent / "state.json"


def load() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    data.setdefault("occurrences", {})
    data.setdefault("tg_last_update_id", 0)
    return data


def save(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _occ(state: dict, occ_id: str) -> dict:
    return state["occurrences"].setdefault(
        occ_id, {"stages_sent": [], "done": False, "done_at": None, "done_by": None}
    )


def is_done(state: dict, occ_id: str) -> bool:
    return bool(state["occurrences"].get(occ_id, {}).get("done"))


def is_suppressed(state: dict, occ_id: str, stage: str) -> bool:
    """완료됐거나 해당 stage를 이미 보냈으면 True (→ 발송 스킵)."""
    occ = state["occurrences"].get(occ_id)
    if not occ:
        return False
    if occ.get("done"):
        return True
    return stage in occ.get("stages_sent", [])


def mark_sent(state: dict, occ_id: str, stage: str) -> None:
    occ = _occ(state, occ_id)
    if stage not in occ["stages_sent"]:
        occ["stages_sent"].append(stage)


def mark_done(state: dict, occ_id: str, by: str = "telegram") -> bool:
    """완료 처리. 새로 완료 처리됐으면 True, 이미 완료였으면 False."""
    occ = _occ(state, occ_id)
    if occ.get("done"):
        return False
    occ["done"] = True
    occ["done_at"] = datetime.now(KST).isoformat()
    occ["done_by"] = by
    return True


def prune(state: dict, keep_days: int = 120) -> None:
    """오래된 occurrence 정리 (목표일 기준 keep_days 이전이면 삭제)."""
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=keep_days)
    dead = []
    for occ_id in state["occurrences"]:
        try:
            d = date.fromisoformat(occ_id.split(":", 1)[1])
        except Exception:
            continue
        if d < cutoff:
            dead.append(occ_id)
    for occ_id in dead:
        del state["occurrences"][occ_id]
