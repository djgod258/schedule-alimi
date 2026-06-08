# PC 진입점 — 상주 루프 + tkinter 팝업 (PC가 켜져 있을 때만 동작)
#
# - 15초마다 due 알림 확인 → 화면 우하단에 팝업(-topmost) 표시
# - [✅완료] : state.json done=true → 영구 종료 + git 동기화(텔레그램에도 반영)
# - [다시 알림] : 드롭다운에서 고른 시간 뒤 다시 팝업(스누즈). 완료 전까지 반복.
# - 창 X로 닫아도 = 드롭다운 시간만큼 스누즈(완료 전엔 사라지지 않음 → 깜빡 방지)
# - 스누즈 상태는 로컬 전용(local_active.json, git 미커밋). state.json은 클라우드와 공유.
#
# 실행: pythonw run_local.py   (창 없이 백그라운드)

from __future__ import annotations

import os
import json
import time
import logging
import threading
import subprocess
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta
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
ACTIVE_FILE = REPO_DIR / "local_active.json"   # 로컬 전용 활성 알림(스누즈) 상태
LOOP_SEC = 15
PULL_EVERY_SEC = 300          # 5분마다 git pull (클라우드 완료 반영)
GIT_SYNC = os.environ.get("LOCAL_GIT_SYNC", "1") != "0"

# 드롭다운 스누즈 선택지 (표시 → 분)
SNOOZE_OPTIONS = [("10분 뒤", 10), ("30분 뒤", 30), ("1시간 뒤", 60),
                  ("2시간 뒤", 120), ("3시간 뒤", 180)]
SNOOZE_MAP = dict(SNOOZE_OPTIONS)
DEFAULT_SNOOZE_LABEL = "30분 뒤"

_lock = threading.Lock()

# ── 팝업 스타일 (그랑죠알리미/monitor.py 패턴 재사용) ─────────────────────────
POPUP_W, POPUP_H, POPUP_GAP, TASKBAR_H = 390, 230, 8, 64
BG, ACCENT = "#16213e", "#0f3460"
BTN_DONE_BG, BTN_SNOOZE_BG = "#2ecc71", "#e9a23b"
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


# ── 로컬 활성상태(스누즈) ─────────────────────────────────────────────────────

def load_active() -> dict:
    if ACTIVE_FILE.exists():
        try:
            return json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_active(a: dict) -> None:
    ACTIVE_FILE.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")


# ── git 동기화 ────────────────────────────────────────────────────────────────
# pythonw로 띄워도 subprocess로 git.exe를 부르면 콘솔 창이 깜빡 뜬다 → CREATE_NO_WINDOW로 숨김.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_git(args: list[str], check: bool = False):
    return subprocess.run(["git", *args], cwd=REPO_DIR, check=check,
                          capture_output=True, timeout=60, creationflags=_NO_WINDOW)


def _git(*args: str) -> bool:
    try:
        _run_git(list(args), check=True)
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
    _run_git(["commit", "-m", "state: local 완료 동기화"])   # 변경 없으면 실패해도 무시
    _git("push")


def _mark_done_state(occ_id: str) -> None:
    with _lock:
        st = ss.load()
        newly = ss.mark_done(st, occ_id, by="local")
        ss.save(st)
    if newly:
        log.info(f"완료(로컬): {occ_id}")
        threading.Thread(target=git_push_state, daemon=True).start()


# ── 팝업 ─────────────────────────────────────────────────────────────────────

def show_popup(key: str, entry: dict) -> None:
    slot = _acquire_slot()

    def _run():
        root = tk.Tk()
        root.title(entry["label"])
        root.configure(bg=BG)
        root.attributes("-topmost", True)
        root.resizable(False, False)

        snooze_var = tk.StringVar(value=DEFAULT_SNOOZE_LABEL)

        def finish(result: str):
            _release_slot(slot)
            mins = SNOOZE_MAP.get(snooze_var.get(), 30)
            with _lock:
                a = load_active()
                if key in a:
                    if result == "done":
                        del a[key]
                    else:  # snooze (버튼 또는 X)
                        a[key]["snooze_until"] = (
                            sr.now_kst() + timedelta(minutes=mins)).isoformat()
                        a[key]["showing"] = False
                save_active(a)
            if result == "done":
                _mark_done_state(entry["occ_id"])
            else:
                log.info(f"스누즈 {mins}분: {key}")
            try:
                root.destroy()
            except Exception:
                pass

        root.protocol("WM_DELETE_WINDOW", lambda: finish("snooze"))

        # 헤더
        hdr = tk.Frame(root, bg=ACCENT, height=30)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"  {entry['emoji']}  {entry['label']}",
                 font=("맑은 고딕", 10, "bold"), fg=WHITE, bg=ACCENT).pack(side="left", padx=4)

        # 본문
        body = entry["message"].replace("<b>", "").replace("</b>", "")
        tk.Label(root, text=body, font=("맑은 고딕", 11), fg=WHITE, bg=BG,
                 wraplength=POPUP_W - 30, justify="left").pack(
                     fill="both", expand=True, padx=16, pady=(10, 6))

        # 스누즈 드롭다운 줄
        snrow = tk.Frame(root, bg=BG)
        snrow.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(snrow, text="다시 알림:", font=("맑은 고딕", 9), fg=GRAY, bg=BG).pack(side="left")
        combo = ttk.Combobox(snrow, textvariable=snooze_var, state="readonly",
                             width=8, values=[lbl for lbl, _ in SNOOZE_OPTIONS])
        combo.pack(side="left", padx=6)

        # 버튼 줄
        btns = tk.Frame(root, bg=BG)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(btns, text="✅ 완료", command=lambda: finish("done"),
                  font=("맑은 고딕", 10, "bold"), bg=BTN_DONE_BG, fg=WHITE,
                  relief="flat", height=2).pack(side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(btns, text="⏰ 다시 알림", command=lambda: finish("snooze"),
                  font=("맑은 고딕", 10), bg=BTN_SNOOZE_BG, fg=WHITE,
                  relief="flat", height=2).pack(side="left", expand=True, fill="x", padx=(4, 0))

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
    log.info("스케쥴 알리미(로컬) 시작 — 완료 누를 때까지 스누즈로 반복 알림")
    last_pull = 0.0
    while True:
        try:
            if time.time() - last_pull > PULL_EVERY_SEC:
                git_pull()
                last_pull = time.time()

            now = _resolve_now()
            state = ss.load()
            to_show = []
            with _lock:
                active = load_active()

                # 1) 새로 도래한 due 알림 → active 등록 (즉시 표시 대상)
                def suppressed(occ, stage):
                    return ss.is_suppressed(state, occ, stage) or f"{occ}|{stage}" in active

                for r in sr.due_reminders(now, suppressed, include_now_stage=True):
                    active[f"{r.occ_id}|{r.stage}"] = {
                        "occ_id": r.occ_id, "stage": r.stage, "label": r.label,
                        "emoji": r.emoji, "message": r.message,
                        "snooze_until": now.isoformat(), "showing": False,
                    }

                # 2) 클라우드/타지점에서 완료된 항목 제거
                for k in list(active):
                    if ss.is_done(state, active[k]["occ_id"]):
                        del active[k]

                # 3) 표시 시각 도래 + 현재 미표시 → 표시
                for k, e in active.items():
                    if e.get("showing"):
                        continue
                    if datetime.fromisoformat(e["snooze_until"]) <= now:
                        e["showing"] = True
                        to_show.append((k, dict(e)))

                save_active(active)

            for k, e in to_show:
                show_popup(k, e)
                log.info(f"팝업: {k}")
        except Exception as e:
            log.error(f"루프 오류: {e}")
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    main()
