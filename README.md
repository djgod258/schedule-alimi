# 루틴 스케쥴 알리미

매월 반복 일정을 **텔레그램**(항상) + **PC 팝업**(켜져 있을 때만)으로 알리고,
처리하면 **완료** 버튼으로 닫아 더 이상 울리지 않게 한다.

## 일정 규칙
| 이벤트 | 목표일 | 알림 |
|---|---|---|
| 코마케팅 | 매월 3번째 영업일(주말+공휴일 제외) | 당일 08:30 |
| 추가금액 & 구간수수료 | 9일을 직전 영업일로 보정 후 -2영업일 | 당일 08:30 |
| 용인자연휴양림 | 매월 5일 고정 | 당일 08:30 |
| 화성 지역화폐 | 1일 00:00(선착순) | 전날 21시·23시 (+PC면 자정 정각) |
| 수원 지역화폐 | 1일 09:00(선착순) | 전날 21시 + 당일 08:30 |
| 9일 송금 | 매월 9일(주말·공휴일이면 직전 영업일) | 당일 08:30 |
| 월말 송금 | 마지막 영업일 + 다음 영업일(이틀) | 각 당일 08:30 |

> 공휴일은 `holidays`(South Korea) 자동 계산. 검증: 2026-05 → 코마케팅·추가금액 모두 5/6.

## 구조
- `events.py` — 영업일/공휴일 헬퍼 + 이벤트 정의
- `schedule_rules.py` — stage별 발송시각 전개 + due 계산
- `state_store.py` — `state.json` 발송/완료 상태
- `notifier_telegram.py` — 텔레그램 발송(완료 버튼) + getUpdates 완료 수신
- `run_cloud.py` — GitHub Actions 진입점
- `run_local.py` — PC 상주(팝업) 진입점
- `.github/workflows/schedule.yml` — 하루 3회 cron(08:30·21:05·23:05 KST)

## 설치
```
pip install -r requirements.txt
```

## GitHub 설정
1. 이 폴더를 새 GitHub 저장소로 push.
2. 저장소 → Settings → Secrets and variables → Actions 에 등록:
   - `TELEGRAM_TOKEN` — 봇 토큰
   - `TELEGRAM_CHAT_ID` — 알림 받을 chat id
3. Actions 탭에서 **스케쥴 알리미 → Run workflow**로 수동 테스트.
   `force_now`에 `2026-05-31T21:00` 같이 넣으면 그 시각 기준으로 동작 확인 가능.

> 텔레그램 봇/CHAT_ID는 기존 그랑죠·주식모니터 봇을 재사용해도 되고,
> 알림을 분리하고 싶으면 새 봇(@BotFather)·새 그룹을 만든다.

## 로컬 PC 실행
```
pythonw run_local.py        # 창 없이 백그라운드
```
- 시작 시 자동 실행: 시작프로그램 폴더(`Win+R` → `shell:startup`)에
  `pythonw "...\스케쥴알리미\run_local.py"` 바로가기를 넣는다.
- PC가 꺼져 있으면 팝업은 생략되고 텔레그램만 온다(정상).
- `state.json`을 git으로 동기화하므로 PC의 이 폴더는 GitHub 저장소 클론이어야 한다.
  git push 동기화를 끄려면 환경변수 `LOCAL_GIT_SYNC=0`.

## 완료 처리
- 텔레그램: 메시지의 **✅ 완료** 버튼 탭 (또는 `/done <occ_id>` 전송)
- PC 팝업: **✅ 완료** 버튼 클릭
- 어느 쪽이든 누르면 그 달 해당 일정은 더 이상 알리지 않는다.

## 테스트
```
python events.py            # 목표일 계산 검증
python schedule_rules.py    # stage 전개 확인
FORCE_NOW=2026-05-31T21:00 python run_cloud.py   # 발송 시뮬레이션
```
