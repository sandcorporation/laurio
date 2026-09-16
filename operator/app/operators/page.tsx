"use client";

// Operator 계정 관리 화면(#69, ADR-0018 — 골간으로 옮긴다, #426/#421). 상위
// 등급(is_superuser) 전용이다 — 「돈을 움직일 수 있다」와 「돈을 움직일 권한을
// 나눠줄 수 있다」는 무게가 다르기 때문이다(#45). 일반 Operator가 이 경로를
// 열면 403을 빈 목록이나 깨진 화면으로 보여주지 않고 "등급이 필요하다"고
// 명시적으로 말한다(lib/operators/use-operators.ts의 forbidden 상태) — 상위
// 등급만 할 수 있는 일이 등급에 따라 갈리는 것이 이 문구로 화면에 드러난다.
import { useRouter } from "next/navigation";

import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { CreateOperatorForm } from "@/lib/operators/create-operator-form";
import { OperatorRow } from "@/lib/operators/operator-row";
import { useOperators } from "@/lib/operators/use-operators";

const COL = {
  grade: "w-[96px]",
  active: "w-[80px]",
  action: "w-[160px]",
};

function TableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className="min-w-0 flex-1">아이디</div>
      <div className={`${COL.grade} shrink-0`}>등급</div>
      <div className={`${COL.active} shrink-0`}>활성 여부</div>
      <div className={`${COL.action} shrink-0`}>작업</div>
    </div>
  );
}

export default function OperatorsPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = useOperators(session.status === "authenticated");

  function handleSessionExpired() {
    router.replace("/login");
  }

  if (session.status === "unauthenticated") {
    // 이 검사가 loading 검사보다 먼저여야 한다(코드리뷰 지적). 세션이 죽으면
    // (쿠키는 남았지만 백엔드가 더 이상 인정하지 않으면) session.status는
    // "loading"을 거치지 않고 곧장 "unauthenticated"로 간다 — 그 시점에
    // enabled(=session.status === "authenticated")는 한 번도 true였던 적이
    // 없으므로 useOperators의 effect가 아예 실행되지 않고, state는 초기값인
    // "loading"에 영원히 머문다. 이 검사를 loading 검사 뒤에 두면 그 state가
    // 계속 "loading"이라는 이유만으로 화면이 스피너에 갇히고, useSession이
    // 이미 시작한 /login 리다이렉트가 이 화면 뒤로 가려진다. useSession이
    // 리다이렉트하는 중이므로 여기서는 아무것도 렌더하지 않는다
    // (operator/app/page.tsx와 같은 원칙).
    return null;
  }

  if (session.status === "loading" || state.status === "loading") {
    return (
      <div className="p-8">
        <p data-testid="operators-loading">불러오는 중...</p>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        crumb="운영 · 운영자 계정"
        title="운영자 계정 관리"
        description="상위 등급만 계정을 만들고 활성 여부를 바꿀 수 있습니다."
      />
      <div className="flex flex-1 flex-col gap-4 p-8">
        {state.status === "forbidden" && (
          <p role="alert" data-testid="operators-forbidden" className="text-[13px] text-ink/62">
            이 화면은 상위 등급 Operator만 볼 수 있습니다. 계정 관리에는 상위 등급 권한이
            필요합니다.
          </p>
        )}

        {state.status === "error" && (
          <p role="alert" data-testid="operators-error" className="text-[13px] text-attention">
            Operator 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
          </p>
        )}

        {state.status === "loaded" && (
          <>
            <CreateOperatorForm onCreated={reload} onSessionExpired={handleSessionExpired} />

            {state.operators.length === 0 ? (
              <p data-testid="operators-empty" className="text-[13px] text-ink/62">
                등록된 Operator가 없습니다.
              </p>
            ) : (
              <div data-testid="operators-table" className="border border-rule bg-surface">
                <TableHead />
                {state.operators.map((operator, i) => (
                  <OperatorRow
                    key={operator.id}
                    operator={operator}
                    zebra={i % 2 === 1}
                    onChanged={reload}
                    onSessionExpired={handleSessionExpired}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
