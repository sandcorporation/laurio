"use client";

// 템플릿 신고 판단 폼(#320) — 이의 심판 폼(ruling-form.tsx)과 같은 모양이다:
// 버튼 둘, 둘 다 `type="button"`으로 각자 자기 decision을 들고 직접 요청을
// 보낸다. 「내림」과 「기각」 둘 다 이유(note)가 필수다 — 서버가 최종
// 판정한다(422).
import { useState } from "react";

import { bffClient } from "@/lib/bff/client";

import type { ModerationDecision, ProblemTemplate } from "./types";

type FormState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "redirecting" }
  | { status: "error"; message: string };

export function ModerationForm({
  templateId,
  onDecided,
}: {
  templateId: number;
  onDecided: (decision: ModerationDecision, template: ProblemTemplate) => void;
}) {
  const [note, setNote] = useState("");
  const [state, setState] = useState<FormState>({ status: "idle" });

  async function submit(decision: ModerationDecision) {
    setState({ status: "submitting" });

    const result = await bffClient.post<ProblemTemplate>(
      `/api/backend/operator/classroom/problem-templates/${templateId}/moderate`,
      { decision, note },
    );

    if (!result.ok) {
      if (result.code === "unauthorized") {
        setState({ status: "redirecting" });
        return;
      }
      setState({ status: "error", message: result.detail });
      return;
    }

    setState({ status: "idle" });
    onDecided(decision, result.data);
  }

  const submitting = state.status === "submitting";

  return (
    <form data-testid={`moderation-form-${templateId}`} onSubmit={(event) => event.preventDefault()}>
      <label>
        이유
        <textarea
          data-testid={`moderation-note-${templateId}`}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          disabled={submitting}
        />
      </label>

      <button
        type="button"
        data-testid={`moderation-takedown-${templateId}`}
        onClick={() => submit("takedown")}
        disabled={submitting}
      >
        내리기
      </button>
      <button
        type="button"
        data-testid={`moderation-dismiss-${templateId}`}
        onClick={() => submit("dismiss")}
        disabled={submitting}
      >
        기각
      </button>

      {state.status === "redirecting" && (
        <p data-testid={`moderation-redirecting-${templateId}`}>
          세션이 만료되어 로그인 화면으로 이동합니다...
        </p>
      )}

      {state.status === "error" && (
        <p role="alert" data-testid={`moderation-error-${templateId}`}>
          {state.message}
        </p>
      )}
    </form>
  );
}
