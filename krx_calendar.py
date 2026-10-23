"""KRX 휴장일. P1(아메리카노) 수요는 휴장일에 0."""
import datetime as dt

# 2026 하반기 KRX 휴장일 (주말 제외). 대체공휴일: 개천절(10/3 토) → 10/5(월).
KRX_HOLIDAYS = {
    dt.date(2026, 8, 17),   # 광복절 대체공휴일 (8/15 토)
    dt.date(2026, 9, 24), dt.date(2026, 9, 25),  # 추석 (9/26 토)
    dt.date(2026, 10, 5),   # 개천절 대체공휴일
    dt.date(2026, 10, 9),   # 한글날
    dt.date(2026, 12, 25),  # 성탄절
    dt.date(2026, 12, 31),  # 연말 휴장
}


def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in KRX_HOLIDAYS
