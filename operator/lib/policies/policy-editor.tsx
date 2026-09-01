"use client";

// 정책 편집 폼(#77) — 상위 등급 Operator만 렌더된다(호출부가 `session.user.
// is_superuser`로 게이트한다). 네 필드를 한 폼에 두고, 실제로 바뀐 값만 골라
// 하나의 PATCH로 보낸다 — 여러 값을 같이 바꾸면 `PolicyChange` 한 사건으로
// 남는다(#76의 규율을 이 화면이 그대로 활용한다).
//
// 클라이언트 검증을 두지 않는다(`create-operator-form.tsx`와 같은 판단) — 말이
// 안 되는 값(음수·상한 초과)은 서버(policies.services.update_policy)가 4xx로
// 거절하고, 그 메시지를 그대로 보여준다. 여기서 한 번 더 막으면 서버 판정과
// 클라이언트 판정이 갈라지는 순간(#78·#79가 상한을 조정하는 등) 화면이 서버보다
// 먼저 틀린 이유로 막거나, 서버가 막을 것을 화면이 허용해버린다.
import { useEffect, useState } from "react";

import { updatePolicy } from "./actions";
import { POLICY_FIELDS, POLICY_FIELD_LABELS } from "./types";
import type { PlatformPolicy, PolicyField } from "./types";

type FieldInputs = Record<PolicyField, string>;

function toInputs(policy: PlatformPolicy): FieldInputs {
  return {
    platform_fee_bps: String(policy.platform_fee_bps),
    withholding_tax_bps: String(policy.withholding_tax_bps),
    withholding_necessary_expense_bps: String(policy.withholding_necessary_expense_bps),
    withholding_minor_income_exempt_won: String(policy.withholding_minor_income_exempt_won),
  };
}

export function PolicyEditor({
  policy,
  onSaved,
  onNeedsReload,
  onSessionExpired,
}: {
  policy: PlatformPolicy;
  onSaved: () => void;
  onNeedsReload: () => void;
  onSessionExpired: () => void;
}) {
  const [inputs, setInputs] = useState<FieldInputs>(() => toInputs(policy));
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 이 행의 version이 바뀌었다는 것은 서버의 값이(우리 자신의 저장이든, 다른
  // Operator의 저장이든) 실제로 바뀌었다는 뜻이다 — 그때만 입력값을 서버
  // 값으로 다시 맞춘다. version이 그대로인 동안은 사용자가 타이핑 중인 값을
  // 건드리지 않는다.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    setInputs(toInputs(policy));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [policy.version]);

  function handleChange(field: PolicyField, value: string) {
    setInputs((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const changes: Partial<Record<PolicyField, number>> = {};
    for (const field of POLICY_FIELDS) {
      const raw = inputs[field].trim();
      const parsed = Number(raw);
      const current = policy[field];
      // 파싱 불가한 값(빈 문자열 포함)은 "이 필드는 안 건드림"으로 보내지
      // 않고 그대로 보낸다 — NaN을 그대로 payload에 실으면 JSON.stringify가
      // null로 바꿔버려 서버의 422(요청 검증)로 이어진다. 그 메시지를 그대로
      // 보여주는 것이 "왜 거절됐는지"를 화면이 뭉개지 않는 방법이다.
      if (Number.isNaN(parsed)) {
        changes[field] = raw as unknown as number; // 서버가 타입 오류로 422를 낸다.
        continue;
      }
      if (parsed !== current) {
        changes[field] = parsed;
      }
    }

    if (Object.keys(changes).length === 0) {
      setError("바뀐 값이 없습니다 — 값을 하나 이상 바꿔주세요.");
      return;
    }

    if (!reason.trim()) {
      setError("이유를 남겨야 저장할 수 있습니다.");
      return;
    }

    setPending(true);
    const result = await updatePolicy({ changes, reason, expectedVersion: policy.version });
    setPending(false);

    if (!result.ok) {
      if (result.status === 401) {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      if (result.code === "conflict") {
        // 다른 Operator의 변경이 먼저 반영됐다 — 최신 값을 다시 읽어와야
        // expected_version이 맞아 재시도가 가능하다.
        onNeedsReload();
      }
      return;
    }

    setReason("");
    onSaved();
  }

  return (
    <form onSubmit={handleSubmit} data-testid="policy-editor-form">
      <h2>정책값 바꾸기</h2>
      <table>
        <tbody>
          {POLICY_FIELDS.map((field) => (
            <tr key={field}>
              <td>
                <label htmlFor={`policy-input-${field}`}>{POLICY_FIELD_LABELS[field]}</label>
              </td>
              <td>
                <input
                  id={`policy-input-${field}`}
                  data-testid={`policy-input-${field}`}
                  value={inputs[field]}
                  onChange={(event) => handleChange(field, event.target.value)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <label>
        변경 이유
        <textarea
          data-testid="policy-reason-input"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>

      <button type="submit" data-testid="policy-save-button" disabled={pending}>
        {pending ? "저장 중..." : "저장"}
      </button>

      {error && (
        <p role="alert" data-testid="policy-save-error">
          {error}
        </p>
      )}
    </form>
  );
}
