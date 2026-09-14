// 운영자 큐 시드(backend/accounts/management/commands/seed_e2e_operator_queues.py)가
// "이번 스위트 실행이 심은 Contest"와 "이전 실행이 남긴 Contest"를 구별하는 데
// 쓰는 토큰이다(코드리뷰 지적, #70). 예전에는 벽시계 기준 1시간 컷오프
// (STALE_AFTER)로 "오래된 것"을 정리했는데, 그 기준은 정확히 "연속 두 번 실행"
// 이라는 경우를 구별하지 못했다 — 깨끗한 스택에서 스위트를 연달아 두 번 돌리면
// 1회차가 심은 Contest는 정의상 1시간이 안 지나 살아남고, 2회차 것과 합쳐져
// 공개 목록 e2e(정렬·페이지네이션)를 깨뜨렸다.
//
// 그래서 시간 대신 **실행 하나를 식별하는 토큰**을 파일에 적어 공유한다.
// `playwright.config.ts`의 `globalSetup`(./global-setup.ts)이 스위트 시작 시
// 딱 한 번 이 파일을 새로 쓴다 — Playwright가 globalSetup 이후 fork하는 워커
// 프로세스에 `process.env` 변경분을 상속시켜 준다는 것이 공식 패턴으로 문서화돼
// 있지만, 그 상속에 기대다 어긋나면 "매 시드 호출이 서로 다른 토큰을 받아 서로의
// 형제를 지우는" 조용한 사고로 이어진다 — 파일은 프로세스 경계와 무관하게 항상
// 같은 값을 읽게 해 그 위험을 없앤다. 이 파일은 이 워크트리 전용이고
// `.gitignore`로 커밋되지 않는다.
import fs from "node:fs";
import path from "node:path";

const RUN_ID_FILE = path.resolve(__dirname, "../../.e2e-run-id");

/** `global-setup.ts`가 스위트 시작 시 한 번 쓴 실행 토큰을 읽는다. 시드
 * 헬퍼(seed-operator.ts)가 백엔드 관리 명령에 `CODEMIT_E2E_RUN_ID`로 실어
 * 보낸다. */
export function e2eRunId(): string {
  if (!fs.existsSync(RUN_ID_FILE)) {
    throw new Error(
      `${RUN_ID_FILE} 이 없다 — playwright.config.ts의 globalSetup(e2e/global-setup.ts)이 ` +
        "돌지 않은 채로 운영자 큐 시드 명령을 부른 것으로 보인다. `pnpm test`(playwright " +
        "test)를 거치지 않고 이 헬퍼를 직접 호출하면 이 에러가 난다.",
    );
  }
  return fs.readFileSync(RUN_ID_FILE, "utf-8").trim();
}
