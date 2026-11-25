"use client";

// 연결된 앱 (ADR-0052, #512, CONTEXT.md 「연결된 앱」) — 내 계정으로 쓰도록 허락한 외부
// AI 앱의 목록과 끊기. 계정 메뉴에서 들어온다. 끊으면 그 앱의 토큰이 곧바로 거절된다.
import { useEffect, useRef, useState } from "react";

import { Card, CardHeader, EmptyState, ErrorNote, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import {
  appDisplayName,
  disconnectConnectedApp,
  fetchConnectedApps,
  type ConnectedAppRow,
} from "@/lib/connected-apps/api";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { useInlineConfirm } from "@/lib/util/use-inline-confirm";

type State = { status: "loading" } | { status: "error" } | { status: "ready"; apps: ConnectedAppRow[] };

const DATE_FORMAT = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long", day: "numeric" });

function formatDate(value: string): string {
  return DATE_FORMAT.format(new Date(value));
}

/** 연결 주소 — AI 앱의 커넥터 설정에 붙여 넣을 MCP 주소. 가입 링크 카드(클래스 상세)와 같은
 *  모양이다: 주소 상자·복사·「복사됨」. 주소는 지금 열린 강의실 오리진에서 만든다 — 앞단
 *  프록시 뒤에서도 브라우저가 친 주소가 곧 바깥 주소다. */
function ConnectAddress({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Card>
      <CardHeader title="연결 주소" hint="AI 앱의 커넥터 설정에 이 주소를 붙여 넣으세요" />
      <div className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <p
            data-testid="connected-apps-mcp-url"
            className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap border border-rule bg-paper px-3 py-2 font-mono text-[13px]"
          >
            {url}
          </p>
          <button
            type="button"
            data-testid="connected-apps-mcp-url-copy"
            onClick={copy}
            disabled={!url}
            className={buttonClass("secondary", "sm")}
          >
            복사
          </button>
          {/* 상태 영역은 늘 있다 — 있다가 생기는 영역은 낭독기가 알리지 않는다(#1447 2-2). */}
          <span role="status" data-testid="connected-apps-mcp-url-copied" className="text-[12px] text-success">
            {copied ? "복사됨" : ""}
          </span>
        </div>
        <ol className="list-decimal space-y-1 pl-5 text-[12.5px] leading-relaxed text-ink/60">
          <li>Claude 같은 AI 앱에서 커넥터(MCP 서버)를 추가하는 화면을 열고 이 주소를 붙여 넣습니다.</li>
          <li>강의실 로그인 화면이 열리면 로그인한 뒤 허락합니다.</li>
          <li>허락한 앱은 아래 목록에 나타나고, 언제든 끊을 수 있습니다.</li>
        </ol>
      </div>
    </Card>
  );
}

function DisconnectAction({
  confirming,
  busy,
  onAsk,
  onKeep,
  onDisconnect,
}: {
  confirming: boolean;
  busy: boolean;
  onAsk: () => void;
  onKeep: () => void;
  onDisconnect: () => void;
}) {
  const { triggerRef, keepRef, onKeyDown } = useInlineConfirm(confirming, onKeep);
  return confirming ? (
    <div className="flex flex-wrap items-center gap-2" onKeyDown={onKeyDown}>
      <span className="text-[12.5px] text-ink/60">끊으면 이 앱은 다시 허락받기 전까지 강의실에 닿지 못합니다.</span>
      <button
        type="button"
        className={buttonClass("dangerFilled", "sm")}
        data-testid="connected-app-disconnect-confirm"
        disabled={busy}
        onClick={onDisconnect}
      >
        {busy ? "끊는 중…" : "끊기"}
      </button>
      <button ref={keepRef} type="button" className={buttonClass("secondary", "sm")} onClick={onKeep} disabled={busy}>
        그대로 두기
      </button>
    </div>
  ) : (
    <button
      ref={triggerRef}
      type="button"
      className={buttonClass("danger", "sm")}
      data-testid="connected-app-disconnect"
      onClick={onAsk}
    >
      끊기
    </button>
  );
}

export default function ConnectedAppsPage() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [confirming, setConfirming] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mcpUrl, setMcpUrl] = useState("");
  // 끊은 앱의 행이 목록에서 빠진 뒤 초점이 갈 곳(#1447 1-5) — 같은 자리로 올라온 다음 앱의 단추, 없으면 목록 제목.
  const [afterDisconnect, setAfterDisconnect] = useState<{ id: number; index: number } | null>(null);
  const listTitleRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (!afterDisconnect || state.status !== "ready") return;
    if (state.apps.some((app) => app.id === afterDisconnect.id)) return; // 목록이 아직 옛것이다
    setAfterDisconnect(null);
    if (document.activeElement && document.activeElement !== document.body) return;
    const next = state.apps[afterDisconnect.index];
    const button = next
      ? document.querySelector<HTMLElement>(`[data-testid="connected-app-row"][data-app-id="${next.id}"] button`)
      : null;
    (button ?? listTitleRef.current)?.focus();
  }, [afterDisconnect, state]);

  async function disconnect(id: number) {
    setBusy(id);
    setError(null);
    const result = await disconnectConnectedApp(id);
    setBusy(null);
    setConfirming(null);
    if (result.ok) {
      if (state.status === "ready") setAfterDisconnect({ id, index: state.apps.findIndex((app) => app.id === id) });
      reload();
    } else setError(result.detail);
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

      <ConnectAddress url={mcpUrl} />

      <Card className="mt-4">
        <div ref={listTitleRef} tabIndex={-1} className="outline-none focus-visible:ring-2 focus-visible:ring-ink/40">
          <CardHeader title="허락한 앱" />
        </div>
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
                data-app-id={app.id}
              >
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="text-[14px] font-medium text-ink">{appDisplayName(app.name)}</span>
                  <span className="text-[12px] text-ink/60">
                    연결한 날 {formatDate(app.connected_at)} · 마지막으로 쓴 날{" "}
                    {app.last_used_at ? formatDate(app.last_used_at) : "아직 쓰지 않음"}
                  </span>
                </div>
                <DisconnectAction
                  confirming={confirming === app.id}
                  busy={busy === app.id}
                  onAsk={() => setConfirming(app.id)}
                  onKeep={() => setConfirming(null)}
                  onDisconnect={() => disconnect(app.id)}
                />
              </li>
            ))}
          </ul>
        )}
      </Card>

    </PageShell>
  );
}
