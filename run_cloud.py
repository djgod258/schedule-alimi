# GitHub Actions 진입점
#
# 흐름: 완료 콜백 수신 → 미발송 due 알림 발송 → state.json 저장 (워크플로가 git commit/push)
#
# 환경변수:
#   TELEGRAM_TOKEN, TELEGRAM_CHAT_ID  : 필수
#   FORCE_NOW="2026-05-31T21:00"      : (테스트용) 현재 KST 시각 강제
#   WINDOW_MIN="90"                   : (선택) 발송 윈도우, 기본 90분

from __future__ import annotations

import os
import logging
from datetime import datetime

import schedule_rules as sr
import state_store as ss
import notifier_telegram as tg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("run_cloud")


def _resolve_now() -> datetime:
    forced = os.environ.get("FORCE_NOW", "").strip()
    if forced:
        dt = datetime.fromisoformat(forced)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=sr.KST)
        log.info(f"[테스트] FORCE_NOW = {dt.isoformat()}")
        return dt.astimezone(sr.KST)
    return sr.now_kst()


def main() -> None:
    now = _resolve_now()
    window = int(os.environ.get("WINDOW_MIN", "90"))
    state = ss.load()

    # 1) 완료 신호 반영
    done_ids, new_offset = tg.fetch_done_acks(state.get("tg_last_update_id", 0))
    state["tg_last_update_id"] = new_offset
    for occ_id in done_ids:
        if ss.mark_done(state, occ_id, by="telegram"):
            log.info(f"완료 처리: {occ_id}")
            tg.send_plain(f"☑️ <b>완료 확인</b> — 더 이상 알리지 않습니다.\n<code>{occ_id}</code>")

    # 2) 발송 대상 계산 (클라우드는 자정 정각 'now' stage 제외 → 사전 스탠바이로 대비)
    due = sr.due_reminders(
        now, window,
        is_suppressed=lambda occ, stage: ss.is_suppressed(state, occ, stage),
        include_now_stage=False,
    )
    for r in due:
        if tg.send_reminder(r.message, r.occ_id):
            ss.mark_sent(state, r.occ_id, r.stage)
            log.info(f"발송: {r.occ_id} [{r.stage}] @ {r.fire_at:%m-%d %H:%M}")

    # 3) 정리 후 저장
    ss.prune(state)
    ss.save(state)
    log.info(f"완료 {len(done_ids)}건 / 발송 {len(due)}건 / now={now:%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()
