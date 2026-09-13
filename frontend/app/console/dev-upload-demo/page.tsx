"use client";

// presigned 업로드(FE-09, #34)의 인수조건 증명용 화면이다. FE-10(#35)의 제출
// 폼이 실제 제품 화면에서 components/upload/upload-field.tsx를 그대로 쓰므로,
// 이 페이지 자체는 별도 제품 기능이 아니라 "파일 바이트가 Next를 거치지
// 않는다"를 브라우저 네트워크 관찰로 검증할 수 있는 최소 표면이다.
//
// target_ref 형식(submissions/target_refs.py): "submission:<contest_id>:<user_id>:source".
// storage.policy가 이 문자열을 파싱해 소유자를 판정하므로(submissions/resolvers.py),
// 실존하는 Contest id와 로그인한 본인의 user id가 있어야 업로드 권한이 선다.
import { useState } from "react";

import { INPUT_CLASS, PageHeader, PageShell } from "@/app/components/ui";
import { UploadField } from "@/components/upload/upload-field";
import { useSession } from "@/lib/auth/use-session";

export default function UploadDemoPage() {
  const session = useSession();
  const [contestId, setContestId] = useState("");
  const [uploadedKey, setUploadedKey] = useState<string | null>(null);

  if (session.status !== "authenticated") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="session-loading">불러오는 중...</p>
      </main>
    );
  }

  const targetRef = contestId.trim()
    ? `submission:${contestId.trim()}:${session.user.id}:source`
    : null;

  return (
    <PageShell>
      <PageHeader title="presigned 업로드 데모" />

      <label className="flex flex-col gap-1 text-sm">
        공모전 ID
        <input
          className={`w-40 ${INPUT_CLASS} font-mono`}
          value={contestId}
          onChange={(event) => setContestId(event.target.value)}
          data-testid="upload-demo-contest-id"
        />
      </label>

      {targetRef && (
        <UploadField
          targetRef={targetRef}
          label="소스코드"
          testId="source-upload"
          onUploaded={setUploadedKey}
        />
      )}

      {uploadedKey && (
        <p data-testid="upload-demo-object-key" className="font-mono text-sm">
          {uploadedKey}
        </p>
      )}
    </PageShell>
  );
}
