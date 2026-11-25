"use client";

// 공개된 템플릿 한 줄 — 문제 편집의 「템플릿으로 공개」 패널과 클래스 설정의 공개 카드가 함께 쓴다(#1446).
// 내릴 수 있는 사람(공개한 사람)에게만 「내리기」가 있다. 그 밖의 강사에게는 누가 공개했는지만 보인다 —
// 눌러도 404 인 단추를 두지 않는다(규칙은 공개자만 내린다, `takedown_own_template`).
import Link from "next/link";
import type { Ref } from "react";

import { Badge, buttonClass } from "@/app/components/ui";
import type { LiveTemplate } from "@/lib/problem-templates/live-state";

export function LiveTemplateRow({
  template,
  hrefBase,
  testIdPrefix,
  linkRef,
  onTakedown,
  takingDown,
}: {
  template: NonNullable<LiveTemplate>;
  hrefBase: string;
  testIdPrefix: string;
  linkRef: Ref<HTMLAnchorElement>;
  onTakedown: () => void;
  takingDown: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      <span data-testid={`${testIdPrefix}-done`} className="self-start">
        <Badge tone="verified">공개됨</Badge>
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <Link
          ref={linkRef}
          href={`${hrefBase}/${template.shareCode}`}
          data-testid={`${testIdPrefix}-share-link`}
          className="min-w-0 flex-1 break-all border border-rule bg-paper px-3 py-2 font-mono text-[12.5px] hover:underline"
        >
          {hrefBase}/{template.shareCode}
        </Link>
        {template.canTakeDown ? (
          <button
            type="button"
            data-testid={`${testIdPrefix}-takedown`}
            onClick={onTakedown}
            disabled={takingDown}
            className={buttonClass("danger", "sm")}
          >
            {takingDown ? "내리는 중..." : "내리기"}
          </button>
        ) : null}
      </div>
      {template.canTakeDown ? null : (
        <p data-testid={`${testIdPrefix}-publisher`} className="text-[12.5px] text-ink/60">
          공개: {template.publisherDisplayName}
        </p>
      )}
    </div>
  );
}
