# 텔레그램 인박스(완료 콜백/명령/일반 답장) 처리 — run_cloud / run_local 공용
#
# fetch(네트워크, 느릴 수 있음)와 apply(상태 변경, 빠름)를 분리해 두었다.
# run_local처럼 락을 잡고 있으면 안 되는 긴 네트워크 대기(롱폴링)가 있는 호출부는
# fetch를 락 밖에서, apply만 락 안에서 부르면 된다. run_cloud처럼 짧게 한 번 확인하고
# 끝내는 경우는 process_inbox()로 fetch+apply를 한 번에 처리하면 된다.

from __future__ import annotations

import re
import logging

import notifier_telegram as tg
import state_store as ss
import oneoff_store as oneoff

log = logging.getLogger(__name__)

_BARE_ADD = re.compile(r"^/add\s*$", re.IGNORECASE)
_BARE_DEL = re.compile(r"^/del\s*$", re.IGNORECASE)


def _send_list_buttons() -> None:
    tg.send_with_buttons(oneoff.format_list(), oneoff.list_keyboard())


def fetch(last_update_id: int, timeout: int = 0):
    """텔레그램 getUpdates 호출(네트워크). timeout>0이면 롱폴링으로 대기.
    반환: (done_ids, commands, texts, new_offset) — 상태는 건드리지 않음."""
    return tg.fetch_updates(last_update_id, timeout=timeout)


def apply(state: dict, done_ids: list[str], commands: list[str], texts: list[str],
          done_by: str) -> tuple[int, int]:
    """fetch() 결과를 state에 반영 + 필요한 답장 발송. (완료건수, 명령+답장건수) 반환.
    state["tg_last_update_id"]는 호출 전에 이미 갱신돼 있어야 한다."""
    for occ_id in done_ids:
        if ss.mark_done(state, occ_id, by=done_by):
            log.info(f"완료 처리: {occ_id}")
            tg.send_plain(f"☑️ <b>완료 확인</b> — 더 이상 알리지 않습니다.\n<code>{occ_id}</code>")

    handled = 0
    for cmd in commands:
        stripped = cmd.strip()
        low = stripped.lower()

        if low.startswith("/list"):
            oneoff.set_awaiting_add(False)
            _send_list_buttons()
            log.info("명령: /list (버튼)")
            handled += 1
            continue

        if _BARE_DEL.match(stripped):
            # 메뉴에서 /del만 누르면 즉시 전송됨 → ID 타이핑 없이 삭제 버튼 목록을 바로 보여줌
            oneoff.set_awaiting_add(False)
            _send_list_buttons()
            log.info("명령: /del (버튼 목록)")
            handled += 1
            continue

        if _BARE_ADD.match(stripped):
            # 메뉴에서 /add만 누르면 즉시 전송됨 → 사용법 대신 ForceReply로 바로 입력받기
            oneoff.set_awaiting_add(True)
            tg.send_force_reply(
                "📌 추가할 일정을 입력해주세요\n"
                "예) 0630 1350 송금종이  /  6/15 14:00 치과예약\n"
                "(시각 생략 시 08:30)",
                placeholder="0630 1350 송금종이",
            )
            log.info("명령: /add (ForceReply 대기)")
            handled += 1
            continue

        oneoff.set_awaiting_add(False)
        reply = oneoff.handle_command(cmd)
        if reply:
            log.info(f"명령: {cmd}")
            tg.send_plain(reply)
            handled += 1

    # ForceReply로 받은 일반 텍스트 답장 → /add 본문으로 처리
    for text in texts:
        if not oneoff.is_awaiting_add():
            continue
        oneoff.set_awaiting_add(False)
        reply = oneoff.handle_command(f"/add {text}")
        if reply:
            log.info(f"/add 답장 처리: {text}")
            tg.send_plain(reply)
            handled += 1

    return len(done_ids), handled


def process_inbox(state: dict, done_by: str, timeout: int = 0) -> tuple[int, int]:
    """fetch + apply를 한 번에. 짧게 한 번 확인하고 끝내는 호출부(run_cloud)용."""
    done_ids, commands, texts, new_offset = fetch(state.get("tg_last_update_id", 0), timeout=timeout)
    state["tg_last_update_id"] = new_offset
    return apply(state, done_ids, commands, texts, done_by)
