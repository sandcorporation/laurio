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
  Card,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  Num,
  buttonClass,
} from "@/app/components/ui";
import { useMe } from "@/lib/auth/use-me";
import { joinClass } from "@/lib/join/api";
import { useJoinPreview } from "@/lib/join/use-join-preview";
import { checkDisplayNameForBannedWords } from "@/lib/members/display-name-check";

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "error"; message: string };

export function JoinView() {
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
    const trimmedName = displayName.trim();
    // 제출을 누르는 순간에만 검사한다 — 타이핑 중에는 부르지 않는다(spec
    // #474, #476). 서버가 진짜 문이고(#475) 이건 편의라, 여기서 걸러도
    // 걸러지지 않아도 서버가 같은 이유로 다시 거절한다.
    const bannedWordMessage = checkDisplayNameForBannedWords(trimmedName);
    if (bannedWordMessage) {
      setSubmit({ status: "error", message: bannedWordMessage });
      return;
    }
    setSubmit({ status: "submitting" });
    // 세션이 죽은 채로 보내면 `bffClient`가 공개 앱 로그인으로 보낸다(#462) —
    // 조회든 변경이든 401은 항상 같은 경로다. 그 사이 잠깐 아래 실패
    // 문구가 보일 수 있지만 곧 이동이 이어진다.
    const result = await joinClass(code, trimmedName);
    if (result.ok) {
      // 버튼이 「가입하고 문제 보기」라 말한 대로 곧장 문제 목록이다(#658) — 중간
      // 「가입 완료」 화면을 두지 않는다. 이동이 끝날 때까지 버튼은 「submitting」
      // 그대로 잠겨 두 번째 가입 요청이 나가지 않는다.
      router.replace(`/classes/${result.data.class_id}/problems/mine`);
    } else {
      setSubmit({ status: "error", message: result.detail });
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
  // 강사 전원의 이름(#565) — 소유자 먼저. 이 칸을 모르는 옛 백엔드면 소유자의 이름 하나로 읽는다.
  const instructorNames =
    info.instructor_display_names ?? (info.instructor_display_name ? [info.instructor_display_name] : []);

  return (
    <Shell>
      <div className="flex flex-col gap-2">
        <div className="text-[11px] tracking-[0.08em] text-ink/45">초대받은 클래스</div>
        <h1 data-testid="join-preview-heading" className="text-[24px] font-semibold leading-[1.3] tracking-[-0.01em]">
          {info.class_name}
        </h1>
        <p className="flex flex-wrap items-center gap-x-[18px] gap-y-1 text-[13px] text-ink/60">
          {instructorNames.length > 0 ? (
            <span data-testid="join-preview-instructor">강사 {instructorNames.join(", ")}</span>
          ) : null}
          <span data-testid="join-preview-problem-count">
            <Num className="font-semibold text-ink">{info.open_problem_count}</Num> 문제
          </span>
          <span data-testid="join-preview-member-count">
            <Num className="font-semibold text-ink">{info.member_count}</Num> 참여자
          </span>
        </p>
      </div>

      {info.archived ? (
        // 보관된 클래스의 가입 링크는 "고장"이 아니라 "끝났다"로 읽혀야
        // 한다(#294 AC) — 죽은 링크(preview.status === "dead")와 달리
        // 미리보기는 그대로 보여주고, 가입 폼만 접는다.
        <Note>
          <span data-testid="join-preview-archived">
            이 클래스는 보관되어 더 이상 가입할 수 없습니다. 지난 기록은 참여자에게 그대로 남습니다.
          </span>
        </Note>
      ) : me.status === "error" ? (
        // 로그인하지 않은 사람은 이름 칸을 아예 보지 않는다(#387 AC) — 적은
        // 이름이 로그인 왕복 사이에 사라지는 일 자체가 없다. 로그인된 채로
        // 폼을 보다가 세션이 만료되면 제출 시 `bffClient`가 곧장 공개 앱
        // 로그인으로 보낸다(#462, #385 Further Notes).
        <Card className="p-5">
          <Link
            href={`/login?next=${encodeURIComponent(`/join/${code}`)}`}
            data-testid="join-login-link"
            className={`${buttonClass("primary")} w-full`}
          >
            로그인하고 가입하기
          </Link>
        </Card>
      ) : me.status === "loading" ? (
        // `me`가 아직 로딩 중이면 이름 칸도 로그인 버튼도 보이지 않는다 —
        // 둘 중 무엇을 보여줄지 아직 모른다.
        <p data-testid="join-login-status-loading" className="text-[13.5px] text-ink/45">
          확인하는 중...
        </p>
      ) : (
        <Card className="p-5">
          <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
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
            </div>
            <button
              type="submit"
              data-testid="join-submit"
              disabled={submit.status === "submitting" || displayName.trim() === ""}
              className={`${buttonClass("primary")} w-full sm:w-auto sm:self-start`}
            >
              {submit.status === "submitting" ? "가입하는 중..." : "가입하고 문제 보기"}
            </button>
          </form>
        </Card>
      )}

      {submit.status === "error" ? (
        <ErrorNote>
          <span data-testid="join-error">{submit.message}</span>
        </ErrorNote>
      ) : null}
    </Shell>
  );
}

/** 폰 우선 — 좁은 화면에서 한 칸으로 흐르고, 넓어져도 읽기 폭을 넘기지 않는다. */
function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto flex w-full max-w-[440px] flex-col gap-7 px-5 py-12">{children}</main>;
}
