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
import notifier_telegram as tg
import oneoff_store as oneoff
import inbox

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
INBOX_LONGPOLL_SEC = 25       # 텔레그램 롱폴링 대기시간(서버가 새 메시지 오면 즉시 응답)
PRUNE_EVERY_SEC = 600         # 10분마다 지나간 단발성 일정 자동 삭제
GIT_SYNC = os.environ.get("LOCAL_GIT_SYNC", "1") != "0"


def _telegram_ready() -> bool:
    return bool(os.environ.get("TELEGRAM_TOKEN")) and bool(os.environ.get("TELEGRAM_CHAT_ID"))

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
    _git("add", "state.json", "oneoff.json")
    _run_git(["commit", "-m", "state: local 동기화(완료/명령/자동삭제)"])   # 변경 없으면 실패해도 무시
    _git("push")


def _mark_done_state(occ_id: str) -> None:
    with _lock:
        st = ss.load()
        newly = ss.mark_done(st, occ_id, by="local")
        ss.save(st)
    if newly:
        log.info(f"완료(로컬): {occ_id}")
        threading.Thread(target=git_push_state, daemon=True).start()


def _send_telegram_and_record(r: sr.Reminder) -> None:
    """PC가 켜져 있을 때는 클라우드(하루 4회)를 기다리지 않고 즉시 텔레그램도 발송.
    클라우드가 늦게 깨어나기 전에 로컬에서 '완료'를 눌러버리면 텔레그램이 영영 안 가는
    레이스를 막기 위함(stages_sent를 바로 기록해 클라우드 쪽 중복발송도 방지)."""
    if not _telegram_ready():
        return
    try:
        ok = tg.send_reminder(r.message, r.occ_id)
    except Exception as e:
        log.warning(f"텔레그램 발송 실패: {e}")
        return
    if ok:
        with _lock:
            st = ss.load()
            ss.mark_sent(st, r.occ_id, r.stage)
            ss.save(st)
        log.info(f"텔레그램 발송(로컬): {r.occ_id} [{r.stage}]")
        threading.Thread(target=git_push_state, daemon=True).start()


def _inbox_long_poll_loop() -> None:
    """텔레그램 getUpdates를 롱폴링으로 상시 대기 — 메시지 오면 1~2초 내 반응.
    네트워크 대기(최대 INBOX_LONGPOLL_SEC초)는 _lock 밖에서 수행해, 그 사이에도
    메인 루프(알림 due 체크·팝업·완료버튼)가 멈추지 않게 한다.
    전체를 try/except로 감싸 — 어디서든 예외가 나도 스레드가 조용히 죽지 않고
    로그를 남긴 뒤 계속 돈다(daemon 스레드라 죽으면 pythonw에선 흔적 없이 사라짐)."""
    log.info(f"텔레그램 롱폴링 시작(최대 {INBOX_LONGPOLL_SEC}초 대기)")
    while True:
        try:
            if not _telegram_ready():
                time.sleep(5)
                continue

            with _lock:
                offset = ss.load().get("tg_last_update_id", 0)
            t0 = time.time()
            done_ids, commands, texts, new_offset = inbox.fetch(offset, timeout=INBOX_LONGPOLL_SEC)
            elapsed = time.time() - t0

            if not done_ids and not commands and not texts and new_offset == offset:
                # 타임아웃(정상, ~INBOX_LONGPOLL_SEC초 걸림)이면 바로 재요청.
                # 너무 빨리(예: 409 충돌 등) 빈손으로 돌아왔으면 짧게 쉬어 폭주 방지.
                if elapsed < 3:
                    time.sleep(2)
                continue

            with _lock:
                st = ss.load()
                st["tg_last_update_id"] = new_offset
                done_n, handled_n = inbox.apply(st, done_ids, commands, texts, done_by="telegram")
                ss.save(st)
            if done_n or handled_n:
                log.info(f"인박스(즉시): 완료 {done_n}건 / 명령 {handled_n}건")
                threading.Thread(target=git_push_state, daemon=True).start()
        except Exception:
            log.exception("인박스 롱폴링 루프 오류 — 5초 후 재시도")
            time.sleep(5)


# ── 팝업 ─────────────────────────────────────────────────────────────────────

def show_popup(key: str, entry: dict) -> None:
    slot = _acquire_slot()

    def _run():
        if slot > 0:
            time.sleep(0.5 * slot)  # 동시 tk.Tk() 초기화 충돌 방지 — 두 번째 팝업부터 지연
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
    log.info("스케쥴 알리미(로컬) 시작 — 완료 누를 때까지 스누즈로 반복 알림 + 텔레그램 동시 발송")
    threading.Thread(target=_inbox_long_poll_loop, daemon=True).start()
    last_pull = 0.0
    last_prune = 0.0
    while True:
        try:
            if time.time() - last_pull > PULL_EVERY_SEC:
                git_pull()
                last_pull = time.time()

            if time.time() - last_prune > PRUNE_EVERY_SEC:
                with _lock:
                    removed = oneoff.prune()
                if removed:
                    log.info(f"단발성 일정 자동삭제: {removed}건")
                    threading.Thread(target=git_push_state, daemon=True).start()
                last_prune = time.time()

            now = _resolve_now()
            state = ss.load()
            to_show = []
            newly_due: list[sr.Reminder] = []
            with _lock:
                active = load_active()

                # 1) 새로 도래한 due 알림 → active 등록 (즉시 표시 대상) + 텔레그램 발송 대상으로 적립
                def suppressed(occ, stage):
                    return ss.is_suppressed(state, occ, stage) or f"{occ}|{stage}" in active

                for r in sr.due_reminders(now, suppressed, include_now_stage=True):
                    active[f"{r.occ_id}|{r.stage}"] = {
                        "occ_id": r.occ_id, "stage": r.stage, "label": r.label,
                        "emoji": r.emoji, "message": r.message,
                        "snooze_until": now.isoformat(), "showing": False,
                    }
                    newly_due.append(r)

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

            # 잠금 밖에서 처리(네트워크 호출 포함) — 팝업과 텔레그램을 거의 동시에 내보냄
            for r in newly_due:
                _send_telegram_and_record(r)

            for k, e in to_show:
                show_popup(k, e)
                log.info(f"팝업: {k}")
        except Exception as e:
            log.error(f"루프 오류: {e}")
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    main()
