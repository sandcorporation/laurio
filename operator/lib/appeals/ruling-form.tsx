"use client";

// 이의 심판 폼(#67) — 이 스펙의 목적지. #24가 "이의 심판에 감사 추적이 없다"고
// 지적한 것을 사람이 실제로 쓸 수 있는 화면으로 만든다.
//
// **인용에는 정정 금액과 이유가, 기각에도 이유가 필요하다.** 클라이언트에서
// 막지 않고 서버(backend/appeals/api.py의 rule_appeal)가 최종 판정을 내린다 —
// 이 폼은 그 판정을 그대로 화면에 보여줄 뿐, 규칙을 다시 구현하지 않는다.
//
// **버튼은 두 개, 둘 다 `type="button"`이다.** 하나의 `<form>` 안에 "인용"과
// "기각"이라는 서로 다른 결정을 내는 제출 지점 두 개를 두되, 네이티브 form
// submit(그리고 `SubmitEvent.submitter`에 기대는 방식)에 기대지 않는다 — 각
// 버튼이 자기 decision을 들고 직접 요청을 보낸다.
//
// **제출 중에는 두 버튼 모두 비활성화된다.** 서버의 조건부 UPDATE가 이중 심판의
// 최후 방어선이지만(append-only 원장에 정정이 두 번 남지 않게), 화면이 먼저
// 더블 클릭 자체를 막는 것도 필요하다 — #67이 그리는 두 겹의 방어와 같은 결.
import { useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { AppealRuling } from "./types";

type RulingFormState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "redirecting" }
  | { status: "error"; message: string };

export function RulingForm({
  appealId,
  onRuled,
}: {
  appealId: number;
  onRuled: (ruling: AppealRuling) => void;
}) {
  const [note, setNote] = useState("");
  const [correctionAmount, setCorrectionAmount] = useState("");
  const [state, setState] = useState<RulingFormState>({ status: "idle" });

  async function submit(decision: "uphold" | "reject") {
    setState({ status: "submitting" });

    const payload: { decision: string; ruling_note: string; correction_amount?: number } = {
      decision,
      ruling_note: note,
    };
    if (decision === "uphold") {
      const trimmed = correctionAmount.trim();
      if (trimmed !== "") {
        const amount = Number(trimmed);
        // 파싱 불가한 값은 정정 금액을 아예 안 보낸 것과 같게 취급한다 —
        // 서버가 "정정 금액이 필요합니다"로 거절하게 둔다(422).
        if (!Number.isNaN(amount)) payload.correction_amount = amount;
      }
    }

    // **두 요청을 별도 try/catch로 가른다(코드리뷰 지적).** 심판 POST 자체가
    // 실패한 것과, 심판은 성공했는데 뒤이은 상세 재조회가 실패한 것은 전혀
    // 다른 사실이다 — 전자는 "아무 일도 일어나지 않았다"이고 후자는 "돈이
    // 이미 움직였는데 화면만 그걸 못 보여준다"다. 하나의 try로 감싸면 후자가
    // "심판 요청을 보내지 못했습니다"로 보이고, 운영자가 그 말을 믿고
    // 재시도해 409를 만난다 — 돈을 움직이는 화면에서 "일어났다"와 "안
    // 일어났다"를 뒤집어 말하면 안 된다.
    const ruled = await bffClient.post(`/api/backend/operator/appeals/${appealId}/rule`, payload);

    if (!ruled.ok) {
      if (ruled.code === "network") {
        setState({ status: "error", message: "심판 요청을 보내지 못했습니다." });
        return;
      }
      if (ruled.code === "unauthorized") {
        // 심판 중 세션이 만료됐다 — 클라이언트가 로그인으로 보낸다. 다만 state 를 "submitting"
        // 에 남겨두면 이동이 늦거나 실패했을 때 비활성화된 버튼만 남고 화면이 그 상태에
        // 갇힌다(코드리뷰 지적). 이 분기에서 심판은 일어나지 않았다 — 서버가 401 을 냈다는 것
        // 자체가 이 요청이 인증되지 않아 아무 것도 반영되지 않았다는 뜻이다.
        setState({ status: "redirecting" });
        return;
      }
      // `detail` 정규화(ninja 422 의 배열 detail 포함)는 패키지가 한다(#148).
      setState({ status: "error", message: ruled.detail });
      return;
    }

    // 재조회 실패는 「심판이 안 됐다」가 아니다 — 돈은 이미 움직였고 화면만 못 따라온 것이다.
    {
      const refreshed = await bffClient.get<{ ruling: AppealRuling | null }>(
        `/api/backend/operator/appeals/${appealId}`,
      );

      if (!refreshed.ok) {
        setState(
          refreshed.code === "unauthorized"
            ? { status: "redirecting" }
            : {
                status: "error",
                message: "심판은 반영됐지만 결과를 다시 불러오지 못했습니다. 새로고침해 주세요.",
              },
        );
        return;
      }

      const detail = refreshed.data;
      if (!detail.ruling) {
        setState({
          status: "error",
          message: "심판은 반영됐지만 결과를 다시 불러오지 못했습니다. 새로고침해 주세요.",
        });
        return;
      }

      onRuled(detail.ruling);
    }
  }

  const submitting = state.status === "submitting";

  return (
    <form data-testid="ruling-form" onSubmit={(event) => event.preventDefault()}>
      <h2>심판</h2>

      <label>
        이유
        <textarea
          data-testid="ruling-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          disabled={submitting}
        />
      </label>

      <label>
        정정 금액 (인용 시 필수 — 원 단위)
        <input
          type="number"
          data-testid="ruling-correction-amount"
          value={correctionAmount}
          onChange={(event) => setCorrectionAmount(event.target.value)}
          disabled={submitting}
        />
      </label>

      <button
        type="button"
        data-testid="ruling-uphold-button"
        onClick={() => submit("uphold")}
        disabled={submitting}
      >
        인용
      </button>
      <button
        type="button"
        data-testid="ruling-reject-button"
        onClick={() => submit("reject")}
        disabled={submitting}
      >
        기각
      </button>

      {state.status === "redirecting" && (
        <p data-testid="ruling-redirecting">세션이 만료되어 로그인 화면으로 이동합니다...</p>
      )}

      {state.status === "error" && (
        <p role="alert" data-testid="ruling-error">
          {state.message}
        </p>
      )}
    </form>
  );
}
