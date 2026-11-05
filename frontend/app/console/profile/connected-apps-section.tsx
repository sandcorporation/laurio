"use client";

// 「내 정보」의 연결된 앱 (#870) — 공모전 MCP 에 허락한 앱(claude.ai·Claude Code 등)을 보고 끊는다.
// 끊으면 그 앱의 토큰이 곧바로 막힌다(백엔드 `DELETE /api/contests/connected-apps/{id}`).
import { useEffect, useState } from "react";

import { ErrorNote, buttonClass } from "@/app/components/ui";
import {
  appDisplayName,
  connectionDates,
  disconnectConnectedApp,
  fetchConnectedApps,
  type ConnectedAppRow,
} from "@/lib/connected-apps/api";

type LoadState = { status: "loading" } | { status: "error" } | { status: "ready"; apps: ConnectedAppRow[] };

export function ConnectedAppsSection() {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchConnectedApps().then((result) => {
      if (cancelled) return;
      setLoad(result.ok ? { status: "ready", apps: result.data } : { status: "error" });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function disconnect(app: ConnectedAppRow) {
    if (busyId !== null) return;
    setBusyId(app.id);
    setActionError(null);
    const result = await disconnectConnectedApp(app.id);
    setBusyId(null);
    if (!result.ok) {
      setActionError(result.detail);
      return;
    }
    setLoad((current) =>
      current.status === "ready" ? { status: "ready", apps: current.apps.filter((row) => row.id !== app.id) } : current,
    );
  }

  return (
    <section className="mt-8 border-t border-rule pt-6" data-testid="profile-connected-apps-section">
      <h2 className="text-lg font-semibold">연결된 앱</h2>

      {load.status === "loading" ? (
        <p className="mt-4 text-sm text-ink/60" data-testid="profile-connected-apps-loading">
          불러오는 중...
        </p>
      ) : load.status === "error" ? (
        <div className="mt-4">
          <ErrorNote testId="profile-connected-apps-load-error">불러오지 못했습니다. 잠시 후 다시 시도해주세요.</ErrorNote>
        </div>
      ) : load.apps.length === 0 ? (
        <p className="mt-4 text-sm text-ink/45" data-testid="profile-connected-apps-empty">
          연결된 앱 없음
        </p>
      ) : (
        <ul className="mt-4 flex flex-col divide-y divide-rule border-y border-rule" data-testid="profile-connected-apps-list">
          {load.apps.map((app) => (
            <li key={app.id} className="flex flex-wrap items-center justify-between gap-3 py-3" data-testid="profile-connected-app">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium" data-testid="profile-connected-app-name">
                  {appDisplayName(app.name)}
                </div>
                <div className="mt-0.5 text-xs text-ink/60">{connectionDates(app)}</div>
              </div>
              <button
                type="button"
                className={buttonClass("secondary")}
                disabled={busyId !== null}
                onClick={() => disconnect(app)}
                data-testid="profile-connected-app-disconnect"
              >
                {busyId === app.id ? "끊는 중..." : "연결 끊기"}
              </button>
            </li>
          ))}
        </ul>
      )}

      {actionError ? (
        <div className="mt-2">
          <ErrorNote testId="profile-connected-apps-error">{actionError}</ErrorNote>
        </div>
      ) : null}
    </section>
  );
}
