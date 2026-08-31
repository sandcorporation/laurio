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
import { useRouter } from "next/navigation";
import { useState } from "react";

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
  const router = useRouter();
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
    let res: Response;
    try {
      res = await fetch(`/api/backend/operator/appeals/${appealId}/rule`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {
      setState({ status: "error", message: "심판 요청을 보내지 못했습니다." });
      return;
    }

    if (res.status === 401) {
      // 심판 중 세션이 만료됐다 — source-reveal.tsx와 같은 원칙: state를
      // "submitting"에 남긴 채 router.replace만 부르면 이동이 늦거나 실패했을
      // 때 비활성화된 버튼만 남고 화면이 그 상태에 갇힌다. 이동을 시작하기
      // 전에 먼저 상태를 바꾼다. 이 분기에서 심판은 일어나지 않았다 — 서버가
      // 401을 냈다는 것 자체가 이 요청이 인증되지 않아 아무 것도 반영되지
      // 않았다는 뜻이다.
      setState({ status: "redirecting" });
      router.replace("/login");
      return;
    }

    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
      // detail이 항상 문자열은 아니다 — 이 폼이 명시적으로 다루는 두 거절
      // (correction_amount 누락, ruling_note 공백)은 커스텀 HttpError라 항상
      // 문자열이지만, pydantic 필드 검증(예: correction_amount<=0)이 걸리면
      // ninja가 배열 형태의 422를 낸다. 문자열이 아니면 그대로 렌더하지 않고
      // 일반 메시지로 대체한다 — "Objects are not valid as a React child"로
      // 화면이 깨지는 것을 막는다.
      const detail = typeof body?.detail === "string" ? body.detail : null;
      setState({
        status: "error",
        message: detail ?? `심판에 실패했습니다 (${res.status}).`,
      });
      return;
    }

    // 여기 도달했으면 심판은 이미 확정됐다(res.ok) — 아래는 그 결과를 화면에
    // 옮기는 절차일 뿐이고, 여기서 무엇이 잘못돼도 "심판이 안 됐다"는 뜻이
    // 아니다. rule 엔드포인트는 AppealOut(요약)만 돌려준다 — ruled_by_username
    // 같은 심판자 신원은 상세 응답(AppealDetailOut.ruling)에만 있다. 손으로
    // 재구성하지 않고 상세를 다시 조회해 그대로 쓴다 — 요청(uphold/reject)과
    // 응답(upheld/rejected)의 어휘가 다른 함정(#66이 이미 겪었다)을 여기서
    // 또 틀리지 않기 위해서다.
    try {
      const detailRes = await fetch(`/api/backend/operator/appeals/${appealId}`, {
        cache: "no-store",
      });
      if (detailRes.status === 401) {
        setState({ status: "redirecting" });
        router.replace("/login");
        return;
      }
      if (!detailRes.ok) {
        setState({
          status: "error",
          message: "심판은 반영됐지만 결과를 다시 불러오지 못했습니다. 새로고침해주세요.",
        });
        return;
      }
      const detail = (await detailRes.json()) as { ruling: AppealRuling | null };
      if (!detail.ruling) {
        setState({
          status: "error",
          message: "심판은 반영됐지만 결과를 확인하지 못했습니다. 새로고침해주세요.",
        });
        return;
      }
      onRuled(detail.ruling);
    } catch {
      setState({
        status: "error",
        message: "심판은 반영됐지만 결과를 다시 불러오지 못했습니다. 새로고침해주세요.",
      });
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
