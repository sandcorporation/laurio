"use client";

// 동의 화면의 본문 (#870) — 요청을 백엔드에 확인받고, 허락·거절을 보낸 뒤 백엔드가 돌려준
// 주소(앱의 콜백)로 브라우저를 넘긴다. 강의실의 같은 화면(classroom/app/oauth/authorize)과 같은 흐름이다.
import { useEffect, useState } from "react";

import { Card, ErrorNote, buttonClass } from "@/app/components/ui";
import { useSession } from "@/lib/auth/use-session";
import {
  appDisplayName,
  decideAuthorization,
  fetchAuthorizationPreview,
  type AuthorizationPreview,
  type AuthorizeParams,
} from "@/lib/connected-apps/api";

type State =
  | { status: "loading" }
  | { status: "invalid"; detail: string }
  | { status: "ready"; preview: AuthorizationPreview };

export function ConsentPanel({ params }: { params: AuthorizeParams }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [submitting, setSubmitting] = useState<"approve" | "deny" | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const session = useSession();

  useEffect(() => {
    fetchAuthorizationPreview(params).then((result) => {
      setState(result.ok ? { status: "ready", preview: result.data } : { status: "invalid", detail: result.detail });
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
          <ErrorNote testId="consent-invalid-detail">{state.detail}</ErrorNote>
        </div>
      </div>
    );
  }

  const name = appDisplayName(state.preview.client_name);
  const email = session.status === "authenticated" ? session.user.email : "";

  return (
    <div className="mx-auto max-w-[560px] pt-6">
      <div className="text-[11px] tracking-[0.08em] text-ink/45">앱 연결</div>
      <h1 className="mt-1.5 text-[22px] font-semibold tracking-[-0.01em]" data-testid="consent-heading">
        {name}을(를) 연결할까요?
      </h1>
      <p className="mt-2 text-[13px] leading-relaxed text-ink/60">
        허락하면 이 앱이 내 계정으로 무료 공모전을 만들고 관리합니다.
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
            내가 연 <strong className="font-semibold">무료 공모전</strong>을 만들고, 고치고, 공개하고, 마감하고,
            수상작을 고르고, 보관할 수 있습니다. 앞으로 여는 공모전도 포함됩니다.
          </li>
          <li className="px-4 py-3">제출물은 참가자의 표시 이름·낸 시각·수상 여부만 전달됩니다.</li>
          <li className="px-4 py-3">유료 공모전은 다루지 못하고, 상금을 넣을 수 없습니다.</li>
          <li className="px-4 py-3">「내 정보」에서 언제든 끊을 수 있습니다. 90일 동안 쓰지 않으면 저절로 끊깁니다.</li>
        </ul>
      </Card>

      <p className="mt-4 text-[12.5px] text-ink/60" data-testid="consent-redirect-host">
        허락하거나 거절하면 <span className="font-mono text-ink">{state.preview.redirect_host}</span>(으)로 돌아갑니다.
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
