// 「현재 울리는 경보」 패널(#829) — 자리만 있고 데이터는 경보 티켓(#830)이 채운다. 그 전에는 비어 있다.
// 경보 티켓은 `alerts` 를 응답에서 받아 넘기면 된다(OpsAlert 모양은 lib/ops/types.ts).
import { Panel } from "@/app/components/panel";
import type { OpsAlert } from "@/lib/ops/types";

const SEOUL_TIME = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function AlertPanel({ alerts }: { alerts: readonly OpsAlert[] }) {
  return (
    <Panel title="현재 울리는 경보" meta={alerts.length ? String(alerts.length) : undefined}>
      <div data-testid="ops-alerts">
        {alerts.length === 0 && (
          <p data-testid="ops-alerts-empty" className="px-4 py-3.5 font-mono text-[13px] text-ink/30">
            —
          </p>
        )}
        {alerts.map((alert) => (
          <div
            key={alert.rule}
            data-testid="ops-alert"
            className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0"
          >
            <span className="flex items-center gap-2 font-medium text-attention">
              <span aria-hidden className="inline-block h-2 w-2 bg-attention" />
              {alert.rule}
            </span>
            <span className="font-mono">{alert.value}</span>
            <span className="font-mono text-ink/45">{alert.threshold}</span>
            <span className="font-mono text-ink/45 sm:ml-auto">{SEOUL_TIME.format(new Date(alert.since))}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
