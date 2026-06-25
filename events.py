# 이벤트 정의 + 영업일/공휴일 헬퍼
#
# 모든 날짜 계산은 KST(Asia/Seoul) 기준 date 객체로 처리한다.
# 공휴일은 holidays 라이브러리(South Korea)로 계산 — 어린이날·설/추석(음력)·대체공휴일 포함.

from __future__ import annotations

import calendar
from datetime import date, timedelta

try:
    import holidays as _holidays_mod
    _KR_HOLIDAYS = _holidays_mod.SouthKorea()
except Exception:  # holidays 미설치 시에도 주말 기준으로는 동작
    _KR_HOLIDAYS = None


# ── 영업일 헬퍼 ───────────────────────────────────────────────────────────────

def is_holiday(d: date) -> bool:
    """한국 공휴일이면 True (라이브러리 없으면 항상 False)."""
    if _KR_HOLIDAYS is None:
        return False
    return d in _KR_HOLIDAYS


def is_business_day(d: date) -> bool:
    """주말이 아니고 공휴일도 아니면 영업일."""
    return d.weekday() < 5 and not is_holiday(d)


def prev_business_day(d: date) -> date:
    """d가 영업일이면 그대로, 아니면 가장 가까운 직전 영업일."""
    cur = d
    while not is_business_day(cur):
        cur -= timedelta(days=1)
    return cur


def add_business_days(d: date, n: int) -> date:
    """d로부터 영업일 n일 이동 (n<0 가능). d 자체는 영업일이라고 가정하지 않는다."""
    if n == 0:
        return prev_business_day(d)
    step = 1 if n > 0 else -1
    remaining = abs(n)
    cur = d
    while remaining > 0:
        cur += timedelta(days=step)
        if is_business_day(cur):
            remaining -= 1
    return cur


def nth_business_day(year: int, month: int, n: int) -> date:
    """해당 월의 n번째 영업일."""
    count = 0
    last = calendar.monthrange(year, month)[1]
    for day in range(1, last + 1):
        d = date(year, month, day)
        if is_business_day(d):
            count += 1
            if count == n:
                return d
    raise ValueError(f"{year}-{month}에 {n}번째 영업일이 없음")


def last_day_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


# ── 목표일 계산 ───────────────────────────────────────────────────────────────

def komarketing_target(year: int, month: int) -> date:
    """코마케팅: 매월 3번째 영업일."""
    return nth_business_day(year, month, 3)


def surcharge_target(year: int, month: int) -> date:
    """추가금액 & 구간수수료: 9일을 직전 영업일로 보정 후 -2영업일."""
    base = prev_business_day(date(year, month, 9))
    return add_business_days(base, -2)


def yongin_target(year: int, month: int) -> date:
    """용인자연휴양림: 매월 5일 고정 (주말·공휴일 무관)."""
    return date(year, month, 5)


def localpay_charge(year: int, month: int) -> date:
    """지역화폐 충전일: 매월 1일 고정."""
    return date(year, month, 1)


def remit_day9_target(year: int, month: int) -> date:
    """9일 송금: 매월 9일, 주말/공휴일이면 직전 영업일."""
    return prev_business_day(date(year, month, 9))


def monthend_remit_days(year: int, month: int) -> tuple[date, date]:
    """월말 송금: (그 달 마지막 영업일, 그 다음 영업일=다음달 첫 영업일) 이틀."""
    last_biz = prev_business_day(last_day_of_month(year, month))
    next_biz = add_business_days(last_biz, 1)
    return last_biz, next_biz


# ── 이벤트 메타 (메시지/이모지) ──────────────────────────────────────────────
# 실제 알림 시각(stage)별 전개는 schedule_rules.py에서 처리한다.

EVENTS = {
    "komarketing": {
        "label": "코마케팅",
        "emoji": "📊",
        "kind": "morning",          # 목표일 당일 아침 1회
        "target": komarketing_target,
    },
    "surcharge": {
        "label": "추가금액 & 구간수수료",
        "emoji": "💸",
        "kind": "morning",
        "target": surcharge_target,
    },
    "yongin": {
        "label": "용인자연휴양림",
        "emoji": "🌲",
        "kind": "morning",
        "target": yongin_target,
    },
    "localpay_hwaseong": {
        "label": "화성 지역화폐 충전",
        "emoji": "💳",
        "kind": "firstcome",        # 선착순: 전날 저녁 + 직전 스탠바이
        "charge": localpay_charge,
        "charge_hhmm": (15, 0),     # 1일 15:00 (2026-06 변경: 기존 00:00 자정 → 15시로 조정)
        "city": "화성",
        "note": "⚠️ 15시 이전 충전 시 인센티브 미지급! 15시 이후에 충전하세요.",
    },
    "localpay_suwon": {
        "label": "수원 지역화폐 충전",
        "emoji": "💳",
        "kind": "firstcome",
        "charge": localpay_charge,
        "charge_hhmm": (9, 0),      # 1일 09:00
        "city": "수원",
    },
    "remit_day9": {
        "label": "9일 송금",
        "emoji": "💰",
        "kind": "morning",          # 매월 9일(평일보정) 당일 아침 1회
        "target": remit_day9_target,
    },
    "remit_monthend": {
        "label": "월말 송금",
        "emoji": "💰",
        "kind": "remit2",           # 마지막 영업일 + 다음 영업일, 이틀 각각 아침 알림
        "days": monthend_remit_days,
    },
}


# ── 셀프테스트 ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for y, m in [(2026, 5), (2026, 6), (2026, 7)]:
        print(f"== {y}-{m:02d} ==")
        print(f"  코마케팅(3번째 영업일) : {komarketing_target(y, m)}")
        print(f"  추가금액(-2영업일)     : {surcharge_target(y, m)}")
        print(f"  용인(5일 고정)         : {yongin_target(y, m)}")
        print(f"  지역화폐 충전(1일)     : {localpay_charge(y, m)}")
    # 기대: 2026-05 → 코마케팅/추가금액 모두 2026-05-06
