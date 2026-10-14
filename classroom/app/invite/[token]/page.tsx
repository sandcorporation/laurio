"use client";

// 공동 강사 초대 링크 (#561, CONTEXT.md 「공동 강사 초대」). 가입 링크(`/join/[code]`)와
// 같은 모양이다 — 로그인하지 않은 사람도 열어 어느 클래스의 공동 강사로 초대받았는지
// 보고(middleware.ts 가 "/invite"를 인증 구역에서 뺐다), 로그인을 거쳐 같은 초대로
// 돌아와 이 클래스에서 불릴 강사 이름을 넣고 수락한다. 수락하면 곧바로 그 클래스의
// 강사 화면으로 간다.
//
// 링크를 받은 사람이 대개 메신저에서 폰으로 연다 — 가입 링크와 같이 좁은 폭에서 한 칸으로
// 흐르고 버튼이 가로 전체를 쓴다.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Badge, Card, ErrorNote, FieldLabel, INPUT_CLASS, Note, buttonClass } from "@/app/components/ui";
import { useMe } from "@/lib/auth/use-me";
import { acceptCoInstructorInvite } from "@/lib/co-instructors/api";
import { useInvitePreview } from "@/lib/co-instructors/use-invite-preview";
import { checkDisplayNameForBannedWords } from "@/lib/members/display-name-check";

export default function CoInstructorInvitePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const preview = useInvitePreview(token);
  const me = useMe();
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (preview.status === "ready" && preview.preview.suggested_name) {
      setDisplayName((current) => (current === "" ? preview.preview.suggested_name! : current));
    }
  }, [preview]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = displayName.trim();
    const bannedWordMessage = checkDisplayNameForBannedWords(trimmedName);
    if (bannedWordMessage) {
      setError(bannedWordMessage);
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await acceptCoInstructorInvite(token, trimmedName);
    if (result.ok) {
      router.push(`/classes/${result.data.class_id}`);
      return;
    }
    setError(result.detail);
    setSubmitting(false);
  }

  if (preview.status === "loading") {
    return (
      <Shell>
        <p data-testid="invite-preview-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </Shell>
    );
  }

  if (preview.status === "dead") {
    return (
      <Shell>
        <h1 data-testid="invite-dead-heading" className="text-[21px] font-semibold leading-snug">
          열 수 없는 초대 링크입니다
        </h1>
        <p data-testid="invite-dead-reason" className="mt-3 text-[13.5px] leading-relaxed text-ink/60">
          {preview.reason}
        </p>
      </Shell>
    );
  }

  if (preview.status === "error") {
    return (
      <Shell>
        <ErrorNote>
          <span data-testid="invite-preview-error">초대 정보를 불러오지 못했습니다.</span>
        </ErrorNote>
      </Shell>
    );
  }

  const info = preview.preview;

  return (
    <Shell>
      <div className="flex flex-col gap-2">
        <div className="text-[11px] tracking-[0.08em] text-ink/45">공동 강사 초대</div>
        <h1 data-testid="invite-class-name" className="text-[24px] font-semibold leading-[1.3] tracking-[-0.01em]">
          {info.class_name}
        </h1>
        {info.instructor_names.length > 0 ? (
          <p data-testid="invite-instructors" className="text-[13px] text-ink/60">
            강사 {info.instructor_names.join(", ")}
          </p>
        ) : null}
      </div>

      {info.status !== "pending" ? (
        <Note tone="attention">
          <span data-testid="invite-unusable">{info.status_message}</span>
        </Note>
      ) : info.already_instructor ? (
        <Card className="p-5">
          <div className="flex flex-col gap-3">
            <span data-testid="invite-already-instructor" className="text-[13.5px]">
              이미 이 클래스의 강사입니다.
            </span>
            <Link
              href={`/classes/${info.class_id}`}
              data-testid="invite-go-to-class"
              className={`${buttonClass("primary")} w-full`}
            >
              클래스로 가기
            </Link>
          </div>
        </Card>
      ) : me.status === "error" ? (
        <Card className="p-5">
          <Link
            href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}
            data-testid="invite-login-link"
            className={`${buttonClass("primary")} w-full`}
          >
            로그인하고 수락하기
          </Link>
        </Card>
      ) : me.status === "loading" ? (
        <p data-testid="invite-login-status-loading" className="text-[13.5px] text-ink/45">
          확인하는 중...
        </p>
      ) : (
        <Card className="p-5">
          <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="invite-display-name">
                <FieldLabel>이 클래스에서 불릴 강사 이름</FieldLabel>
              </label>
              <input
                id="invite-display-name"
                data-testid="invite-display-name-input"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                required
                maxLength={100}
                className={INPUT_CLASS}
              />
            </div>
            {info.archived ? (
              <span data-testid="invite-archived">
                <Badge>보관됨</Badge>
              </span>
            ) : null}
            <button
              type="submit"
              data-testid="invite-accept"
              disabled={submitting || displayName.trim() === ""}
              className={`${buttonClass("primary")} w-full sm:w-auto sm:self-start`}
            >
              {submitting ? "수락하는 중..." : "공동 강사로 수락"}
            </button>
          </form>
        </Card>
      )}

      {error ? (
        <ErrorNote>
          <span data-testid="invite-error">{error}</span>
        </ErrorNote>
      ) : null}
    </Shell>
  );
}

/** 폰 우선 — 가입 링크 화면과 같은 폭. */
function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto flex w-full flex-col gap-7 max-w-[440px] px-5 py-12">{children}</main>;
}
