# 단발성 일정 PC 입력창 (더블클릭/바로가기로 실행)
#
# 날짜·시각·제목을 입력하고 [추가]를 누르면 oneoff.json에 저장 후 git push로 동기화.
# 실행: pythonw add_oneoff.py

from __future__ import annotations

import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
from pathlib import Path

import oneoff_store as oneoff

REPO_DIR = Path(__file__).parent
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BG, ACCENT, WHITE, GRAY = "#16213e", "#0f3460", "#ffffff", "#bbbbbb"
BTN_ADD = "#2ecc71"


def _git_sync():
    try:
        for args in (["pull", "--rebase", "--autostash"], ["add", "oneoff.json"]):
            subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True,
                           timeout=60, creationflags=_NO_WINDOW)
        subprocess.run(["git", "commit", "-m", "oneoff: PC 입력"], cwd=REPO_DIR,
                       capture_output=True, creationflags=_NO_WINDOW)
        subprocess.run(["git", "push"], cwd=REPO_DIR, capture_output=True,
                       timeout=60, creationflags=_NO_WINDOW)
    except Exception:
        pass


def main():
    root = tk.Tk()
    root.title("단발성 일정 추가")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    tk.Label(root, text="📌 단발성 일정 추가", font=("맑은 고딕", 13, "bold"),
             fg=WHITE, bg=ACCENT).pack(fill="x", ipady=8)

    frm = tk.Frame(root, bg=BG)
    frm.pack(padx=20, pady=16)

    tomorrow = datetime.now(oneoff.KST) + timedelta(days=1)

    def row(label, default=""):
        r = tk.Frame(frm, bg=BG)
        r.pack(fill="x", pady=5)
        tk.Label(r, text=label, width=6, anchor="w", font=("맑은 고딕", 10),
                 fg=GRAY, bg=BG).pack(side="left")
        e = tk.Entry(r, font=("맑은 고딕", 11), width=22)
        e.pack(side="left")
        if default:
            e.insert(0, default)
        return e

    e_date = row("날짜", tomorrow.strftime("%Y-%m-%d"))
    e_time = row("시각", "08:30")
    e_title = row("제목")
    e_title.focus_set()

    tk.Label(frm, text="예) 날짜 6/15 · 시각 14:00(비우면 08:30)", font=("맑은 고딕", 8),
             fg=GRAY, bg=BG).pack(pady=(2, 8))

    def submit():
        d = e_date.get().strip()
        t = e_time.get().strip()
        title = e_title.get().strip()
        if not title:
            messagebox.showwarning("입력", "제목을 입력하세요.", parent=root)
            return
        try:
            dt_iso, title2 = oneoff.parse_datetime(f"{d} {t} {title}")
        except ValueError as ex:
            messagebox.showerror("오류", str(ex), parent=root)
            return
        oneoff.add_item(dt_iso, title2)
        _git_sync()
        dt = datetime.fromisoformat(dt_iso)
        messagebox.showinfo("완료", f"등록됨\n{dt:%m/%d(%a) %H:%M}  {title2}", parent=root)
        root.destroy()

    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=20, pady=(0, 16))
    tk.Button(btns, text="추가", command=submit, font=("맑은 고딕", 11, "bold"),
              bg=BTN_ADD, fg=WHITE, relief="flat", height=2).pack(
                  side="left", expand=True, fill="x", padx=(0, 4))
    tk.Button(btns, text="닫기", command=root.destroy, font=("맑은 고딕", 11),
              bg="#444444", fg=WHITE, relief="flat", height=2).pack(
                  side="left", expand=True, fill="x", padx=(4, 0))

    root.bind("<Return>", lambda e: submit())
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = root.winfo_width(), root.winfo_height()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
    root.mainloop()


if __name__ == "__main__":
    main()
