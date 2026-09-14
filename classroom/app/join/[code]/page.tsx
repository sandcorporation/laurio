"use client";

// 가입 링크 (#280). 계정이 없는 사람도 열어 미리보기를 본다 — middleware.ts가
// "/join"을 인증 구역에서 뺐다. 로그인만 되어 있으면 이름 하나로 회원가입과
// 클래스 가입이 한 번에 끝난다(#280 AC) — 두 화면으로 나뉘지 않는다.
//
// **폰으로 열린다는 전제다**(#298, 시안 Join.dc.html 은 390×844) — 링크를 받은
// 사람이 대개 폰에서 연다. 그래서 고정 너비를 두지 않고, 좁은 폭에서 한 칸으로
// 흐르며 버튼이 가로 전체를 쓰는 레이아웃이다.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  Badge,
  Card,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  Num,
  buttonClass,
} from "@/app/components/ui";
import { BackendError } from "@/lib/backend/client";
import { useMe } from "@/lib/auth/use-me";
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
  // 로그인 여부를 이름 칸을 보여주기 전에 먼저 안다(#387) — 이미 트리 전체가
  // 공유하는 `MeProvider` 조회를 그대로 쓴다(계정 메뉴·알림 종과 같은 신호,
  // `me-context.tsx`). 이 앱에서 "error"는 대개 익명 방문자의 401이다 — 세션이
  // 아예 없거나 만료된 쿠키나 결과가 같게 다뤄진다.
  const me = useMe();
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [submit, setSubmit] = useState<SubmitState>({ status: "idle" });

  // 이미 가입한 사람(내보내진 사람 포함)이 링크를 다시 열면 이름 입력 폼이
  // 아니라 곧장 문제 목록으로 보낸다(#300 AC) — 두 번째 가입 요청은 보내지
  // 않는다, 이미 정한 이름과 내보낸 사실 둘 다 바뀌면 안 되기 때문이다.
  useEffect(() => {
    if (preview.status === "ready" && preview.preview.already_joined) {
      router.replace(`/classes/${preview.preview.class_id}/problems/mine`);
    }
  }, [preview, router]);

  // 이름 칸을 카카오 닉네임으로 미리 채운다(#390 AC) — 로그인한 요청에만
  // 오는 값이라(비로그인·미동의·비카카오 제공자는 `null`) 그때만 채워진다.
  // 아직 아무것도 입력하지 않았을 때만 채운다 — 사람이 고쳐 쓴 뒤에 이
  // 효과가 다시 돌아 덮어쓰는 일이 없게 하기 위해서다.
  useEffect(() => {
    if (preview.status === "ready" && preview.preview.suggested_name) {
      setDisplayName((current) => (current === "" ? preview.preview.suggested_name! : current));
    }
  }, [preview]);

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
      <Shell>
        <p data-testid="join-preview-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </Shell>
    );
  }

  if (preview.status === "dead") {
    return (
      <Shell>
        <h1 data-testid="join-preview-dead-heading" className="text-[21px] font-semibold leading-snug">
          들어갈 수 없는 링크입니다
        </h1>
        <p data-testid="join-preview-dead-reason" className="mt-3 text-[13.5px] leading-relaxed text-ink/60">
          {preview.reason}
        </p>
      </Shell>
    );
  }

  if (preview.status === "error") {
    return (
      <Shell>
        <ErrorNote>
          <span data-testid="join-preview-error">클래스 정보를 불러오지 못했습니다.</span>
        </ErrorNote>
      </Shell>
    );
  }

  if (preview.preview.already_joined) {
    // 위 useEffect가 이동을 시작한다 — 그 사이 이름 입력 폼이 잠깐이라도
    // 보이면 안 되므로 여기서 렌더를 멈춘다.
    return (
      <Shell>
        <p data-testid="join-already-joined" className="text-[13.5px] text-ink/45">
          이미 참여한 클래스입니다. 문제 목록으로 이동합니다...
        </p>
      </Shell>
    );
  }

  const { preview: info } = preview;

  if (submit.status === "done") {
    return (
      <Shell>
        <h1 data-testid="join-done-heading" className="text-[21px] font-semibold">가입 완료</h1>
        <p data-testid="join-done-message" className="mt-3 text-[13.5px] leading-relaxed text-ink/60">
          {submit.className}에 &quot;{submit.displayName}&quot;(으)로 참여했습니다.
        </p>
        <p className="mt-6">
          <Link
            href={`/classes/${submit.classId}/problems/mine`}
            data-testid="join-done-problems-link"
            className={`${buttonClass("primary")} w-full`}
          >
            문제 목록 보러 가기
          </Link>
        </p>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="text-[11px] tracking-[0.08em] text-ink/45">초대받은 클래스</div>
      <h1 data-testid="join-preview-heading" className="mt-1.5 text-[21px] font-semibold leading-snug">
        {info.class_name}
      </h1>
      <p className="mt-2 flex flex-wrap items-center gap-x-1.5 text-[13px] text-ink/60">
        {info.instructor_display_name ? (
          <>
            <span data-testid="join-preview-instructor">강사 {info.instructor_display_name}</span>
            <span aria-hidden>·</span>
          </>
        ) : null}
        <span data-testid="join-preview-problem-count">
          문제 <Num>{info.problem_count}</Num>개
        </span>
        <span aria-hidden>·</span>
        <span data-testid="join-preview-participant-count">
          참여자 <Num>{info.participant_count}</Num>명
        </span>
      </p>
      <p className="mt-3 text-[13px] leading-relaxed text-ink/60">
        문제를 풀어 코드나 저장소를 내면 곧바로 채점되는 클래스입니다.
      </p>

      <div className="mt-6">
        {info.archived ? (
          // 보관된 클래스의 가입 링크는 "고장"이 아니라 "끝났다"로 읽혀야
          // 한다(#294 AC) — 죽은 링크(preview.status === "dead")와 달리
          // 미리보기는 그대로 보여주고, 가입 폼만 접는다.
          <Note>
            <span data-testid="join-preview-archived">
              이 클래스는 보관되어 더 이상 가입할 수 없습니다. 지난 기록은 참여자에게 그대로 남습니다.
            </span>
          </Note>
        ) : submit.status === "needsLogin" || me.status === "error" ? (
          // 로그인하지 않은 사람은 이름 칸을 아예 보지 않는다(#387 AC) — 적은
          // 이름이 로그인 왕복 사이에 사라지는 일 자체가 없다. `submit.status
          // === "needsLogin"`는 로그인된 채로 폼을 보다가 세션이 만료된
          // 경우의 대비로 남는다(#385 Further Notes).
          <div className="flex flex-col gap-3">
            <Note>
              <span data-testid="join-needs-login">
                가입하려면 먼저 로그인해야 합니다. 로그인하면 이 초대 링크로 자동으로 돌아옵니다.
              </span>
            </Note>
            <Link
              href={`/login?next=${encodeURIComponent(`/join/${code}`)}`}
              data-testid="join-login-link"
              className={`${buttonClass("primary")} w-full`}
            >
              로그인하러 가기
            </Link>
          </div>
        ) : me.status === "loading" ? (
          // `me`가 아직 로딩 중이면 이름 칸도 로그인 버튼도 보이지 않는다 —
          // 둘 중 무엇을 보여줄지 아직 모른다.
          <p data-testid="join-login-status-loading" className="text-[13.5px] text-ink/45">
            확인하는 중...
          </p>
        ) : (
          <Card className="p-4">
            <form onSubmit={handleSubmit} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="join-display-name">
                  <FieldLabel>이 클래스에서 불릴 이름</FieldLabel>
                </label>
                <input
                  id="join-display-name"
                  data-testid="join-display-name-input"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  required
                  className={INPUT_CLASS}
                />
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  강사에게 이 이름으로 보입니다. 계정 이름과 달라도 됩니다 —
                  회사 수업이나 스터디에서 다른 이름을 쓸 수 있습니다.
                </span>
              </div>
              <button
                type="submit"
                data-testid="join-submit"
                disabled={submit.status === "submitting" || displayName.trim() === ""}
                className={`${buttonClass("primary")} w-full`}
              >
                {submit.status === "submitting" ? "가입하는 중..." : "가입하기"}
              </button>
            </form>
          </Card>
        )}
      </div>

      {submit.status === "error" ? (
        <div className="mt-4">
          <ErrorNote>
            <span data-testid="join-error">{submit.message}</span>
          </ErrorNote>
        </div>
      ) : null}

      <p className="mt-8 border-t border-rule pt-4 text-[11.5px] leading-relaxed text-ink/45">
        가입하면 바로 문제 목록이 열립니다 — 본인확인도 결제도 없습니다.
      </p>
    </Shell>
  );
}

/** 폰 우선 — 좁은 화면에서 한 칸으로 흐르고, 넓어져도 읽기 폭을 넘기지 않는다. */
function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto w-full max-w-[440px] px-5 py-8">{children}</main>;
}
