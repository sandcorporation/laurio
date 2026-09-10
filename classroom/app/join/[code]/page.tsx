"use client";

// 가입 링크 (#280). 계정이 없는 사람도 열어 미리보기를 본다 — middleware.ts가
// "/join"을 인증 구역에서 뺐다. 로그인만 되어 있으면 이름 하나로 회원가입과
// 클래스 가입이 한 번에 끝난다(#280 AC) — 두 화면으로 나뉘지 않는다.
//
// 폰으로 열린다는 전제라 고정 너비를 두지 않는다 — 텍스트가 줄바꿈되고
// 버튼이 세로로 쌓이는 기본 흐름 레이아웃만 쓴다.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

import { BackendError } from "@/lib/backend/client";
import { joinClass } from "@/lib/join/api";
import { useJoinPreview } from "@/lib/join/use-join-preview";

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "needsLogin" }
  | { status: "error"; message: string }
  | { status: "done"; classId: number; className: string; displayName: string };

export default function JoinPage() {
  const params = useParams<{ code: string }>();
  const code = params.code;
  const preview = useJoinPreview(code);
  const [displayName, setDisplayName] = useState("");
  const [submit, setSubmit] = useState<SubmitState>({ status: "idle" });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmit({ status: "submitting" });
    try {
      const result = await joinClass(code, displayName.trim());
      setSubmit({
        status: "done",
        classId: result.class_id,
        className: result.class_name,
        displayName: result.display_name,
      });
    } catch (error) {
      if (error instanceof BackendError && error.status === 401) {
        setSubmit({ status: "needsLogin" });
      } else if (error instanceof BackendError) {
        setSubmit({ status: "error", message: error.message });
      } else {
        setSubmit({ status: "error", message: "가입하지 못했습니다. 잠시 후 다시 시도해주세요." });
      }
    }
  }

  if (preview.status === "loading") {
    return (
      <main>
        <p data-testid="join-preview-loading">불러오는 중...</p>
      </main>
    );
  }

  if (preview.status === "dead") {
    return (
      <main>
        <h1 data-testid="join-preview-dead-heading">들어갈 수 없는 링크입니다</h1>
        <p data-testid="join-preview-dead-reason">{preview.reason}</p>
      </main>
    );
  }

  if (preview.status === "error") {
    return (
      <main>
        <p data-testid="join-preview-error">클래스 정보를 불러오지 못했습니다.</p>
      </main>
    );
  }

  const { preview: info } = preview;

  if (submit.status === "done") {
    return (
      <main>
        <h1 data-testid="join-done-heading">가입 완료</h1>
        <p data-testid="join-done-message">
          {submit.className}에 &quot;{submit.displayName}&quot;(으)로 참여했습니다.
        </p>
        <p>
          <Link href={`/classes/${submit.classId}/problems/mine`} data-testid="join-done-problems-link">
            문제 목록 보러 가기
          </Link>
        </p>
      </main>
    );
  }

  return (
    <main>
      <h1 data-testid="join-preview-heading">{info.class_name}</h1>
      <p data-testid="join-preview-instructor">강사 {info.instructor_email}</p>
      <p data-testid="join-preview-problem-count">문제 {info.problem_count}개</p>
      <p data-testid="join-preview-participant-count">참여자 {info.participant_count}명</p>

      {submit.status === "needsLogin" ? (
        <div>
          <p data-testid="join-needs-login">
            가입하려면 먼저 로그인해야 합니다. 로그인한 뒤 이 링크로 다시 돌아와 주세요.
          </p>
          <Link href="/login" data-testid="join-login-link">
            로그인하러 가기
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit}>
          <label htmlFor="join-display-name">이 클래스에서 불릴 이름</label>
          <input
            id="join-display-name"
            data-testid="join-display-name-input"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            required
          />
          <button
            type="submit"
            data-testid="join-submit"
            disabled={submit.status === "submitting" || displayName.trim() === ""}
          >
            {submit.status === "submitting" ? "가입하는 중..." : "가입하기"}
          </button>
        </form>
      )}

      {submit.status === "error" ? <p data-testid="join-error">{submit.message}</p> : null}
    </main>
  );
}
