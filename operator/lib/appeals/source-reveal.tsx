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
import { useState } from "react";

import { bffClient } from "@/lib/bff/client";

type RevealState =
  | { status: "collapsed" }
  | { status: "revealing" }
  | { status: "redirecting" }
  | { status: "revealed"; prompt: string }
  | { status: "error"; message: string };

export function SourceReveal({
  appealId,
  onRevealed,
}: {
  appealId: number;
  /** 펼침이 성공한 순간을 부모에게 알린다(#423) — 이의 상세의 감사 추적 카드가
   * "지금 이 세션에서 누가 언제 열어봤는지" 를 실제로 일어난 사건으로 쌓기
   * 위해서다. 호출하지 않아도 이 컴포넌트의 동작은 그대로다. */
  onRevealed?: () => void;
}) {
  const [state, setState] = useState<RevealState>({ status: "collapsed" });

  async function reveal() {
    setState({ status: "revealing" });

    const result = await bffClient.post<{ prompt: string }>(
      `/api/backend/operator/appeals/${appealId}/source`,
    );

    if (result.ok) {
      setState({ status: "revealed", prompt: result.data.prompt });
      onRevealed?.();
      return;
    }
    if (result.code === "unauthorized") {
      // 세션이 만료됐다 — 클라이언트가 로그인으로 보낸다. 이동이 늦거나 실패해도 화면이
      // "펼치는 중..."에 갇히지 않도록 상태를 먼저 바꾼다(코드리뷰 지적).
      setState({ status: "redirecting" });
      return;
    }
    if (result.code === "network") {
      setState({ status: "error", message: "소스를 펼치는 요청을 보내지 못했습니다." });
      return;
    }
    setState({ status: "error", message: result.detail });
  }

  return (
    <section data-testid="appeal-source-section" className="border-t border-rule">
      <div className="border-b border-rule px-4 py-3 text-[14px] font-semibold">AI 채점 원문</div>
      <div className="flex flex-col gap-3 p-4">
        <p data-testid="appeal-source-warning" className="text-[12px] leading-relaxed text-ink/45">
          펼치면 이 열람이 기록되고, Developer가 자기 Submission의 열람 기록에서 그
          시각을 확인할 수 있습니다. 심판에 정말 필요할 때만 펼치세요.
        </p>

        {state.status !== "revealed" && state.status !== "redirecting" && (
          <button
            type="button"
            data-testid="appeal-source-reveal-button"
            onClick={reveal}
            disabled={state.status === "revealing"}
            className="w-fit border border-rule bg-surface px-3 py-1.5 text-[12.5px] text-ink disabled:opacity-50"
          >
            {state.status === "revealing" ? "펼치는 중..." : "소스 펼치기"}
          </button>
        )}

        {state.status === "redirecting" && (
          <p data-testid="appeal-source-redirecting" className="text-[12.5px] text-ink/62">
            세션이 만료되어 로그인 화면으로 이동합니다...
          </p>
        )}

        {state.status === "error" && (
          <p role="alert" data-testid="appeal-source-error" className="text-[12.5px] text-attention">
            {state.message}
          </p>
        )}

        {state.status === "revealed" && (
          <pre
            data-testid="appeal-source-content"
            className="max-h-80 overflow-auto border border-rule bg-paper p-3 text-[12px] whitespace-pre-wrap"
          >
            {state.prompt}
          </pre>
        )}
      </div>
    </section>
  );
}
