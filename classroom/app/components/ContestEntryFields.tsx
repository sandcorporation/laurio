"use client";

// 「공모전에도 내기」 칸(#549, CONTEXT.md) — 공모전 문제의 제출 카드 안, 소스·저장소 입력 위에
// 선다. 켜면 공모전에 직접 낼 때와 같은 칸이 펼쳐진다: 요구사항마다 충족·설명·근거, 선택 자료
// (데모 주소·시연 영상·스크린샷), 소스 열람 동의, 이미 낸 제출이 있으면 바꾸기 확인.
//
// 상태는 부모(제출 화면)가 쥔다 — 소스 파일을 고르는 순간 제출이 나가므로, 그때 이 칸의 값이
// 함께 실려야 한다.
import { useState } from "react";
import type { ChangeEvent } from "react";

import { Badge, ErrorNote, FieldLabel, INPUT_CLASS, Note, buttonClass } from "@/app/components/ui";
import {
  EVIDENCE_KINDS,
  OPTIONAL_ASSET_LABELS,
  type ContestEntryForm,
  type ContestEntryState,
  type EntryResponseState,
} from "@/lib/submissions/contest-entry";
import { useSourceUpload } from "@/lib/submissions/use-source-upload";

function formatDeadline(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

export function ContestEntryFields({
  form,
  state,
  onChange,
  disabled,
}: {
  form: ContestEntryForm;
  state: ContestEntryState;
  onChange: (next: ContestEntryState) => void;
  disabled: boolean;
}) {
  function setResponse(requirementId: number, next: EntryResponseState) {
    onChange({ ...state, responses: { ...state.responses, [requirementId]: next } });
  }

  return (
    <div data-testid="contest-entry" className="flex flex-col gap-3 border border-rule bg-paper p-3.5">
      <label className="flex items-start gap-2.5">
        <input
          type="checkbox"
          data-testid="contest-entry-switch"
          checked={state.on}
          disabled={disabled}
          onChange={(event) => onChange({ ...state, on: event.target.checked })}
          className="mt-1"
        />
        <span className="flex flex-col gap-0.5">
          <span className="text-[13.5px] font-medium">공모전에도 내기</span>
          <span className="text-[12px] leading-relaxed text-ink/60">
            이 시도가 이 공모전의 내 제출이 됩니다
            {form.deadline_at ? ` · 마감 ${formatDeadline(form.deadline_at)}` : ""}. 클래스 채점은
            그대로이고, 공모전은 마감 뒤 따로 채점합니다.
          </span>
        </span>
      </label>

      {state.on ? (
        <div className="flex flex-col gap-3">
          {form.has_entry ? (
            <Note tone="attention">
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  data-testid="contest-entry-replace"
                  checked={state.replaceConfirmed}
                  disabled={disabled}
                  onChange={(event) => onChange({ ...state, replaceConfirmed: event.target.checked })}
                  className="mt-1"
                />
                <span className="text-[12.5px] leading-relaxed">
                  이미 이 공모전에 낸 제출이 있습니다. 이 시도로 바뀝니다 — 지금 공모전에 있는 소스·확인 위치·선택
                  자료는 남지 않습니다.
                </span>
              </label>
            </Note>
          ) : null}

          <div className="flex flex-col gap-2">
            <FieldLabel>요구사항마다 확인 위치(선택)</FieldLabel>
            {form.requirements.map((requirement) => (
              <RequirementEntry
                key={requirement.requirement_id}
                text={requirement.text}
                required={requirement.required}
                testId={`contest-entry-requirement-${requirement.requirement_id}`}
                state={
                  state.responses[requirement.requirement_id] ?? { isMet: false, note: "", evidence: [] }
                }
                onChange={(next) => setResponse(requirement.requirement_id, next)}
                disabled={disabled}
              />
            ))}
          </div>

          <OptionalAssets form={form} state={state} onChange={onChange} disabled={disabled} />

          <label className="flex items-start gap-2.5 border-t border-rule pt-3">
            <input
              type="checkbox"
              data-testid="contest-entry-consent"
              checked={state.consent}
              disabled={disabled}
              onChange={(event) => onChange({ ...state, consent: event.target.checked })}
              className="mt-1"
            />
            <span className="text-[12.5px] leading-relaxed">
              수상작의 소스는 개최자가 볼 수 있습니다 — 동의합니다.
            </span>
          </label>
        </div>
      ) : null}
    </div>
  );
}

function RequirementEntry({
  text,
  required,
  testId,
  state,
  onChange,
  disabled,
}: {
  text: string;
  required: boolean;
  testId: string;
  state: EntryResponseState;
  onChange: (next: EntryResponseState) => void;
  disabled: boolean;
}) {
  return (
    <div data-testid={testId} className="flex flex-col gap-2 border border-rule bg-surface p-3">
      <div className="flex items-start justify-between gap-3">
        <span className="flex items-start gap-2 text-[13px] leading-relaxed">
          <Badge tone={required ? "attention" : "neutral"}>{required ? "필수" : "선택"}</Badge>
          {text}
        </span>
        <label className="flex shrink-0 items-center gap-1 text-[12.5px]">
          <input
            type="checkbox"
            checked={state.isMet}
            disabled={disabled}
            onChange={(event) => onChange({ ...state, isMet: event.target.checked })}
            data-testid={`${testId}-is-met`}
          />
          충족
        </label>
      </div>
      <input
        className={INPUT_CLASS}
        placeholder="설명(선택)"
        value={state.note}
        disabled={disabled}
        onChange={(event) => onChange({ ...state, note: event.target.value })}
        data-testid={`${testId}-note`}
      />
      {state.evidence.map((item, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2">
          <select
            value={item.kind}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...state,
                evidence: state.evidence.map((e, i) => (i === index ? { ...e, kind: event.target.value } : e)),
              })
            }
            data-testid={`${testId}-evidence-${index}-kind`}
            className={INPUT_CLASS}
          >
            {EVIDENCE_KINDS.map((kind) => (
              <option key={kind.value} value={kind.value}>
                {kind.label}
              </option>
            ))}
          </select>
          <input
            className={`min-w-0 flex-1 ${INPUT_CLASS}`}
            placeholder="예: 01:23, /todos, src/app.js 의 addTodo()"
            value={item.value}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...state,
                evidence: state.evidence.map((e, i) => (i === index ? { ...e, value: event.target.value } : e)),
              })
            }
            data-testid={`${testId}-evidence-${index}-value`}
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange({ ...state, evidence: state.evidence.filter((_, i) => i !== index) })}
            className={buttonClass("secondary", "sm")}
          >
            삭제
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange({ ...state, evidence: [...state.evidence, { kind: "source_location", value: "" }] })}
        data-testid={`${testId}-add-evidence`}
        className={`${buttonClass("secondary", "sm")} self-start`}
      >
        + 확인 위치 추가
      </button>
    </div>
  );
}

function OptionalAssets({
  form,
  state,
  onChange,
  disabled,
}: {
  form: ContestEntryForm;
  state: ContestEntryState;
  onChange: (next: ContestEntryState) => void;
  disabled: boolean;
}) {
  const [demoUrl, setDemoUrl] = useState("");
  const screenshot = useSourceUpload(form.upload_target_refs.screenshot ?? null);
  const video = useSourceUpload(form.upload_target_refs.demo_video ?? null);

  function addAsset(kind: string, value: string, contentType: string, label = "") {
    onChange({
      ...state,
      optionalAssets: [...state.optionalAssets, { kind, value, label, content_type: contentType }],
    });
  }

  async function onFile(kind: "screenshot" | "demo_video", event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const uploader = kind === "screenshot" ? screenshot : video;
    try {
      const uploaded = await uploader.upload(file);
      addAsset(kind, uploaded.objectKey, uploaded.contentType ?? "", file.name.slice(0, 200));
    } catch {
      // 업로드 훅이 이유를 상태에 남긴다.
    }
  }

  const uploadError = screenshot.state.error ?? video.state.error;
  const uploading = screenshot.state.status === "uploading" || video.state.status === "uploading";

  return (
    <div className="flex flex-col gap-2">
      <FieldLabel>선택 자료</FieldLabel>
      {state.optionalAssets.length > 0 ? (
        <ul data-testid="contest-entry-assets" className="flex flex-col gap-1.5">
          {state.optionalAssets.map((asset, index) => (
            <li key={`${asset.kind}-${asset.value}`} className="flex items-center gap-2 text-[12.5px]">
              <Badge>{OPTIONAL_ASSET_LABELS[asset.kind] ?? asset.kind}</Badge>
              <span className="min-w-0 flex-1 truncate text-ink/70">
                {asset.kind === "demo_url" ? asset.value : asset.label || "올린 파일"}
              </span>
              <button
                type="button"
                disabled={disabled}
                onClick={() =>
                  onChange({ ...state, optionalAssets: state.optionalAssets.filter((_, i) => i !== index) })
                }
                className="text-[12px] text-ink/45 hover:underline"
              >
                빼기
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex gap-2">
        <input
          type="url"
          className={`min-w-0 flex-1 ${INPUT_CLASS}`}
          placeholder="데모 주소 https://"
          value={demoUrl}
          disabled={disabled}
          onChange={(event) => setDemoUrl(event.target.value)}
          data-testid="contest-entry-demo-url"
        />
        <button
          type="button"
          disabled={disabled || demoUrl.trim() === ""}
          onClick={() => {
            addAsset("demo_url", demoUrl.trim(), "");
            setDemoUrl("");
          }}
          className={buttonClass("secondary", "sm")}
        >
          더하기
        </button>
      </div>
      <div className="flex flex-wrap gap-2 text-[12.5px]">
        <label className={`${buttonClass("secondary", "sm")} cursor-pointer`}>
          스크린샷 올리기
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="sr-only"
            disabled={disabled || uploading}
            onChange={(event) => onFile("screenshot", event)}
          />
        </label>
        <label className={`${buttonClass("secondary", "sm")} cursor-pointer`}>
          시연 영상 올리기
          <input
            type="file"
            accept="video/*"
            className="sr-only"
            disabled={disabled || uploading}
            onChange={(event) => onFile("demo_video", event)}
          />
        </label>
        {uploading ? <span className="self-center text-ink/45">올리는 중...</span> : null}
      </div>
      {uploadError ? (
        <ErrorNote>
          <span>{uploadError}</span>
        </ErrorNote>
      ) : null}
    </div>
  );
}
