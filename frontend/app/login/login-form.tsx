"use client";

// 로그인 화면(ADR-0016, FE-07 #32, #95 spec #92). ADR-0015가 그은 경계 밖이다 —
// 이 페이지는 auth=None 백엔드 엔드포인트를 부르지 않고(호출할 세션이 아직
// 없다), 색인 대상도 아니다. 그래서 서버 컴포넌트로 남겨둘 이유가 없어 클라이언트
// 컴포넌트로 둔다.
//
// 이 화면은 두 경로를 같이 그린다(#95, #189):
//
// 1. **실물 제공자 버튼.** 셋 다 누르면 이 페이지를 떠나
//    `/api/auth/social/{provider}/authorize`로 top-level GET 이동한다(BFF가
//    OAuth를 진다, 클라이언트 JS가 토큰을 만지는 일이 없다) — 단, **그 제공자의
//    OAuth 앱 자격증명이 이 프로세스에 설정돼 있을 때만.** 백엔드 어댑터
//    (accounts/social.py)는 카카오·GitHub·구글 셋 다 이미 실물 구현이 있지만,
//    GitHub·구글의 client_id/secret은 아직 어느 환경에도 등록돼 있지 않다
//    (#189 — 그 등록은 사람이 벤더 콘솔에서 하는 일이다). `githubConfigured`/
//    `googleConfigured`(app/login/page.tsx가 lib/auth/github·google.ts의
//    readGithubOAuthConfig/readGoogleOAuthConfig로 판정해 내려준다 — authorize
//    라우트가 실제로 쓰는 것과 정확히 같은 기준)가 false인 동안은 눌러도 아무
//    데도 안 가는 버튼을 두지 않기 위해 비활성 "준비 중"으로 그린다. 값이
//    true가 되는 순간(사람이 자격증명을 채우고 배포하는 순간) 이 컴포넌트를
//    다시 고치지 않아도 같은 자리가 실제 링크로 바뀐다 — 카카오는 처음부터
//    이 조건이 필요 없었다(dev부터 자격증명 유무와 무관하게 링크로 두고,
//    미설정이면 authorize 라우트 자신이 우리 문구로 돌려보낸다, #96)이므로
//    그 동작은 그대로 둔다.
// 2. **dev seed 폼.** SOCIAL_AUTH_MODE=fake(dev/test 기본값)는 access_token을
//    "<식별자>:<이메일>" 형식 문자열로 그대로 신뢰한다(accounts/social.py
//    FakeSocialAdapter) — 그 형식에 맞는 결정적인 토큰을 만들어 곧바로 POST한다.
//    기존 e2e 119건이 이 폼(`fake-login-seed`·`login-kakao` 등 테스트 id)으로
//    로그인하므로 여기는 손대지 않는다. `showDevSeedForm`이 false면(배포 환경,
//    app/login/page.tsx가 서버에서 판정) 이 절 자체가 렌더되지 않는다 — 배포
//    환경에 로그인 우회가 실려 나가는 것이 막는 값이다(#95).
import { Suspense, useState } from "react";
import { normalizeDetail } from "@laurio/bff-client";
import { useRouter, useSearchParams } from "next/navigation";

import { resolveNextPath } from "@/lib/auth/next-path";
import type { SocialProvider } from "@/lib/auth/social-providers";

const DEV_SEED_PROVIDERS = [
  { id: "kakao", label: "카카오로 로그인" },
  { id: "github", label: "GitHub으로 로그인" },
  { id: "google", label: "Google로 로그인" },
] as const;

type DevSeedProviderId = (typeof DEV_SEED_PROVIDERS)[number]["id"];

// 콜백(app/api/auth/social/[provider]/callback/route.ts)과 authorize
// (app/api/auth/social/[provider]/authorize/route.ts)가 ?error=로 실어 보내는
// 코드를 사람이 읽을 문구로 옮긴다 — "빈 화면이 아니라 이유가 보인다"는
// 인수조건. 이 코드는 어느 provider에서 났는지를 싣지 않으므로(next 목적지가
// provider 종류와 무관하게 같은 자리로 돌아온다) 문구도 특정 제공자 이름을
// 박지 않는다(#189 — 예전에는 카카오 전용이라 "카카오"를 하드코딩했다).
const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  oauth_unconfigured: "이 로그인 방식은 이 환경에서 아직 설정되지 않았습니다.",
  invalid_state: "로그인 세션이 만료되었거나 올바르지 않습니다. 다시 시도해주세요.",
  provider_denied: "로그인이 취소되었거나 거부되었습니다.",
  login_failed: "로그인에 실패했습니다. 다시 시도해주세요.",
};

function describeOAuthError(code: string | null): string | null {
  if (!code) return null;
  return OAUTH_ERROR_MESSAGES[code] ?? "로그인에 실패했습니다.";
}

interface LoginButtonsProps {
  showDevSeedForm: boolean;
  githubConfigured: boolean;
  googleConfigured: boolean;
}

// 카카오는 자격증명 유무와 무관하게 항상 실물 링크다(#96) — authorize 라우트
// 자신이 미설정 상태를 처리한다. GitHub·구글은 설정 여부로 링크/비활성을
// 가른다(#189).
interface OAuthButtonSpec {
  provider: SocialProvider;
  label: string;
  configured: boolean;
}

function LoginButtons({ showDevSeedForm, githubConfigured, googleConfigured }: LoginButtonsProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  // 같은 오리진 경로가 아니면 기본값으로 떨어진다(오픈 리다이렉트 방어) —
  // authorize 라우트가 이 값을 다시 한번 같은 규칙으로 검증한다.
  const next = resolveNextPath(searchParams.get("next"));
  const oauthError = describeOAuthError(searchParams.get("error"));

  const [seed, setSeed] = useState("dev-user");
  const [pending, setPending] = useState<DevSeedProviderId | null>(null);
  const [devSeedError, setDevSeedError] = useState<string | null>(null);

  async function handleDevSeedLogin(provider: DevSeedProviderId) {
    setDevSeedError(null);
    setPending(provider);
    try {
      const accessToken = `${seed}:${seed}@example.test`;
      const res = await fetch(`/api/auth/social/${provider}/login`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ access_token: accessToken }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
        setDevSeedError(normalizeDetail(body?.detail, `로그인에 실패했습니다 (${res.status})`));
        return;
      }

      router.replace(next);
      router.refresh();
    } catch {
      setDevSeedError("로그인 요청을 보내지 못했습니다. 네트워크를 확인해주세요.");
    } finally {
      setPending(null);
    }
  }

  const displayedError = devSeedError ?? oauthError;

  const oauthButtons: OAuthButtonSpec[] = [
    { provider: "kakao", label: "카카오로 로그인", configured: true },
    { provider: "github", label: "GitHub으로 로그인", configured: githubConfigured },
    { provider: "google", label: "Google로 로그인", configured: googleConfigured },
  ];

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 bg-paper p-10">
      <div className="flex w-full max-w-sm flex-col gap-6 rounded-md border border-rule bg-surface p-8">
        <div>
          <h1 className="text-2xl font-semibold">로그인</h1>
        </div>

        <div className="flex flex-col gap-3">
          {oauthButtons.map(({ provider, label, configured }) =>
            configured ? (
              <a
                key={provider}
                href={`/api/auth/social/${provider}/authorize?next=${encodeURIComponent(next)}`}
                data-testid={`oauth-login-${provider}`}
                className="rounded-sm border border-ink px-4 py-2 text-center text-sm font-medium hover:bg-ink hover:text-paper"
              >
                {label}
              </a>
            ) : (
              <button
                key={provider}
                type="button"
                disabled
                aria-disabled="true"
                data-testid={`oauth-login-${provider}`}
                className="cursor-not-allowed rounded-sm border border-rule px-4 py-2 text-sm text-ink/50"
              >
                {label} (준비 중)
              </button>
            ),
          )}
        </div>

        {displayedError && (
          <p role="alert" data-testid="login-error" className="text-sm text-attention">
            {displayedError}
          </p>
        )}

        {showDevSeedForm && (
          <div className="flex flex-col gap-3 border-t border-rule pt-6" data-testid="dev-seed-login">
            <p className="text-sm text-ink">
              dev 환경은 소셜 제공자 대신 결정적인 fake 어댑터로 로그인합니다.
            </p>

            <label className="flex flex-col gap-1 text-sm">
              테스트 계정 식별자
              <input
                className="rounded-sm border border-rule bg-paper px-2 py-1 font-mono"
                value={seed}
                onChange={(event) => setSeed(event.target.value)}
                data-testid="fake-login-seed"
              />
            </label>

            <div className="flex flex-col gap-3">
              {DEV_SEED_PROVIDERS.map((provider) => (
                <button
                  key={provider.id}
                  type="button"
                  onClick={() => handleDevSeedLogin(provider.id)}
                  disabled={pending !== null}
                  data-testid={`login-${provider.id}`}
                  className="rounded-sm border border-rule px-4 py-2 text-sm hover:border-ink disabled:opacity-50"
                >
                  {pending === provider.id ? "로그인 중..." : provider.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

export default function LoginForm({
  showDevSeedForm,
  githubConfigured,
  googleConfigured,
}: LoginButtonsProps) {
  return (
    <Suspense fallback={null}>
      <LoginButtons
        showDevSeedForm={showDevSeedForm}
        githubConfigured={githubConfigured}
        googleConfigured={googleConfigured}
      />
    </Suspense>
  );
}
