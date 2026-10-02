"use client";

// 연결된 앱 (ADR-0052, #512, CONTEXT.md 「연결된 앱」) — 내 계정으로 쓰도록 허락한 외부
// AI 앱의 목록과 끊기. 계정 메뉴에서 들어온다. 끊으면 그 앱의 토큰이 곧바로 거절된다.
import { useEffect, useState } from "react";

import { Card, EmptyState, ErrorNote, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import {
  appDisplayName,
  disconnectConnectedApp,
  fetchConnectedApps,
  type ConnectedAppRow,
} from "@/lib/connected-apps/api";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";

type State = { status: "loading" } | { status: "error" } | { status: "ready"; apps: ConnectedAppRow[] };

const DATE_FORMAT = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long", day: "numeric" });

function formatDate(value: string): string {
  return DATE_FORMAT.format(new Date(value));
}

export default function ConnectedAppsPage() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [confirming, setConfirming] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mcpUrl, setMcpUrl] = useState("");

  useClassroomTabTitle({ screenName: "연결된 앱" });

  function reload() {
    fetchConnectedApps().then((result) => {
      setState(result.ok ? { status: "ready", apps: result.data } : { status: "error" });
    });
  }

  useEffect(() => {
    setMcpUrl(`${window.location.origin}/mcp`);
    reload();
  }, []);

  async function disconnect(id: number) {
    setBusy(id);
    setError(null);
    const result = await disconnectConnectedApp(id);
    setBusy(null);
    setConfirming(null);
    if (result.ok) reload();
    else setError(result.detail);
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="내 계정"
        title="연결된 앱"
        titleTestId="connected-apps-heading"
        description="내 계정으로 쓰도록 허락한 AI 앱입니다. 연결된 앱은 내가 강사인 모든 클래스에서 화면과 같은 일을 할 수 있습니다."
      />

      {error ? (
        <div className="mb-4">
          <ErrorNote>{error}</ErrorNote>
        </div>
      ) : null}

      <Card>
        {state.status === "loading" ? (
          <EmptyState>불러오는 중…</EmptyState>
        ) : state.status === "error" ? (
          <div className="p-4">
            <ErrorNote>연결된 앱을 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요.</ErrorNote>
          </div>
        ) : state.apps.length === 0 ? (
          <EmptyState>
            <span data-testid="connected-apps-empty">연결된 앱이 없습니다.</span>
          </EmptyState>
        ) : (
          <ul className="divide-y divide-rule" data-testid="connected-apps-list">
            {state.apps.map((app) => (
              <li
                key={app.id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
                data-testid="connected-app-row"
              >
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="text-[14px] font-medium text-ink">{appDisplayName(app.name)}</span>
                  <span className="text-[12px] text-ink/60">
                    연결한 날 {formatDate(app.connected_at)} · 마지막으로 쓴 날{" "}
                    {app.last_used_at ? formatDate(app.last_used_at) : "아직 쓰지 않음"}
                  </span>
                </div>
                {confirming === app.id ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[12.5px] text-ink/60">끊으면 이 앱은 다시 허락받기 전까지 강의실에 닿지 못합니다.</span>
                    <button
                      type="button"
                      className={buttonClass("dangerFilled", "sm")}
                      data-testid="connected-app-disconnect-confirm"
                      disabled={busy === app.id}
                      onClick={() => disconnect(app.id)}
                    >
                      {busy === app.id ? "끊는 중…" : "끊기"}
                    </button>
                    <button
                      type="button"
                      className={buttonClass("secondary", "sm")}
                      onClick={() => setConfirming(null)}
                    >
                      그대로 두기
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className={buttonClass("danger", "sm")}
                    data-testid="connected-app-disconnect"
                    onClick={() => setConfirming(app.id)}
                  >
                    끊기
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <p className="mt-4 text-[12.5px] leading-relaxed text-ink/60">
        Claude 같은 AI 앱의 커넥터 설정에 이 주소를 넣고 강의실 로그인으로 허락하면 연결됩니다:{" "}
        <span className="font-mono text-ink" data-testid="connected-apps-mcp-url">
          {mcpUrl}
        </span>
      </p>
    </PageShell>
  );
}
