# PC 진입점 — 상주 루프 + tkinter 팝업 (PC가 켜져 있을 때만 동작)
#
# - 30초마다 due 알림 확인 → 화면 우하단에 팝업(-topmost) 표시
# - [완료] : state.json done=true 기록 후 git pull/commit/push 로 클라우드와 동기화
# - [나중에]: 닫기만 (같은 stage는 재표시 안 함, 다음 stage/일정에 다시 뜸)
# - 클라우드(텔레그램) 변경분을 받기 위해 주기적으로 git pull
#
# 실행: pythonw run_local.py   (창 없이 백그라운드)
# 시작프로그램/작업 스케줄러 등록은 README 참고.

from __future__ import annotations

import os
import time
import logging
import threading
import subprocess
import tkinter as tk
from datetime import datetime
from pathlib import Path

import schedule_rules as sr
import state_store as ss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "local.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("run_local")

REPO_DIR = Path(__file__).parent
LOOP_SEC = 30
PULL_EVERY_SEC = 300          # 5분마다 git pull
WINDOW_MIN = 2                # 로컬은 상주라 좁은 윈도우
GIT_SYNC = os.environ.get("LOCAL_GIT_SYNC", "1") != "0"

_state_lock = threading.Lock()

# ── 팝업 스타일 (그랑죠알리미/monitor.py 패턴 재사용) ─────────────────────────
POPUP_W, POPUP_H, POPUP_GAP, TASKBAR_H = 380, 190, 8, 64
BG, ACCENT = "#16213e", "#0f3460"
BTN_DONE_BG, BTN_LATER_BG = "#2ecc71", "#444444"
WHITE, GRAY = "#ffffff", "#bbbbbb"

_used_slots: set[int] = set()
_slots_lock = threading.Lock()


def _acquire_slot() -> int:
    with _slots_lock:
        slot = 0
        while slot in _used_slots:
            slot += 1
        _used_slots.add(slot)
        return slot


def _release_slot(slot: int) -> None:
    with _slots_lock:
        _used_slots.discard(slot)


def _slot_pos(slot: int, sw: int, sh: int) -> tuple[int, int]:
    x = sw - POPUP_W - 16
    y = sh - TASKBAR_H - (POPUP_H + POPUP_GAP) * (slot + 1)
    return x, max(y, 10)


# ── git 동기화 ────────────────────────────────────────────────────────────────

def _git(*args: str) -> bool:
    try:
        subprocess.run(["git", *args], cwd=REPO_DIR, check=True,
                       capture_output=True, timeout=60)
        return True
    except Exception as e:
        log.warning(f"git {' '.join(args)} 실패: {e}")
        return False


def git_pull() -> None:
    if GIT_SYNC:
        _git("pull", "--rebase", "--autostash")


def git_push_state() -> None:
    if not GIT_SYNC:
        return
    _git("pull", "--rebase", "--autostash")
    _git("add", "state.json")
    # 변경 없으면 commit 실패해도 무시
    subprocess.run(["git", "commit", "-m", "state: local 완료 동기화"],
                   cwd=REPO_DIR, capture_output=True)
    _git("push")


# ── 완료/표시 처리 (reload-modify-save) ──────────────────────────────────────

def _mark_done(occ_id: str) -> None:
    with _state_lock:
        st = ss.load()
        newly = ss.mark_done(st, occ_id, by="local")
        ss.save(st)
    if newly:
        log.info(f"완료(로컬): {occ_id}")
        threading.Thread(target=git_push_state, daemon=True).start()


def _mark_shown(occ_id: str, stage: str) -> None:
    with _state_lock:
        st = ss.load()
        ss.mark_sent(st, occ_id, stage)
        ss.save(st)


# ── 팝업 ─────────────────────────────────────────────────────────────────────

def show_popup(r: sr.Reminder) -> None:
    slot = _acquire_slot()

    def _run():
        root = tk.Tk()
        root.title(r.label)
        root.configure(bg=BG)
        root.attributes("-topmost", True)
        root.resizable(False, False)

        def close():
            _release_slot(slot)
            try:
                root.destroy()
            except Exception:
                pass

        def on_done():
            _mark_done(r.occ_id)
            close()

        root.protocol("WM_DELETE_WINDOW", close)

        hdr = tk.Frame(root, bg=ACCENT, height=30)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"  {r.emoji}  {r.label}", font=("맑은 고딕", 10, "bold"),
                 fg=WHITE, bg=ACCENT).pack(side="left", padx=4)

        body = r.message.replace("<b>", "").replace("</b>", "")
        tk.Label(root, text=body, font=("맑은 고딕", 11), fg=WHITE, bg=BG,
                 wraplength=POPUP_W - 30, justify="left").pack(
                     fill="both", expand=True, padx=16, pady=12)

        btns = tk.Frame(root, bg=BG)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(btns, text="✅ 완료", command=on_done, font=("맑은 고딕", 10, "bold"),
                  bg=BTN_DONE_BG, fg=WHITE, relief="flat", height=2).pack(
                      side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(btns, text="나중에", command=close, font=("맑은 고딕", 10),
                  bg=BTN_LATER_BG, fg=WHITE, relief="flat", height=2).pack(
                      side="left", expand=True, fill="x", padx=(4, 0))

        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = _slot_pos(slot, sw, sh)
        root.geometry(f"{POPUP_W}x{POPUP_H}+{x}+{y}")
        root.mainloop()

    threading.Thread(target=_run, daemon=True).start()


# ── 메인 루프 ────────────────────────────────────────────────────────────────

def _resolve_now() -> datetime:
    forced = os.environ.get("FORCE_NOW", "").strip()
    if forced:
        dt = datetime.fromisoformat(forced)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=sr.KST)
        return dt.astimezone(sr.KST)
    return sr.now_kst()


def main() -> None:
    log.info("스케쥴 알리미(로컬) 시작")
    last_pull = 0.0
    while True:
        try:
            if time.time() - last_pull > PULL_EVERY_SEC:
                git_pull()
                last_pull = time.time()

            now = _resolve_now()
            state = ss.load()
            due = sr.due_reminders(
                now, WINDOW_MIN,
                is_suppressed=lambda occ, stage: ss.is_suppressed(state, occ, stage),
                include_now_stage=True,   # 로컬은 자정 정각 핑도 표시
            )
            for r in due:
                _mark_shown(r.occ_id, r.stage)
                show_popup(r)
                log.info(f"팝업: {r.occ_id} [{r.stage}]")
        except Exception as e:
            log.error(f"루프 오류: {e}")
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    main()
