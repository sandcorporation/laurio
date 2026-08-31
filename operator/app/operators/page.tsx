"use client";

// Operator 계정 관리 화면(#69, ADR-0018). 상위 등급(is_superuser) 전용이다 —
// 「돈을 움직일 수 있다」와 「돈을 움직일 권한을 나눠줄 수 있다」는 무게가
// 다르기 때문이다(#45). 일반 Operator가 이 경로를 열면 403을 빈 목록이나 깨진
// 화면으로 보여주지 않고 "등급이 필요하다"고 명시적으로 말한다
// (lib/operators/use-operators.ts의 forbidden 상태).
import { useRouter } from "next/navigation";

import { useSession } from "@/lib/auth/use-session";
import { CreateOperatorForm } from "@/lib/operators/create-operator-form";
import { OperatorRow } from "@/lib/operators/operator-row";
import { useOperators } from "@/lib/operators/use-operators";

export default function OperatorsPage() {
  const session = useSession();
  const router = useRouter();
  const { state, reload } = useOperators(session.status === "authenticated");

  function handleSessionExpired() {
    router.replace("/login");
  }

  if (session.status === "loading" || state.status === "loading") {
    return (
      <main>
        <p data-testid="operators-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") {
    // useSession이 이미 /login으로 보내는 중이다 — 리다이렉트가 붙기 전 한
    // 프레임 동안 보호된 내용이 그려지지 않도록 여기서 아무것도 렌더하지 않는다
    // (operator/app/page.tsx와 같은 원칙).
    return null;
  }

  return (
    <main>
      <h1 data-testid="operators-heading">Operator 계정 관리</h1>

      {state.status === "forbidden" && (
        <p role="alert" data-testid="operators-forbidden">
          이 화면은 상위 등급 Operator만 볼 수 있습니다. 계정 관리에는 상위 등급 권한이
          필요합니다.
        </p>
      )}

      {state.status === "error" && (
        <p role="alert" data-testid="operators-error">
          Operator 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {state.status === "loaded" && (
        <>
          <CreateOperatorForm onCreated={reload} onSessionExpired={handleSessionExpired} />

          <table data-testid="operators-table">
            <thead>
              <tr>
                <th>아이디</th>
                <th>등급</th>
                <th>활성 여부</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {state.operators.map((operator) => (
                <OperatorRow
                  key={operator.id}
                  operator={operator}
                  onChanged={reload}
                  onSessionExpired={handleSessionExpired}
                />
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
