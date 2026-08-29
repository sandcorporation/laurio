"use client";

// 로그인 화면(ADR-0016, FE-07 #32). ADR-0015가 그은 경계 밖이다 — 이 페이지는
// auth=None 백엔드 엔드포인트를 부르지 않고(호출할 세션이 아직 없다), 색인
// 대상도 아니다. 그래서 서버 컴포넌트로 남겨둘 이유가 없어 클라이언트
// 컴포넌트로 둔다.
//
// dev/test는 소셜 제공자 실제 연동이 불가능하다(카카오·GitHub·구글 계정으로
// 브라우저를 통과시킬 수 없다). 백엔드의 SOCIAL_AUTH_MODE=fake(기본값, dev/test)는
// access_token을 "<식별자>:<이메일>" 형식 문자열로 그대로 신뢰하므로
// (accounts/social.py FakeSocialAdapter), 여기서는 그 형식에 맞는 결정적인
// 토큰을 만들어 세 버튼 모두 실제로 로그인이 끝까지 되는 것을 증명한다.
// SOCIAL_AUTH_MODE=real인 배포(staging/prod)에서는 이 자리에 실제 OAuth authorize
// 리다이렉트가 들어가야 한다 — 그건 이 티켓 범위 밖이고(#23이 배포 환경을 갈랐고,
// 실제 제공자 자격증명 발급은 별도 운영 작업이다), 지금 이 폼은 백엔드가 어떤
// 어댑터를 쓰든 상관없이 "access_token 문자열을 얻어 POST 한다"는 동일한 계약을
// 지킨다.
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

const PROVIDERS = [
  { id: "kakao", label: "카카오로 로그인" },
  { id: "github", label: "GitHub으로 로그인" },
  { id: "google", label: "Google로 로그인" },
] as const;

type ProviderId = (typeof PROVIDERS)[number]["id"];

function LoginButtons() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "/console";

  const [seed, setSeed] = useState("dev-user");
  const [pending, setPending] = useState<ProviderId | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleLogin(provider: ProviderId) {
    setError(null);
    setPending(provider);
    try {
      const accessToken = `${seed}:${seed}@example.test`;
      const res = await fetch(`/api/auth/social/${provider}/login`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ access_token: accessToken }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setError(body?.detail ?? `로그인에 실패했습니다 (${res.status})`);
        return;
      }

      router.replace(next);
      router.refresh();
    } catch {
      setError("로그인 요청을 보내지 못했습니다. 네트워크를 확인해주세요.");
    } finally {
      setPending(null);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 bg-paper p-10">
      <div className="flex w-full max-w-sm flex-col gap-6 rounded-md border border-rule bg-surface p-8">
        <div>
          <h1 className="text-2xl font-semibold">로그인</h1>
          <p className="mt-2 text-sm text-ink">
            dev 환경은 소셜 제공자 대신 결정적인 fake 어댑터로 로그인합니다.
          </p>
        </div>

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
          {PROVIDERS.map((provider) => (
            <button
              key={provider.id}
              type="button"
              onClick={() => handleLogin(provider.id)}
              disabled={pending !== null}
              data-testid={`login-${provider.id}`}
              className="rounded-sm border border-rule px-4 py-2 text-sm hover:border-ink disabled:opacity-50"
            >
              {pending === provider.id ? "로그인 중..." : provider.label}
            </button>
          ))}
        </div>

        {error && (
          <p role="alert" data-testid="login-error" className="text-sm text-attention">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}

export default function LoginForm() {
  return (
    <Suspense fallback={null}>
      <LoginButtons />
    </Suspense>
  );
}
