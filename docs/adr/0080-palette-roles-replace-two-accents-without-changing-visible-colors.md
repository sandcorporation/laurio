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
   | warning · advanced | #c4442b / #e5694f | attention (둘이 같다) |
   | error | #b01e4a / #ff7a99 | attention → **#965 에서 갈랐다**(아래 「개정」) |
   | primary · secondary · info | #17160f / #ece8dc | 잉크 (아직 색상이 없다) |

   error 를 가르는 것은 후속 티켓(#965)이었고 아래 「개정」에서 했다. 그 표와
   `classroom/lib/design/tokens.test.ts` 의 얼린 값은 함께 고친다.
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

## 개정 (2026-11-19, #965) — error 만 가른다

- error 를 심화(advanced)와 겹치지 않는 장미빛 붉은색 **#b01e4a / #ff7a99**(밝음 / 어둠)로 정했다.
  warning·advanced 는 #c4442b / #e5694f 그대로다 — 둘을 가르는 것은 대표 결정에 없었다.
- 대비(WCAG): error 글자는 밝은 paper 6.04:1 · surface 6.65:1, 어두운 paper 7.33:1 · surface 6.66:1(전부 4.5:1 이상).
  advanced 와의 구별: 색상각 OKLCH 10°↔33°(밝음), 7°↔33°(어둠) — 23°·26° 차, 명도 0.065·0.075 차.
- 세 앱의 토큰 파일이 한 벌이라(위 3번) 공개 앱·운영자 앱의 error 쓰는 자리와 `--color-attention`
  별칭(= error)을 쓰는 운영자 화면도 같이 장미빛으로 바뀐다. 대조 시험은 그대로 둔다.
- 강의실 화면은 자리마다 error(오류·실패·검증 오류)·warning(주의·마감 지남·대기)·advanced(심화)를
  갈랐다. `Badge`·`Note` 의 톤은 `attention` 대신 `error`·`warning` 이다(3번의 속성 이름 유지는 이
  개정으로 강의실에서 풀렸다).
- 얼린 값(`classroom/lib/design/tokens.test.ts`)과 위 표를 함께 고쳤다.

## 개정 (2026-11-19, #978) — 경고·심화 글자색을 AA 위로

- 밝은 테마 warning·advanced 를 **#c4442b → #c3442b** 로 명도만 낮췄다(둘은 같은 색으로 둔다 — 대표 결정). 어두운 값 #e5694f 는 그대로다.
- 까닭: #c4442b 가 밝은 paper 위에서 4.49:1 로 AA(4.5:1)에 0.01 모자랐다. 가장 작은 폭이 #c3442b 다.
- 대비 전후: 밝음 paper 4.49 → 4.52 · surface 4.94 → 4.98, 어둠 paper 5.58 · surface 5.07(변경 없음).
- `frontend/lib/design/contrast.test.ts` 가 warning·advanced·error × paper·surface 를 두 테마에서 4.5:1 이상으로 고정한다.

## 되돌리는 법

PR 하나를 revert 한다. 토큰 값이 옛 값 그대로라 데이터·마이그레이션은 없다.
