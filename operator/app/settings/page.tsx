"use client";

// 설정 화면(#922, ADR-0075, #1041) — 탭 하나에 운영 설정(키별 저장)과 플랫폼 정책(묶음 저장·이유·version)이 같이 선다. 저장하면 재시작 없이 다음 호출부터 반영된다.
// 일반 등급은 값·출처·이력만 본다. 분기 순서는 정책 화면과 같다(unauthenticated 를 로딩보다 먼저).
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { RuntimeSettingHistoryTable } from "@/lib/runtime-settings/history-table";
import { RuntimeSettingRow } from "@/lib/runtime-settings/setting-row";
import { useRuntimeSettings } from "@/lib/runtime-settings/use-runtime-settings";
import { usePolicy } from "@/lib/policies/use-policy";
import { usePolicyHistory } from "@/lib/policies/use-policy-history";
import { PolicyEditor } from "@/lib/policies/policy-editor";
import { PolicyHistoryTable } from "@/lib/policies/policy-history";
import { PolicyValuesTable } from "@/lib/policies/policy-values-table";
import { SETTINGS_TABS, policyFieldsOfTab, settingsOfTab, tabFromParam } from "@/lib/runtime-settings/view";

function Heading({ children }: { children: string }) {
  return <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{children}</h2>;
}

function RuntimeSettingsScreen() {
  const router = useRouter();
  const tab = tabFromParam(useSearchParams().get("tab"));
  const policyFields = policyFieldsOfTab(tab);
  const hasPolicy = policyFields.length > 0;
  const session = useSession();
  const authed = session.status === "authenticated";
  const { settings, changes, reload } = useRuntimeSettings(authed);
  const { state: policy, reload: reloadPolicy } = usePolicy(authed);
  const { state: policyHistory, reload: reloadPolicyHistory } = usePolicyHistory(authed);

  if (session.status === "unauthenticated") return null;

  if (session.status === "loading" || settings.status === "loading" || (hasPolicy && policy.status === "loading")) {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="runtime-settings-loading">불러오는 중...</p>
      </div>
    );
  }

  const editable = session.user.is_superuser;
  const tabSettings = settings.status === "loaded" ? settingsOfTab(settings.data, tab) : [];
  const visibleTabs = SETTINGS_TABS.filter(
    (t) =>
      t.id === tab ||
      policyFieldsOfTab(t.id).length > 0 ||
      (settings.status === "loaded" ? settingsOfTab(settings.data, t.id).length > 0 : t.id === "ai"),
  );
  const showSettingsHistory = !hasPolicy || tabSettings.length > 0;
  const bothHistories = hasPolicy && showSettingsHistory;

  function handlePolicySaved() {
    reloadPolicy();
    reloadPolicyHistory();
  }

  return (
    <>
      <PageHeader crumb="기준 · 운영 설정" title="운영 설정" />
      <div className="flex flex-1 flex-col gap-6 p-4 sm:p-8">
        <div className="flex items-baseline justify-between gap-3">
          <div role="tablist" aria-label="운영 설정" className="flex flex-wrap items-end gap-0.5">
            {visibleTabs.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                role="tab"
                id={`runtime-settings-tab-${id}`}
                aria-selected={tab === id}
                aria-controls="runtime-settings-panel"
                data-testid={`runtime-settings-tab-${id}`}
                onClick={() => router.replace(`/settings?tab=${id}`)}
                className={
                  tab === id
                    ? "border border-rule bg-surface px-4 py-2 text-[13.5px] font-medium"
                    : "px-4 py-2 text-[13.5px] text-ink/62 hover:text-ink"
                }
              >
                {label}
              </button>
            ))}
          </div>
          {!editable && (
            <span
              data-testid="runtime-settings-read-only"
              className="border border-rule px-1.5 py-0.5 text-[11px] text-ink/62"
            >
              조회 전용
            </span>
          )}
        </div>

        <div role="tabpanel" id="runtime-settings-panel" aria-labelledby={`runtime-settings-tab-${tab}`} className="-mt-5 flex flex-col gap-6">
          {settings.status === "error" && (
            <p role="alert" data-testid="runtime-settings-error" className="text-[13px] text-attention">
              운영 설정을 불러오지 못했습니다.
            </p>
          )}
          {tabSettings.length > 0 && (
            <div data-testid="runtime-settings-list" className="border border-rule bg-surface">
              {tabSettings.map((setting) => (
                // 저장 뒤 다시 읽으면 key 가 같아도 updated_at 이 달라 입력 상태를 새로 시작한다.
                <RuntimeSettingRow
                  key={`${setting.key}-${setting.updated_at ?? "none"}-${setting.source}`}
                  setting={setting}
                  editable={editable}
                  onChanged={reload}
                />
              ))}
            </div>
          )}

          {hasPolicy && policy.status === "error" && (
            <p role="alert" data-testid="policy-error" className="text-[13px] text-attention">
              정책값을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
            </p>
          )}
          {hasPolicy && policy.status === "loaded" && (
            <>
              <PolicyValuesTable policy={policy.policy} fields={policyFields} />
              {editable ? (
                <PolicyEditor
                  policy={policy.policy}
                  fields={policyFields}
                  onSaved={handlePolicySaved}
                  onNeedsReload={reloadPolicy}
                  onSessionExpired={() => router.replace("/login")}
                />
              ) : (
                // 「너는 안 된다」와 「여기엔 아무것도 없다」가 다르게 읽혀야 한다(계정 관리 화면의 관용구, #69).
                <p role="alert" data-testid="policy-edit-forbidden" className="text-[13px] text-attention">
                  이 값을 바꾸려면 상위 등급 Operator 권한이 필요합니다. 지금은 조회만 가능합니다.
                </p>
              )}
            </>
          )}

          {showSettingsHistory && (
            <div>
              <Heading>{bothHistories ? "운영 설정 변경 이력" : "변경 이력"}</Heading>
              <div className="mt-2.5">
                {changes.status === "loading" && (
                  <p data-testid="runtime-settings-history-loading" className="text-[13px] text-ink/62">
                    불러오는 중...
                  </p>
                )}
                {changes.status === "error" && (
                  <p role="alert" data-testid="runtime-settings-history-error" className="text-[13px] text-attention">
                    변경 이력을 불러오지 못했습니다.
                  </p>
                )}
                {changes.status === "loaded" && <RuntimeSettingHistoryTable changes={changes.data} />}
              </div>
            </div>
          )}

          {hasPolicy && (
            <div>
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <Heading>{bothHistories ? "정책 변경 이력" : "변경 이력"}</Heading>
                <p data-testid="policy-history-immutable-note" className="text-[12px] text-ink/62">
                  이 이력은 고치거나 지울 수 없습니다.
                </p>
              </div>
              <div className="mt-2.5">
                {policyHistory.status === "loading" && (
                  <p data-testid="policy-history-loading" className="text-[13px] text-ink/62">
                    이력을 불러오는 중...
                  </p>
                )}
                {policyHistory.status === "error" && (
                  <p role="alert" data-testid="policy-history-error" className="text-[13px] text-attention">
                    변경 이력을 불러오지 못했습니다.
                  </p>
                )}
                {policyHistory.status === "loaded" && <PolicyHistoryTable changes={policyHistory.changes} />}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// useSearchParams 는 Suspense 경계가 필요하다(app/usage/page.tsx 와 같은 이유).
export default function RuntimeSettingsPage() {
  return (
    <Suspense fallback={null}>
      <RuntimeSettingsScreen />
    </Suspense>
  );
}
