"use client";

// 운영 설정 화면(#922, ADR-0075) — 공모전 AI 키·모델 값. 저장하면 재시작 없이 다음 호출부터 반영된다.
// 일반 등급은 값·출처·이력만 본다. 분기 순서는 정책 화면과 같다(unauthenticated 를 로딩보다 먼저).
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/app/components/page-header";
import { useSession } from "@/lib/auth/use-session";
import { RuntimeSettingHistoryTable } from "@/lib/runtime-settings/history-table";
import { RuntimeSettingRow } from "@/lib/runtime-settings/setting-row";
import { useRuntimeSettings } from "@/lib/runtime-settings/use-runtime-settings";
import { SETTINGS_TABS, settingsOfTab, tabFromParam } from "@/lib/runtime-settings/view";

function RuntimeSettingsScreen() {
  const router = useRouter();
  const tab = tabFromParam(useSearchParams().get("tab"));
  const session = useSession();
  const { settings, changes, reload } = useRuntimeSettings(session.status === "authenticated");

  if (session.status === "unauthenticated") return null;

  if (session.status === "loading" || settings.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="runtime-settings-loading">불러오는 중...</p>
      </div>
    );
  }

  const editable = session.user.is_superuser;
  const visibleTabs =
    settings.status === "loaded"
      ? SETTINGS_TABS.filter((t) => t.id === tab || settingsOfTab(settings.data, t.id).length > 0)
      : SETTINGS_TABS.slice(0, 1);

  return (
    <>
      <PageHeader crumb="기준 · 운영 설정" title="운영 설정" />
      <div className="flex flex-1 flex-col gap-6 p-4 sm:p-8">
        {settings.status === "error" && (
          <p role="alert" data-testid="runtime-settings-error" className="text-[13px] text-attention">
            운영 설정을 불러오지 못했습니다.
          </p>
        )}
        {settings.status === "loaded" && (
          <div>
            <div className="flex items-baseline justify-between gap-3">
              <div role="tablist" aria-label="운영 설정" className="flex items-end gap-0.5">
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
            <div
              role="tabpanel"
              id="runtime-settings-panel"
              aria-labelledby={`runtime-settings-tab-${tab}`}
              data-testid="runtime-settings-list"
              className="-mt-px border border-rule bg-surface"
            >
              {settingsOfTab(settings.data, tab).map((setting) => (
                // 저장 뒤 다시 읽으면 key 가 같아도 updated_at 이 달라 입력 상태를 새로 시작한다.
                <RuntimeSettingRow
                  key={`${setting.key}-${setting.updated_at ?? "none"}-${setting.source}`}
                  setting={setting}
                  editable={editable}
                  onChanged={reload}
                />
              ))}
            </div>
          </div>
        )}

        <div>
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">변경 이력</h2>
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
