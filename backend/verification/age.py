"""만 나이 계산.

ADR-0011: 본인확인으로 얻은 생년월일이 만 19세 미만이면 제출과 개최를 모두 막는다.
"""

from __future__ import annotations

from datetime import date

ADULT_AGE = 19


def age_in_years(birth_date: date, *, on: date) -> int:
    age = on.year - birth_date.year
    if (on.month, on.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def is_adult(birth_date: date, *, on: date) -> bool:
    return age_in_years(birth_date, on=on) >= ADULT_AGE
