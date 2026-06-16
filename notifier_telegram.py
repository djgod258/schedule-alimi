# 텔레그램 발송(완료 인라인버튼) + getUpdates로 완료 콜백/명령 수신
#
# 환경변수: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
# (그랑죠알리미/monitor_cloud.py의 send_telegram 패턴 재사용 + reply_markup 추가)

from __future__ import annotations

import os
import json
import logging

import requests

log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def _enabled() -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("텔레그램 환경변수 없음 - 알림 스킵")
        return False
    return True


def send_reminder(message: str, occ_id: str) -> bool:
    """알림 메시지 + '✅ 완료' 인라인 버튼 전송."""
    if not _enabled():
        return False
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ 완료", "callback_data": f"done:{occ_id}"}
        ]]
    }
    try:
        resp = requests.post(f"{API}/sendMessage", data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard),
        }, timeout=10)
        if resp.ok:
            return True
        log.error(f"텔레그램 전송 실패: {resp.text}")
    except Exception as e:
        log.error(f"텔레그램 오류: {e}")
    return False


def send_plain(message: str) -> bool:
    if not _enabled():
        return False
    try:
        resp = requests.post(f"{API}/sendMessage", data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
        return resp.ok
    except Exception as e:
        log.error(f"텔레그램 오류: {e}")
        return False


def _answer_callback(callback_id: str, text: str = "완료 처리됨 ✅") -> None:
    try:
        requests.post(f"{API}/answerCallbackQuery", data={
            "callback_query_id": callback_id,
            "text": text,
        }, timeout=10)
    except Exception as e:
        log.error(f"answerCallbackQuery 오류: {e}")


def fetch_updates(last_update_id: int) -> tuple[list[str], list[str], int]:
    """getUpdates로 완료 신호 + 명령 텍스트 수집.

    완료 경로:
      1) 인라인버튼 콜백:  callback_data = "done:<occ_id>"
      2) 텍스트 명령:      "/done <occ_id>"  또는  "done:<occ_id>"
    명령 경로(단발성 일정):
      "/add 6/15 14:00 치과예약", "/list", "/del <id끝4자리>"
    반환: (완료된 occ_id 리스트, 명령 텍스트 리스트, 새 last_update_id)
    """
    if not _enabled():
        return [], [], last_update_id

    done_ids: list[str] = []
    commands: list[str] = []
    new_offset = last_update_id
    try:
        resp = requests.get(f"{API}/getUpdates", params={
            "offset": last_update_id + 1,
            "timeout": 0,
            "allowed_updates": json.dumps(["callback_query", "message"]),
        }, timeout=15)
        if not resp.ok:
            log.error(f"getUpdates 실패: {resp.text}")
            return [], [], last_update_id
        for upd in resp.json().get("result", []):
            new_offset = max(new_offset, upd.get("update_id", new_offset))

            cq = upd.get("callback_query")
            if cq:
                data = cq.get("data", "")
                if data.startswith("done:"):
                    done_ids.append(data[len("done:"):])
                    _answer_callback(cq.get("id", ""))
                continue

            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            if text.startswith("/done "):
                done_ids.append(text[len("/done "):].strip())
            elif text.startswith("done:"):
                done_ids.append(text[len("done:"):].strip())
            elif text.startswith(("/add", "/list", "/del", "/help")):
                commands.append(text)
    except Exception as e:
        log.error(f"getUpdates 오류: {e}")
        return [], [], last_update_id

    return done_ids, commands, new_offset


# 하위호환 별칭
def fetch_done_acks(last_update_id: int) -> tuple[list[str], int]:
    done_ids, _cmds, off = fetch_updates(last_update_id)
    return done_ids, off
