"use client";

// 콘솔의 "내 정보" 화면 (#228) — 표시 이름 · 소개를 역할별로 보고 고친다.
//
// **백엔드는 이미 있다.** `POST /api/accounts/sponsor-profile`·
// `.../developer-profile`가 부분 수정을 이미 지원한다(`accounts.api.
// _apply_profile_update`) — payload 필드가 `None`(안 보냄)이면 손대지 않고,
// `""`(명시적으로 비움)이면 지운다. 프로필 행은 저장 시점에 지연 생성된다
// (`get_or_create`).
//
// **읽기 전용 GET이 없다 — 그리고 이 티켓은 백엔드를 바꾸지 않는다.** 그래서
// 이 화면은 그 두 POST를 빈 payload(`{}`)로 불러 "현재 값을 읽는다"를 얻는다:
// 필드가 전부 `None`이면 `_apply_profile_update`가 아무것도 바꾸지 않고 현재
// 값을 그대로 돌려주고(save조차 하지 않는다, `changed=False`), 프로필이 아직
// 없으면 `get_or_create`가 빈 문자열 두 개짜리 행을 만들어 돌려준다 — 그 자체가
// AC("아직 그 역할의 프로필이 없어도 저장하면 만들어진다")가 요구하는 동작이다.
//
// **실명·생년월일·연락처는 여기 없다.** 그 값은 Verification이 채우고
// Authentication과는 무관하다(`accounts/api.py` 모듈 독스트링) — 이 화면이
// 다루는 건 사용자가 스스로 정하는 표시 이름·소개뿐이다.
//
// **저장한 값은 다른 화면에서 그대로 나타난다** — 공개 개발자 프로필
// (`GET /submissions/developers/{id}`, `submissions.api`)과 Sponsor의 심사
// 비교 화면(`ContestComparisonOut.developer_display_name`)이 전부 이
// `DeveloperProfile.display_name`을 그대로 읽으므로, 새 화면은 그 두 곳을
// 다시 구현하지 않는다 — 값을 저장하는 자리 하나를 더할 뿐이다.
//
// **`returnOrigin`은 강의실에서 건너온 사람에게만 있다**(#307). 서버 컴포넌트인
// `page.tsx`가 `?from_origin=`을 `resolveSiblingOrigin`으로 검증해 우리 형제
// 오리진일 때만 이 값을 채워 넘긴다 — 여기서는 그 결과를 그대로 믿고 그린다,
// 다시 검증하지 않는다.
import { useEffect, useState } from "react";
import Link from "next/link";

import { ErrorNote, INPUT_CLASS, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";

type ProfileOut = { display_name: string; bio: string };

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; display_name: string; bio: string };

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "success" }
  | { status: "error"; message: string };

type Role = "sponsor" | "developer";

const ROLE_COPY: Record<Role, { title: string; description: string; path: string }> = {
  sponsor: {
    title: "개최자 표시 이름 · 소개",
    description: "공모전을 열고 심사할 때 참가자에게 보이는 이름입니다.",
    path: "sponsor-profile",
  },
  developer: {
    title: "참가자 표시 이름 · 소개",
    description:
      "공개 개발자 프로필과 제출물에서 보이는 이름입니다. 비워두면 참가자#{id}로 보입니다.",
    path: "developer-profile",
  },
};

export function ProfilePageClient({ returnOrigin }: { returnOrigin: string | null }) {
  const session = useSession();

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="profile-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <PageShell>
      <div className="flex items-center justify-between gap-3">
        <Link className="text-sm text-ink/60" href="/console" data-testid="profile-back">
          ← 콘솔
        </Link>
        {returnOrigin && (
          <a
            className="text-sm text-ink/60"
            href={returnOrigin}
            data-testid="profile-return-to-classroom"
          >
            강의실로 돌아가기 →
          </a>
        )}
      </div>
      <PageHeader
        title="내 정보"
        titleTestId="profile-heading"
        description="표시 이름과 소개는 개최자·참가자 역할마다 따로 저장됩니다. 실명·생년월일·연락처 같은 본인확인 정보는 여기서 다루지 않습니다."
      />

      <RoleSection role="sponsor" />
      <RoleSection role="developer" />
    </PageShell>
  );
}

function RoleSection({ role }: { role: Role }) {
  const copy = ROLE_COPY[role];
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [save, setSave] = useState<SaveState>({ status: "idle" });

  useEffect(() => {
    let cancelled = false;
    // 빈 payload — 아무 필드도 안 보내 "읽기만" 한다(위 파일 독스트링).
    bffClient.post<ProfileOut>(`/api/backend/accounts/${copy.path}`, {}).then((res) => {
      if (cancelled) return;
      if (res.ok) {
        setLoad({ status: "ready", display_name: res.data.display_name, bio: res.data.bio });
        setDisplayName(res.data.display_name);
        setBio(res.data.bio);
      } else {
        setLoad({ status: "error" });
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [copy.path]);

  async function handleSave() {
    if (save.status === "saving") return; // 중복 클릭 방지 — 버튼도 disabled 지만 방어로 한 번 더.
    setSave({ status: "saving" });
    const result = await bffClient.post<ProfileOut>(`/api/backend/accounts/${copy.path}`, {
      display_name: displayName,
      bio,
    });
    if (!result.ok) {
      setSave({ status: "error", message: result.detail });
      return;
    }
    setLoad({ status: "ready", display_name: result.data.display_name, bio: result.data.bio });
    setDisplayName(result.data.display_name);
    setBio(result.data.bio);
    // "success"로 남긴다("idle"이 아니라) — 빈 값으로 저장했을 때 화면이 저장 전과
    // 똑같아 보이는 문제(#239)가 바로 이 상태가 메우는 자리다. 다음 입력 수정이
    // 오면(아래 onChange) 다시 idle로 돌려 낡은 성공 표시가 새 편집을 가리지 않게 한다.
    setSave({ status: "success" });
  }

  function handleFieldChange<T>(setField: (value: T) => void) {
    return (value: T) => {
      setField(value);
      // 성공 표시가 뜬 채로 사용자가 다시 고치기 시작하면 그 표시는 이미 낡은 정보다
      // (AC: "성공 표시가 다음 편집을 방해하지 않는다").
      setSave((current) => (current.status === "success" ? { status: "idle" } : current));
    };
  }

  return (
    <section className="mt-8 border-t border-rule pt-6" data-testid={`profile-${role}-section`}>
      <h2 className="text-lg font-semibold">{copy.title}</h2>
      <p className="mt-1 text-sm text-ink/60">{copy.description}</p>

      {load.status === "loading" ? (
        <p className="mt-4 text-sm text-ink/60" data-testid={`profile-${role}-loading`}>
          불러오는 중...
        </p>
      ) : load.status === "error" ? (
        <div className="mt-4">
          <ErrorNote>
            <span data-testid={`profile-${role}-load-error`}>
              불러오지 못했습니다. 잠시 후 다시 시도해주세요.
            </span>
          </ErrorNote>
        </div>
      ) : (
        <>
          <label className="mt-4 flex flex-col gap-1 text-sm" htmlFor={`${role}-display-name`}>
            표시 이름
            <input
              id={`${role}-display-name`}
              type="text"
              value={displayName}
              onChange={(event) => handleFieldChange(setDisplayName)(event.target.value)}
              maxLength={100}
              data-testid={`profile-${role}-display-name-input`}
              className={INPUT_CLASS}
            />
          </label>

          <label className="mt-3 flex flex-col gap-1 text-sm" htmlFor={`${role}-bio`}>
            소개
            <textarea
              id={`${role}-bio`}
              value={bio}
              onChange={(event) => handleFieldChange(setBio)(event.target.value)}
              rows={3}
              data-testid={`profile-${role}-bio-input`}
              className={INPUT_CLASS}
            />
          </label>

          {save.status === "error" && (
            <div className="mt-2">
              <ErrorNote>
                <span data-testid={`profile-${role}-save-error`}>{save.message}</span>
              </ErrorNote>
            </div>
          )}

          {save.status === "success" && (
            <p className="mt-2 text-sm text-ink" role="status" data-testid={`profile-${role}-save-success`}>
              {copy.title} 저장했습니다.
            </p>
          )}

          <button
            type="button"
            onClick={handleSave}
            disabled={save.status === "saving"}
            data-testid={`profile-${role}-save`}
            className={`mt-4 ${buttonClass("primary")}`}
          >
            {save.status === "saving" ? "저장 중..." : "저장"}
          </button>
        </>
      )}
    </section>
  );
}
