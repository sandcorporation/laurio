// 삭제 확인 — 되돌릴 수 없어 실수로 눌리면 안 된다(#330). 클래스 이름을 그대로
// 다시 치게 해서, 버튼을 두 번 누르는 것보다 확실하게 "이 클래스가 맞다"는
// 확인을 받는다. 앞뒤 공백만 허용한다 — 대소문자나 부분 일치까지 봐주면
// 실수로 지우는 것을 막는다는 목적이 흐려진다.
export function isDeleteConfirmationTyped(className: string, typed: string): boolean {
  return typed.trim() === className;
}
