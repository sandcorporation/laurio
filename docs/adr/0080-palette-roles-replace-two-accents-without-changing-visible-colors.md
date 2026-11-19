# 팔레트를 MUI 꼴 역할로 옮긴다 — 보이는 색은 그대로 (ADR-0063 계열 토큰 규칙 개정)

Status: Accepted (2026-11-19 결정)

## 맥락

토큰은 중립 넷(ink·paper·surface·rule)과 「액센트는 정확히 둘」(attention·verified)이었다.
강의실에 「심화」(attention 의 붉은 주황을 쓴다)와 「완벽」 도장이 오고, 오류 표시는 심화와 겹치지
않는 다른 붉은 계열로 갈라야 한다. 한 색이 주의·오류·선택을 겸하는 지금의 이름으로는 그 구분을
적을 자리가 없다. 대표는 MUI 같은 팔레트 역할로 바꾸기로 결정했다(spec #960 5번).

## 결정

1. **역할 일곱**: primary·secondary·info·success·warning·error·advanced(심화 전용). 밝은·어두운 값을
   `light-dark()` 로 함께 둔다. 중립 넷은 이름 그대로다.
2. **이번에는 보이는 색을 바꾸지 않는다.** 옛 값을 새 이름으로 옮기기만 했다.

   | 역할 | 값 (밝음 / 어둠) | 옛 이름 |
   | --- | --- | --- |
   | success | #2e6a4c / #62b489 | verified |
   | error · warning · advanced | #c4442b / #e5694f | attention (셋이 아직 같다) |
   | primary · secondary · info | #17160f / #ece8dc | 잉크 (아직 색상이 없다) |

   error 와 warning 을 가르고 심화가 자기 값을 갖는 일은 후속 티켓(#963·#965)이다. 그때 이 표와
   `classroom/lib/design/tokens.test.ts` 의 얼린 값을 함께 고친다.
3. **범위: 세 앱의 `tokens.css` 가 한 벌이다.** 강의실만 바꾸면 `classroom/lib/design/tokens.test.ts`
   (강의실↔공개 앱)와 `operator/lib/design/tokens.test.ts`(공개 앱↔운영자 앱)의 「한 글자도 다르지
   않다」가 깨진다 — 그 대조를 지우는 것은 브랜드를 가르는 결정이라 하지 않았다. 그래서 파일은 셋을
   같이 바꾸고, **화면 코드는 강의실·공개 앱만** 새 이름으로 옮겼다(`text-attention`→`text-error`,
   `*-verified`→`*-success`). operator 화면 코드는 이번 범위 밖이라 옛 이름을 그대로 쓴다.
4. **옛 이름 `--color-attention`·`--color-verified` 는 별칭으로 남긴다**(`var(--color-error)`·
   `var(--color-success)`). operator 화면과 공유 마크다운 패키지(`packages/markdown`)가 두 앱·운영자
   앱에 함께 쓰이므로 한 번에 옮길 수 없다. 마지막 사용처가 옮겨가면 별칭을 지운다.
5. brand-guard 의 리터럴 색 금지는 그대로다. 허용 이름 목록만 새 역할로 늘었다.
6. `Badge`·`Note` 의 `tone="attention"|"verified"` 같은 컴포넌트 속성 이름은 색 이름이 아니라 의미
   이름이라 이번에 바꾸지 않았다.

## 증거

`classroom/lib/design/tokens.test.ts` 가 옛 값을 얼려 두고 새 역할의 계산된 값(밝은·어두운)을
대조한다. 옛 이름이 새 역할의 별칭인지도 본다. 유틸리티 이름만 바뀌었으므로 화면은 같다.

## 되돌리는 법

PR 하나를 revert 한다. 토큰 값이 옛 값 그대로라 데이터·마이그레이션은 없다.
