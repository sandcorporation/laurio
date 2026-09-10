// FE-06(#31) — 공개 SSR 개발자 프로필. REQUEST.md 가 약속한 「검색엔진에 색인되는
// 공개 URL」이 이 페이지다 — 순수 콘테스트라 탈락한 Developer 의 금전 보상은
// 0이고, 참가 이력이 플랫폼 밖에서 발견되는 자산으로 남는다는 약속 하나가
// 전부다(spec #25, ADR-0015). 이 약속이 지켜지려면 이 페이지가 서버에서
// 렌더링돼야 한다 — 그래서 app/contests/[id]/page.tsx 와 같은 패턴을 그대로
// 따른다: 서버 컴포넌트뿐이고, 클라이언트 컴포넌트 지시어를 붙이지 않는다.
//
// `GET /api/developers/{developer_id}/profile` 도 auth=None 공개 표면이다.
//
// 노출 금지 두 가지(ADR-0014) — 소스코드와 test_account 는 이 페이지 어디에도
// 없어야 한다. 이 페이지는 그 값을 "안 그린다"가 아니라 애초에 그 값을 모른다 —
// `DeveloperPublicProfileOut`/`PublicSubmissionOut` 스키마 자체에 그 필드가
// 없다(lib/api/developers.ts, backend/submissions/schemas.py). 그리고 이 트리에는
// 클라이언트 컴포넌트가 하나도 없으므로(아래 전부 서버 컴포넌트), Next 가
// 하이드레이션 payload 에 실어 보낼 props 자체가 없다 — "화면에 안 그렸다"보다
// 강한 보장이다.
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { fetchDeveloperProfile, type PublicSubmission } from "@/lib/api/developers";

type Params = { id: string };

function parseDeveloperId(raw: string): number | null {
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { id } = await params;
  const developerId = parseDeveloperId(id);
  const profile = developerId === null ? null : await fetchDeveloperProfile(developerId);

  if (!profile) {
    return { title: "개발자를 찾을 수 없습니다 — Laurio" };
  }

  const description =
    profile.bio.trim().length > 0
      ? profile.bio
      : `${profile.display_name}의 Laurio 참가 이력 — 아카이브된 제출작 ${profile.submissions.length}건`;

  // OG 이미지는 opengraph-image.tsx(같은 디렉터리)가 이 프로필 이름으로 매번
  // 새로 그려 자동으로 연결한다 — app/contests/[id]/page.tsx 와 같은 컨벤션.
  return {
    title: `${profile.display_name} — Laurio 개발자 프로필`,
    description,
    openGraph: {
      title: profile.display_name,
      description,
      type: "profile",
    },
  };
}

export default async function DeveloperProfilePage({ params }: { params: Promise<Params> }) {
  const { id } = await params;
  const developerId = parseDeveloperId(id);
  const profile = developerId === null ? null : await fetchDeveloperProfile(developerId);

  if (!profile) {
    notFound();
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 bg-paper p-10 text-ink">
      <header className="flex flex-col gap-3 border-b border-rule pb-6">
        <span className="text-xs tracking-wide text-ink/60">개발자 프로필</span>
        <h1 className="text-2xl font-semibold" data-testid="developer-display-name">
          {profile.display_name}
        </h1>
        {profile.bio && (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink/80">{profile.bio}</p>
        )}
      </header>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium">아카이브된 제출작</h2>
        <p className="text-xs text-ink/60">
          마감된 공모전에 낸 제출작만 보입니다. 소스코드는 저작권이 본인에게 남아 공개되지
          않습니다.
        </p>
        {profile.submissions.length === 0 ? (
          <p className="text-sm text-ink/60">마감된 공모전에 낸 제출작이 아직 없습니다.</p>
        ) : (
          <ul className="flex flex-col" data-testid="archived-submissions">
            {profile.submissions.map((submission) => (
              <ArchivedSubmissionRow key={submission.submission_id} submission={submission} />
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function ArchivedSubmissionRow({ submission }: { submission: PublicSubmission }) {
  const videos = submission.assets.filter(
    (asset) => asset.kind === "demo_video" && asset.download_url,
  );
  const screenshots = submission.assets.filter(
    (asset) => asset.kind === "screenshot" && asset.download_url,
  );

  return (
    <li
      className="flex flex-col gap-2 border-b border-rule py-3"
      data-testid="archived-submission"
      data-contest-id={submission.contest_id}
    >
      <a href={`/contests/${submission.contest_id}`} className="text-sm font-medium hover:underline">
        {submission.contest_title}
      </a>
      <span className="font-mono text-xs text-ink/60">
        {new Date(submission.created_at).toLocaleDateString("ko-KR")}
      </span>
      <div className="flex flex-wrap gap-2 text-xs">
        {/* 자료는 여럿일 수 있다(#190) — 데모마다 링크를 하나씩 낸다. 라벨이
            있으면 그것이 링크 이름이 된다(「모바일 앱 데모」). */}
        {submission.assets
          .filter((asset) => asset.kind === "demo_url")
          .map((asset) => (
            <a
              key={asset.id}
              href={asset.value}
              target="_blank"
              rel="noreferrer noopener"
              className="border border-verified px-1.5 py-0.5 text-verified"
              data-testid="demo-url-link"
            >
              {asset.label || "데모 보기"}
            </a>
          ))}
      </div>
      {/* #265 — 「시연 영상 N편 있음」이라고만 말하던 죽은 배지 대신, 실제로
          재생·열람할 수 있는 영상·스크린샷을 낸다(ADR-0036). `download_url`은
          백엔드가 이미 서명해 실어 보낸 것이라(`submissions.api.
          _public_asset_summaries`) 이 서버 컴포넌트가 별도 요청 없이 그대로
          렌더링한다 — JS를 꺼도 재생·열람이 가능하다. 라벨로 자료를 구별한다
          (영상 둘, 스크린샷 여럿이 나란히 선다). */}
      {(videos.length > 0 || screenshots.length > 0) && (
        <div className="flex flex-wrap gap-3">
          {videos.map((asset) => (
            <div key={asset.id} className="flex flex-col gap-1">
              <span className="text-xs text-ink/60">{asset.label || "시연 영상"}</span>
              <video
                controls
                preload="metadata"
                className="w-48 rounded-sm border border-rule"
                data-testid="demo-video-player"
              >
                <source src={asset.download_url!} />
              </video>
            </div>
          ))}
          {screenshots.map((asset) => (
            // eslint-disable-next-line @next/next/no-img-element -- presigned URL, Next Image 최적화 대상이 아니다
            <img
              key={asset.id}
              src={asset.download_url!}
              alt={asset.label || "스크린샷"}
              className="w-48 rounded-sm border border-rule"
              data-testid="screenshot-image"
            />
          ))}
        </div>
      )}
    </li>
  );
}
