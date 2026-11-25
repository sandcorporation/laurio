// 모달 창 안에 Tab 을 가둔다(#1463). 눌린 Tab 이 창 가장자리를 넘어가려 하면 반대편 끝의 위치를 돌려주고,
// 창 안에서 자연히 움직일 때는 null 이라 브라우저에 맡긴다. 초점이 창 밖(-1)이면 가장자리로 끌어들인다.
export function trapTabTarget(shift: boolean, current: number, count: number): number | null {
  if (count <= 0) return null;
  if (current < 0) return shift ? count - 1 : 0;
  if (shift && current === 0) return count - 1;
  if (!shift && current === count - 1) return 0;
  return null;
}
