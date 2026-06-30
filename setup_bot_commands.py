# 텔레그램 "/" 명령어 메뉴 등록 (1회 실행, 재등록해도 무해)
# 봇 토큰을 바꾸거나 명령을 추가/수정했을 때 다시 실행하면 됨.

from __future__ import annotations

import os
import requests

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

COMMANDS = [
    {"command": "add", "description": "일정 추가"},
    {"command": "list", "description": "일정 목록(단발성)"},
    {"command": "fixed", "description": "일정 목록(고정)"},
    {"command": "del", "description": "일정 삭제"},
    {"command": "help", "description": "도움말"},
]


def main() -> None:
    if not TOKEN:
        print("TELEGRAM_TOKEN 환경변수가 없습니다.")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/setMyCommands",
        json={"commands": COMMANDS},
        timeout=10,
    )
    print(r.json())


if __name__ == "__main__":
    main()
