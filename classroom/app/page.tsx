// 「내 클래스」 홈 (#276) — 뼈대뿐이다. Class 모델이 아직 없어(이 체인은 인프라만
// 짓는다) 항상 빈 상태를 보여준다. 이 화면에 닿는다는 것 자체가 미들웨어 가드를
// 통과했다는 뜻이라(middleware.ts) 여기서 다시 세션을 확인하지 않는다 — 강의실은
// 자기 로그인이 없고(ADR-0038) 클라이언트 세션 훅도 아직 필요하지 않다.
export default function ClassroomHome() {
  return (
    <main>
      <h1 data-testid="classroom-home-heading">내 클래스</h1>
      <p data-testid="classroom-empty-state">아직 가입하거나 개설한 클래스가 없습니다.</p>
    </main>
  );
}
