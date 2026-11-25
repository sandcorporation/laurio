// 클래스·강사 이름 저장이 끝난 뒤 클래스를 다시 읽을지(#1447 11).
//
// 실패해도 무조건 다시 읽던 때에는, 다시 읽어 온 새 클래스가 적던 칸을 저장된 값으로 덮어 적던 값과 방금 난
// 오류가 함께 사라졌다. 저장이 됐거나(저장된 값으로 맞춘다), 접근을 잃었는지 확인해야 할 때(404·403 — 안내 화면이
// 뜨고 적던 값은 그 곁에 남는다)만 다시 읽는다.
export function reloadAfterNameSave(failure: { status: number } | null): boolean {
  if (failure === null) return true;
  return failure.status === 404 || failure.status === 403;
}
