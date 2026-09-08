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
import { useEffect, useState } from "react";
import Link from "next/link";

import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";

type ProfileOut = { display_name: string; bio: string };

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; display_name: string; bio: string };

type SaveState = { status: "idle" } | { status: "saving" } | { status: "error"; message: string };

type Role = "sponsor" | "developer";

const ROLE_COPY: Record<Role, { title: string; description: string; path: string }> = {
  sponsor: {
    title: "Sponsor 표시 이름 · 소개",
    description: "공모전을 열고 심사할 때 참가자에게 보이는 이름입니다.",
    path: "sponsor-profile",
  },
  developer: {
    title: "Developer 표시 이름 · 소개",
    description:
      "공개 개발자 프로필과 제출물에서 보이는 이름입니다. 비워두면 Developer#{id}로 보입니다.",
    path: "developer-profile",
  },
};

export default function ProfilePage() {
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
    <main className="mx-auto max-w-2xl p-10">
      <Link className="text-sm text-muted" href="/console" data-testid="profile-back">
        ← 콘솔
      </Link>
      <h1 className="mt-2 text-2xl font-semibold" data-testid="profile-heading">
        내 정보
      </h1>
      <p className="mt-2 text-sm text-muted">
        표시 이름과 소개는 Sponsor·Developer 역할마다 따로 저장됩니다. 실명·생년월일·연락처 같은
        본인확인 정보는 여기서 다루지 않습니다.
      </p>

      <RoleSection role="sponsor" />
      <RoleSection role="developer" />
    </main>
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
    setSave({ status: "idle" });
  }

  return (
    <section className="mt-8 border-t border-rule pt-6" data-testid={`profile-${role}-section`}>
      <h2 className="text-lg font-semibold">{copy.title}</h2>
      <p className="mt-1 text-sm text-muted">{copy.description}</p>

      {load.status === "loading" ? (
        <p className="mt-4 text-sm text-muted" data-testid={`profile-${role}-loading`}>
          불러오는 중...
        </p>
      ) : load.status === "error" ? (
        <p className="mt-4 text-sm text-attention" data-testid={`profile-${role}-load-error`}>
          불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      ) : (
        <>
          <label className="mt-4 flex flex-col gap-1 text-sm" htmlFor={`${role}-display-name`}>
            표시 이름
            <input
              id={`${role}-display-name`}
              type="text"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              maxLength={100}
              data-testid={`profile-${role}-display-name-input`}
              className="rounded-sm border border-rule px-3 py-2"
            />
          </label>

          <label className="mt-3 flex flex-col gap-1 text-sm" htmlFor={`${role}-bio`}>
            소개
            <textarea
              id={`${role}-bio`}
              value={bio}
              onChange={(event) => setBio(event.target.value)}
              rows={3}
              data-testid={`profile-${role}-bio-input`}
              className="rounded-sm border border-rule px-3 py-2"
            />
          </label>

          {save.status === "error" && (
            <p className="mt-2 text-sm text-attention" data-testid={`profile-${role}-save-error`}>
              {save.message}
            </p>
          )}

          <button
            type="button"
            onClick={handleSave}
            disabled={save.status === "saving"}
            data-testid={`profile-${role}-save`}
            className="mt-4 rounded-sm border border-ink bg-ink px-4 py-2 text-sm text-paper hover:bg-ink/90 disabled:opacity-50"
          >
            {save.status === "saving" ? "저장 중..." : "저장"}
          </button>
        </>
      )}
    </section>
  );
}
