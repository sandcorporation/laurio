// 「M/D」 짧은 날짜 — 클래스 상세의 강사 탭(수락일·초대 기한)과 참여자 탭(가입일)(#669), 클래스 설정의 채점 연결 확인일(#671)이 같은 말로 적는다.
// 화면마다 날짜를 새로 셈하지 않는다.
export function formatDay(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
