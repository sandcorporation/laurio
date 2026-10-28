"use client";

// 동의 화면의 본문 (ADR-0052, #512) — 요청을 백엔드에 확인받고, 허락·거절을 보낸 뒤
// 백엔드가 돌려준 주소(앱의 콜백)로 브라우저를 넘긴다.
import { useEffect, useState } from "react";

import { Card, ErrorNote, buttonClass } from "@/app/components/ui";
import { useMe } from "@/lib/auth/use-me";
import {
  appDisplayName,
  decideAuthorization,
  fetchAuthorizationPreview,
  type AuthorizationPreview,
  type AuthorizeParams,
} from "@/lib/connected-apps/api";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";

type State =
  | { status: "loading" }
  | { status: "invalid"; detail: string }
  | { status: "ready"; preview: AuthorizationPreview };

export function ConsentPanel({ params }: { params: AuthorizeParams }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [submitting, setSubmitting] = useState<"approve" | "deny" | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const me = useMe();

  useClassroomTabTitle({ screenName: "앱 연결" });

  useEffect(() => {
    fetchAuthorizationPreview(params).then((result) => {
      setState(
        result.ok ? { status: "ready", preview: result.data } : { status: "invalid", detail: result.detail },
      );
    });
    // 쿼리는 이 화면이 사는 동안 바뀌지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function decide(approve: boolean) {
    setSubmitting(approve ? "approve" : "deny");
    setSubmitError(null);
    const result = await decideAuthorization(params, approve);
    if (result.ok) {
      window.location.assign(result.data.redirect_to);
      return;
    }
    setSubmitError(result.detail);
    setSubmitting(null);
  }

  if (state.status === "loading") {
    return <div className="mx-auto max-w-[560px] pt-10 text-[13.5px] text-ink/45">불러오는 중…</div>;
  }

  if (state.status === "invalid") {
    return (
      <div className="mx-auto max-w-[560px] pt-10">
        <h1 className="text-[22px] font-semibold tracking-[-0.01em]" data-testid="consent-invalid-heading">
          연결할 수 없습니다
        </h1>
        <div className="mt-4">
          <ErrorNote>{state.detail}</ErrorNote>
        </div>
      </div>
    );
  }

  const name = appDisplayName(state.preview.client_name);
  const email = me.status === "ready" ? me.email : "";

  return (
    <div className="mx-auto max-w-[560px] pt-6">
      <div className="text-[11px] tracking-[0.08em] text-ink/45">앱 연결</div>
      <h1 className="mt-1.5 text-[22px] font-semibold tracking-[-0.01em]" data-testid="consent-heading">
        {name}을(를) 연결할까요?
      </h1>
      <p className="mt-2 text-[13px] leading-relaxed text-ink/60">
        허락하면 이 앱이 내 계정으로 강의실에 접근합니다.
        {email ? (
          <>
            {" "}
            허락하는 계정: <span className="text-ink" data-testid="consent-account">{email}</span>
          </>
        ) : null}
      </p>

      <Card className="mt-6">
        <ul className="flex flex-col divide-y divide-rule text-[13.5px] leading-relaxed">
          <li className="px-4 py-3">
            내가 강사인 <strong className="font-semibold">모든 클래스</strong>에서 화면과 같은 일을 할 수
            있습니다. 앞으로 만드는 클래스도 포함됩니다.
          </li>
          <li className="px-4 py-3">참여자의 제출물과 참여자가 클래스에서 쓰는 이름이 이 앱으로 전달될 수 있습니다.</li>
          <li className="px-4 py-3">클래스의 채점 키는 넣거나 바꿀 수 없습니다.</li>
          <li className="px-4 py-3">「연결된 앱」에서 언제든 끊을 수 있습니다. 90일 동안 쓰지 않으면 저절로 끊깁니다.</li>
        </ul>
      </Card>

      <p className="mt-4 text-[12.5px] text-ink/60" data-testid="consent-redirect-host">
        허락하거나 거절하면 <span className="font-mono text-ink">{state.preview.redirect_host}</span>(으)로
        돌아갑니다.
      </p>

      {submitError ? (
        <div className="mt-4">
          <ErrorNote>{submitError}</ErrorNote>
        </div>
      ) : null}

      <div className="mt-6 flex flex-wrap gap-2">
        <button
          type="button"
          className={buttonClass("primary")}
          data-testid="consent-approve"
          disabled={submitting !== null}
          onClick={() => decide(true)}
        >
          {submitting === "approve" ? "연결하는 중…" : "허락"}
        </button>
        <button
          type="button"
          className={buttonClass("secondary")}
          data-testid="consent-deny"
          disabled={submitting !== null}
          onClick={() => decide(false)}
        >
          거절
        </button>
      </div>
    </div>
  );
}
