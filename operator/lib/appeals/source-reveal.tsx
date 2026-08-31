"use client";

// 소스 펼침(#66, ADR-0022) — 이 티켓의 핵심.
//
// **접혀 있다는 것은 "아직 가져오지 않았다"는 뜻이다.** 상세 조회(useAppealDetail)와
// 소스 펼침은 완전히 분리된 요청이다 — 이 컴포넌트는 마운트 시 아무것도 fetch하지
// 않는다. `state`가 "collapsed"인 동안 소스 문자열은 이 컴포넌트도, 부모도, 어떤
// 자바스크립트 변수도 들고 있지 않다. 그래서 "펼치기 전 화면 어디에도 소스
// 내용이 없다"는 #66 AC가 `display:none`으로 숨기는 방식과 달리 구조적으로
// 성립한다.
//
// **펼치는 행위 자체가 POST다.** 백엔드가 이 요청 하나로 SourceReading을 남기고
// 소스를 돌려준다(backend/appeals/api.py의 reveal_appeal_source) — 기록 없이
// 소스만 얻는 경로가 없다. 그래서 경고 문구는 버튼을 누르기 **전에** 항상
// 보인다: "펼치면 기록된다"는 사실을 행위 이후가 아니라 이전에 알려야 그 기록이
// 운영자가 선택한 일이 된다(ADR-0022).
import { useRouter } from "next/navigation";
import { useState } from "react";

type RevealState =
  | { status: "collapsed" }
  | { status: "revealing" }
  | { status: "redirecting" }
  | { status: "revealed"; prompt: string }
  | { status: "error"; message: string };

export function SourceReveal({ appealId }: { appealId: number }) {
  const router = useRouter();
  const [state, setState] = useState<RevealState>({ status: "collapsed" });

  async function reveal() {
    setState({ status: "revealing" });
    try {
      const res = await fetch(`/api/backend/operator/appeals/${appealId}/source`, {
        method: "POST",
      });

      if (res.status === 401) {
        // 세션이 만료됐다 — 코드리뷰 지적: 이전에는 여기서 state를 그대로
        // "revealing"에 남겨둔 채 router.replace만 불렀다. 내비게이션이
        // 늦거나(느린 네트워크) 실패하면 비활성화된 "펼치는 중..." 버튼만
        // 남고 오류도 재시도 수단도 없이 화면이 그 상태에 갇힌다. 이동을
        // 시작하기 전에 먼저 상태를 바꿔, 내비게이션이 어떻게 되든 화면이
        // 더 이상 "펼치는 중"으로 보이지 않게 한다.
        setState({ status: "redirecting" });
        router.replace("/login");
        return;
      }
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setState({
          status: "error",
          message: body?.detail ?? `소스를 펼치지 못했습니다 (${res.status}).`,
        });
        return;
      }

      const body = (await res.json()) as { prompt: string };
      setState({ status: "revealed", prompt: body.prompt });
    } catch {
      setState({ status: "error", message: "소스를 펼치는 요청을 보내지 못했습니다." });
    }
  }

  return (
    <section data-testid="appeal-source-section">
      <h2>제출 소스</h2>
      <p data-testid="appeal-source-warning">
        펼치면 이 열람이 기록되고, Developer가 자기 Submission의 열람 기록에서 그
        시각을 확인할 수 있습니다. 심판에 정말 필요할 때만 펼치세요.
      </p>

      {state.status !== "revealed" && state.status !== "redirecting" && (
        <button
          type="button"
          data-testid="appeal-source-reveal-button"
          onClick={reveal}
          disabled={state.status === "revealing"}
        >
          {state.status === "revealing" ? "펼치는 중..." : "소스 펼치기"}
        </button>
      )}

      {state.status === "redirecting" && (
        <p data-testid="appeal-source-redirecting">세션이 만료되어 로그인 화면으로 이동합니다...</p>
      )}

      {state.status === "error" && (
        <p role="alert" data-testid="appeal-source-error">
          {state.message}
        </p>
      )}

      {state.status === "revealed" && (
        <pre data-testid="appeal-source-content">{state.prompt}</pre>
      )}
    </section>
  );
}
