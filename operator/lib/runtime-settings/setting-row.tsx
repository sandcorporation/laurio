"use client";

// 운영 설정 한 줄(#922) — 라벨·지금 값·출처·변경 시각/변경자, 상위 등급이면 입력·저장·연결 시험·지우기.
// 비밀 입력은 쓰기 전용이다: 처음 값은 언제나 빈칸이고, 저장 뒤에도 비운다.
import { useState } from "react";

import { clearRuntimeSetting, probeRuntimeSetting, saveRuntimeSetting } from "./actions";
import type { ProbeResult, RuntimeSetting } from "./types";
import {
  PROBE_LABELS,
  SOURCE_LABELS,
  canClear,
  canProbe,
  initialInput,
  inputAttributes,
  savePayload,
  updatedText,
  valueSummary,
} from "./view";

const BUTTON = "border border-rule bg-paper px-3 py-1.5 text-[13px] text-ink disabled:opacity-50";
const PRIMARY = "border border-ink bg-ink px-3.5 py-1.5 text-[13px] text-paper disabled:opacity-50";

export function RuntimeSettingRow({
  setting,
  editable,
  onChanged,
}: {
  setting: RuntimeSetting;
  editable: boolean;
  onChanged: () => void;
}) {
  const [input, setInput] = useState(() => initialInput(setting));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const id = `runtime-setting-${setting.key}`;
  const attrs = inputAttributes(setting);

  async function run(action: () => Promise<{ ok: boolean; detail?: string }>, after: () => void) {
    setPending(true);
    setError(null);
    const result = await action();
    setPending(false);
    if (!result.ok) {
      setError(result.detail ?? "요청을 처리하지 못했습니다.");
      return;
    }
    after();
  }

  function handleSave(event: React.FormEvent) {
    event.preventDefault();
    const payload = savePayload(input);
    if (payload === null) {
      setInput("");
      return;
    }
    void run(
      () => saveRuntimeSetting(setting.key, payload.value),
      () => {
        setInput("");
        setProbe(null);
        onChanged();
      },
    );
  }

  function handleClear() {
    void run(
      () => clearRuntimeSetting(setting.key),
      () => {
        setProbe(null);
        onChanged();
      },
    );
  }

  function handleProbe() {
    void run(
      async () => {
        const result = await probeRuntimeSetting(setting.key, input.trim());
        if (result.ok) setProbe(result.data.result);
        return result;
      },
      () => {},
    );
  }

  return (
    <div data-testid={id} className="flex flex-col gap-3 border-b border-rule px-4 py-3.5 last:border-b-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <div className="text-[13.5px] font-medium">{setting.label}</div>
          <div className="font-mono text-[11.5px] text-ink/45 break-all">{setting.key}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <span data-testid={`${id}-value`} className="font-mono break-all">
            {valueSummary(setting)}
          </span>
          <span
            data-testid={`${id}-source`}
            className="border border-rule px-1.5 py-0.5 text-[11px] tracking-[0.04em] text-ink/62"
          >
            {SOURCE_LABELS[setting.source]}
          </span>
        </div>
      </div>
      {updatedText(setting) !== null && (
        <div data-testid={`${id}-updated`} className="text-[12px] text-ink/62">
          {updatedText(setting)}
        </div>
      )}

      {editable && (
        <form onSubmit={handleSave} className="flex flex-wrap items-center gap-2">
          <label htmlFor={`${id}-input`} className="sr-only">
            {setting.label}
          </label>
          <input
            id={`${id}-input`}
            data-testid={`${id}-input`}
            type={attrs.type}
            autoComplete={attrs.autoComplete}
            inputMode={attrs.inputMode}
            spellCheck={false}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            className="min-w-0 flex-1 basis-[220px] border border-rule bg-paper px-2.5 py-1.5 font-mono text-[13px] text-ink"
          />
          <button type="submit" data-testid={`${id}-save`} disabled={pending} className={PRIMARY}>
            저장
          </button>
          {canProbe(setting) && (
            <button
              type="button"
              data-testid={`${id}-probe`}
              disabled={pending}
              onClick={handleProbe}
              className={BUTTON}
            >
              연결 시험
            </button>
          )}
          {canClear(setting) && (
            <button
              type="button"
              data-testid={`${id}-clear`}
              disabled={pending}
              onClick={handleClear}
              className={BUTTON}
            >
              지우기
            </button>
          )}
        </form>
      )}

      {probe && (
        <p
          data-testid={`${id}-probe-result`}
          className={`text-[12.5px] ${probe === "ok" ? "text-ink" : "text-attention"}`}
        >
          {PROBE_LABELS[probe]}
        </p>
      )}
      {error && (
        <p role="alert" data-testid={`${id}-error`} className="text-[12.5px] text-attention">
          {error}
        </p>
      )}
    </div>
  );
}
