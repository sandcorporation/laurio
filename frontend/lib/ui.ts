// 되돌릴 수 없는 행위의 버튼 색 규칙 한 곳(#344). 그릴링으로 정한 규칙은 셋 —
// 입구·한 번에 끝나는 버튼은 주의색 테두리, 확인을 거친 최종 실행은 주의색
// 채움, 되돌릴 수 있는 것은 보통. 화면마다 `text-attention`을 직접 적으면
// 다시 갈라지므로(탈퇴 진입점이 회색이고 인수인계 확인 입구가 강조색 채움이던
// 것처럼) 색만 여기서 낸다 — 크기·모서리는 화면마다 달라 이 함수가 정하지
// 않는다.
export type DangerButtonVariant = "outline" | "filled";

export function dangerButtonClass(variant: DangerButtonVariant): string {
  if (variant === "filled") {
    return "border border-attention bg-attention text-paper hover:bg-attention/85";
  }
  return "border border-attention text-attention hover:bg-attention/10";
}
