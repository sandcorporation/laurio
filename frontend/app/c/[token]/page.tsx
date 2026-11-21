// 상장 확인 페이지(#1128, 스펙 #1071 「확인 페이지 상태 셋」) — 상장의 QR 이 가리키는 곳.
//
// 로그인 없이 서버에서 그린다. 검색에는 싣지 않는다: 메타 robots·`X-Robots-Tag`
// (next.config.ts)·robots.txt 의 `/c/` 막기, 사이트맵에도 없다. 없는 토큰만 404 이고,
// 받는 사람이 닫은 상장도 「있다」는 사실은 숨기지 않는다(번호만 보인다).
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Badge, PageShell } from "@/app/components/ui";
import { fetchCertificateVerification } from "@/lib/api/certificates";
import { describeVerification } from "@/lib/certificates/verify";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "상장 확인",
  robots: { index: false, follow: false },
};

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{1,32}$/;

export default async function CertificateVerifyPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const verification = TOKEN_PATTERN.test(token) ? await fetchCertificateVerification(token) : null;

  if (!verification) {
    notFound();
  }

  const view = describeVerification(verification);

  return (
    <PageShell>
      <section className="mx-auto flex max-w-xl flex-col gap-6" data-testid="certificate-verify">
        <h1 className="sr-only">상장 확인</h1>
        <div>
          <Badge tone={view.tone === "valid" ? "verified" : "attention"}>
            <span className="text-sm font-bold" data-testid="certificate-verify-state">
              {view.stateLabel}
            </span>
          </Badge>
        </div>
        <dl className="grid grid-cols-[7em_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-sm">
          {view.rows.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-ink/60">{row.label}</dt>
              <dd className={`break-words ${row.mono ? "font-mono text-[13px]" : ""}`}>{row.value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </PageShell>
  );
}
