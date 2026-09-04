// 순수 함수 시임의 임포트 규칙을 기계로 강제하는 공유 Vite 플러그인(#160, ADR-0026).
//
// 각 앱/패키지의 vitest.config.ts가 이 파일을 상대경로로 불러 쓴다 — 규칙을 한 곳에
// 두어야 세 군데(frontend·operator·packages/bff-shared)가 각자 다른 규칙으로 갈리지
// 않는다(ADR-0021이 허용목록 검사 로직을 공유 패키지 하나로 둔 것과 같은 이유).
//
// **막는 것: react·react-dom 전부, 그리고 실행 중인 앱이 있어야만 의미 있는 next의
// 표면(next/navigation·next/router·next/link·next/image·next/head·next/dynamic·
// next/font·next/document·next/config, 그리고 프레임워크 서버/CLI 자체를 여는 맨
// "next").**
//
// **막지 않는 예외: `next/server`.** NextRequest/NextResponse는 Fetch API의
// Request/Response를 얇게 감싼 것뿐이라 Node에서 앱 없이도 동일하게 동작한다(직접
// 확인함 — `require("next/server")`로 NextResponse를 만들어 Location 헤더를 읽는
// 것이 실행 중인 Next 서버 없이 그대로 된다). ADR-0026이 순수 함수의 대상으로 명시한
// Origin 검증(packages/bff-shared/src/origin.ts)이 타입·응답 생성에 이 모듈을 쓰므로,
// 이 예외가 없으면 그 함수 자체를 이 시임에 못 둔다. DOM(window·document)은 여기서
// 따로 막지 않는다 — vitest 설정이 `environment: "node"`를 쓰면 그 전역이 애초에
// 존재하지 않아 참조하는 순간 ReferenceError로 터진다(별도 목록이 필요 없다).
import type { Plugin } from "vite";

const ALLOWED_NEXT_SUBPATHS = new Set(["next/server"]);

function isForbidden(source: string): boolean {
  if (/^react(-dom)?($|\/)/.test(source)) return true;
  if (source === "next") return true;
  if (/^next\//.test(source) && !ALLOWED_NEXT_SUBPATHS.has(source)) return true;
  return false;
}

export function pureModuleGuard(): Plugin {
  return {
    name: "pure-module-guard",
    enforce: "pre",
    resolveId(source) {
      if (isForbidden(source)) {
        throw new Error(
          `[pure-module-guard] "${source}"는 이 러너에서 금지된 임포트다. ` +
            `순수 함수 시임(ADR-0026)은 react나 next의 렌더링/라우팅 표면을 볼 수 없다 — ` +
            `그 위험(SSR·가드·라우팅)은 실행 중인 앱을 치는 e2e(ADR-0017/0021)의 몫이다.`,
        );
      }
      return null;
    },
  };
}
