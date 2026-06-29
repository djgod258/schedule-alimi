# 텔레그램 인박스(완료 콜백/명령) 처리 — run_cloud / run_local 공용
from __future__ import annotations

import logging

import notifier_telegram as tg
import state_store as ss
import oneoff_store as oneoff

log = logging.getLogger(__name__)


def process_inbox(state: dict, done_by: str) -> tuple[int, int]:
    """getUpdates로 완료/명령 수신·반영. (완료건수, 명령건수) 반환. state는 in-place 갱신."""
    done_ids, commands, new_offset = tg.fetch_updates(state.get("tg_last_update_id", 0))
    state["tg_last_update_id"] = new_offset

    for occ_id in done_ids:
        if ss.mark_done(state, occ_id, by=done_by):
            log.info(f"완료 처리: {occ_id}")
            tg.send_plain(f"☑️ <b>완료 확인</b> — 더 이상 알리지 않습니다.\n<code>{occ_id}</code>")

    for cmd in commands:
        if cmd.strip().lower().startswith("/list"):
            tg.send_with_buttons(oneoff.format_list(), oneoff.list_keyboard())
            log.info("명령: /list (버튼)")
            continue
        reply = oneoff.handle_command(cmd)
        if reply:
            log.info(f"명령: {cmd}")
            tg.send_plain(reply)

    return len(done_ids), len(commands)
