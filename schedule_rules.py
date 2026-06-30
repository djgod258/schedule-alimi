# 핵심 로직: KST 기준 '지금 보내야 할 알림(reminder)' 목록 계산
#
# 각 이벤트를 stage별 발송시각(KST datetime)으로 전개한 뒤,
# now ± window 안에 들고 아직 미발송/미완료인 것만 골라낸다.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import events as ev
import oneoff_store as oneoff

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


@dataclass
class Reminder:
    occ_id: str        # "<event_key>:<목표일 YYYY-MM-DD>"
    event_key: str
    label: str
    emoji: str
    stage: str         # morning / eve / pre / now
    fire_at: datetime  # KST tz-aware
    target_date: date
    message: str
    catchup_min: int = 720   # fire_at 이후 이 시간(분)까지 '아직 보낼 수 있음'(지연 흡수)


def _dt(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=KST)


def _morning_message(meta: dict, target: date) -> str:
    return (
        f"{meta['emoji']} <b>{meta['label']}</b>\n"
        f"오늘({target:%m월 %d일}) 처리할 일정입니다.\n"
        f"완료하면 아래 <b>완료</b> 버튼을 눌러주세요."
    )


def _firstcome_message(meta: dict, charge: date, stage: str) -> str:
    hh, mm = meta["charge_hhmm"]
    when = f"{charge:%m월 %d일} {hh:02d}:{mm:02d}"
    head = f"{meta['emoji']} <b>{meta['label']}</b> (선착순)"
    if stage == "eve":
        body = f"내일 {when} 충전 오픈! 오늘 미리 스탠바이 하세요."
    elif stage == "pre":
        body = f"{when} 충전 임박 — 곧 오픈, 대기하세요."
    else:  # now
        body = f"지금! {when} 충전 오픈 — 바로 충전하세요."
    note = meta.get("note")
    tail = f"\n{note}" if note else ""
    return f"{head}\n{body}{tail}\n완료하면 <b>완료</b> 버튼을 눌러주세요."


def _expand_event(event_key: str, year: int, month: int) -> list[Reminder]:
    """해당 (year, month)를 '목표월/충전월'로 갖는 이벤트의 모든 stage를 전개."""
    meta = ev.EVENTS[event_key]
    out: list[Reminder] = []

    if meta["kind"] == "morning":
        target = meta["target"](year, month)
        occ_id = f"{event_key}:{target.isoformat()}"
        out.append(Reminder(
            occ_id, event_key, meta["label"], meta["emoji"], "morning",
            _dt(target, 8, 30), target, _morning_message(meta, target),
            catchup_min=14 * 60,   # 당일 안에는 따라잡아 발송(08:30~22:30)
        ))

    elif meta["kind"] == "remit2":
        # 월말 송금: 이틀(마지막 영업일 + 다음 영업일) 각각 아침 알림
        d1, d2 = meta["days"](year, month)
        for idx, target in enumerate((d1, d2), start=1):
            occ_id = f"{event_key}:{target.isoformat()}"
            msg = (
                f"{meta['emoji']} <b>{meta['label']}</b> (이틀 중 {idx}일차)\n"
                f"오늘({target:%m월 %d일}) 송금일입니다.\n"
                f"완료하면 아래 <b>완료</b> 버튼을 눌러주세요."
            )
            out.append(Reminder(
                occ_id, event_key, meta["label"], meta["emoji"], "morning",
                _dt(target, 8, 30), target, msg, catchup_min=14 * 60,
            ))

    elif meta["kind"] == "firstcome":
        charge = meta["charge"](year, month)          # 1일
        hh, mm = meta["charge_hhmm"]
        occ_id = f"{event_key}:{charge.isoformat()}"
        py, pm = ev.prev_month(year, month)
        eve_day = ev.last_day_of_month(py, pm)         # 전날 = 전월 말일

        charge_dt = _dt(charge, hh, mm)
        eve_fire = _dt(eve_day, 21, 0)
        # eve catch-up: 다음 stage(pre)가 뜨기 전까지 유효
        eve_catch = max(120, int((charge_dt - eve_fire).total_seconds() // 60) - 10)

        # 두 도시 동일 패턴: 전날 저녁 21시 → 오픈 10분 전(스탠바이) → 오픈 정각
        # 수원 09:00 → 08:50 / 화성 15:00 → 14:50
        stages: list[tuple[str, datetime, int]] = [
            ("eve", eve_fire, eve_catch),
            ("pre", charge_dt - timedelta(minutes=10), 90),
            ("now", charge_dt, 120),
        ]

        for stage, fire_at, catch in stages:
            out.append(Reminder(
                occ_id, event_key, meta["label"], meta["emoji"], stage,
                fire_at, charge, _firstcome_message(meta, charge, stage),
                catchup_min=catch,
            ))

    return out


def _expand_oneoff() -> list[Reminder]:
    """단발성 일정(oneoff.json) → Reminder. 지정 시각에 1회(stage='once')."""
    out: list[Reminder] = []
    for it in oneoff.load_items():
        try:
            dt = datetime.fromisoformat(it["datetime"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
        except Exception:
            continue
        occ_id = f"oneoff:{it['id']}"
        msg = (
            f"📌 <b>{it.get('title', '일정')}</b>\n"
            f"{dt:%m월 %d일 %H:%M} 일정입니다.\n"
            f"완료하면 아래 <b>완료</b> 버튼을 눌러주세요."
        )
        out.append(Reminder(
            occ_id, "oneoff", it.get("title", "일정"), "📌", "once",
            dt, dt.date(), msg, catchup_min=14 * 60,
        ))
    return out


def all_reminders_around(ref: date) -> list[Reminder]:
    """ref가 속한 달의 전·당·다음 달 이벤트 + 단발성 일정을 모두 전개."""
    months = set()
    for delta in (-1, 0, 1):
        y, m = ref.year, ref.month + delta
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        months.add((y, m))

    out: list[Reminder] = []
    for (y, m) in months:
        for key in ev.EVENTS:
            out.extend(_expand_event(key, y, m))
    out.extend(_expand_oneoff())
    return out


def due_reminders(
    now: datetime,
    is_suppressed,
    include_now_stage: bool = True,
    grace_min: int = 0,
) -> list[Reminder]:
    """발송시각이 지났고(따라잡기 창 이내) 아직 발송/완료되지 않은 reminder 목록.

    핵심: fire_at - grace <= now <= fire_at + catchup_min.
    → GitHub Actions가 몇 시간 늦게 실행돼도, 시각이 지난 알림을 '그날 안에' 따라잡아
      한 번 발송한다(중복은 is_suppressed로 방지). 이로써 깨움 지연/누락에 견고해진다.
      grace_min은 기본 0 — '늦게' 확인해도 catchup_min이 이미 커버하므로,
      '일찍'(예정 시각 전) 울릴 이유가 없다. 0보다 크면 그만큼 더 일찍 울린다.

    is_suppressed(occ_id, stage) -> bool : 이미 발송했거나 완료(done)면 True.
    include_now_stage : 클라우드는 'now'(자정 정각) stage를 안 보내려면 False.
    """
    result = []
    seen = set()
    for r in all_reminders_around(now.date()):
        if r.stage == "now" and not include_now_stage:
            continue
        lo = r.fire_at - timedelta(minutes=grace_min)
        hi = r.fire_at + timedelta(minutes=r.catchup_min)
        if not (lo <= now <= hi):
            continue
        if is_suppressed(r.occ_id, r.stage):
            continue
        dedup = (r.occ_id, r.stage)
        if dedup in seen:
            continue
        seen.add(dedup)
        result.append(r)
    return result


# ── 고정 일정 목록 (텔레그램 /fixed) ──────────────────────────────────────────

_WD_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _ko_date(dt: datetime) -> str:
    return f"{dt:%m/%d}({_WD_KO[dt.weekday()]})"


def _event_target_times(event_key: str, year: int, month: int) -> list[tuple[datetime, str, str]]:
    """알림 stage가 아니라 '실제 이벤트 시각'(목표일/충전 시각)을 직접 계산.
    예: 화성 충전은 항상 15:00, 수원은 09:00 — stage 기반으로는 둘 다 전날 21시
    안내로만 보여 실제 시각 차이가 안 드러나는 문제를 피하기 위함."""
    meta = ev.EVENTS[event_key]
    out: list[tuple[datetime, str, str]] = []
    if meta["kind"] == "morning":
        target = meta["target"](year, month)
        out.append((_dt(target, 8, 30), meta["emoji"], meta["label"]))
    elif meta["kind"] == "remit2":
        d1, d2 = meta["days"](year, month)
        out.append((_dt(d1, 8, 30), meta["emoji"], f"{meta['label']} (1일차)"))
        out.append((_dt(d2, 8, 30), meta["emoji"], f"{meta['label']} (2일차)"))
    elif meta["kind"] == "firstcome":
        charge = meta["charge"](year, month)
        hh, mm = meta["charge_hhmm"]
        out.append((_dt(charge, hh, mm), meta["emoji"], f"{meta['label']} 오픈"))
    return out


def upcoming_fixed(now: datetime, days: int = 60) -> list[tuple[datetime, str, str]]:
    """다음 days일 동안의 고정(반복) 일정 — 실제 이벤트 시각 기준. 단발성은 제외.
    반환: (시각, 이모지, 라벨) 목록, 시각순 정렬."""
    end_dt = now + timedelta(days=days)
    months = set()
    d = now.date()
    while d <= end_dt.date():
        months.add((d.year, d.month))
        d += timedelta(days=1)
    for (y, m) in list(months):
        for delta in (-1, 1):
            yy, mm = y, m + delta
            if mm < 1:
                yy, mm = y - 1, 12
            elif mm > 12:
                yy, mm = y + 1, 1
            months.add((yy, mm))

    seen = set()
    out: list[tuple[datetime, str, str]] = []
    for (y, m) in months:
        for key in ev.EVENTS:
            for dt, emoji, label in _event_target_times(key, y, m):
                if not (now <= dt <= end_dt):
                    continue
                sig = (key, dt.isoformat())
                if sig in seen:
                    continue
                seen.add(sig)
                out.append((dt, emoji, label))

    out.sort(key=lambda x: x[0])
    return out


def format_fixed_list(now: datetime, days: int = 60) -> str:
    items = upcoming_fixed(now, days=days)
    if not items:
        return f"📅 앞으로 {days}일 동안 예정된 고정 일정이 없습니다."
    lines = [f"📅 <b>고정 일정</b> (다음 {days}일)"]
    for dt, emoji, label in items:
        lines.append(f"• {_ko_date(dt)} {dt:%H:%M}  {emoji} {label}")
    return "\n".join(lines)


# ── 셀프테스트 ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 2026-06-01 충전 관련 stage 시각 출력
    rs = sorted(all_reminders_around(date(2026, 6, 1)), key=lambda r: r.fire_at)
    for r in rs:
        if r.target_date.month in (5, 6, 7):
            print(f"{r.fire_at:%Y-%m-%d %H:%M}  {r.stage:5s}  {r.occ_id}")
