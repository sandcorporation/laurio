"use client";

// 「채점 연결」(#601, CONTEXT.md 「채점 연결」) — 클래스 설정의 첫 구획(`#scoring-key`, 카드는 쪽이
// 감싼다). 이 클래스의 채점이 모델에 닿는 길을 소유자가 고른다: OpenAI·Claude 키를 둘 다 넣어 두고 스위치로
// 고르거나(#1269), 셋째 선택 「호환 서버」(소유자가 바깥에 열어 둔 OpenAI 호환 주소와 Bearer 값). 상태 한 줄이
// 먼저 보이고(#636) 그 아래 스위치와 키 두 줄이 선다. 공동 강사는 상태 한 줄만 본다(ADR-0055).
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { Badge, ErrorNote, FieldLabel, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import {
  deleteVendorKey,
  setAnthropicKey,
  setCompatibleServer,
  setOpenAIKey,
  switchScoringVendor,
  type ClassRow,
  type VendorKey,
} from "@/lib/classes/api";
import { CLAUDE_KEY_LABEL, connectionKindOptions, type ConnectionKind } from "@/lib/classes/connection-kinds";
import { formatDay } from "@/lib/classes/format-day";
import { checkOpenAIKeyFromBrowser, type OpenAIKeyCheckResult } from "@/lib/classes/openai-key-check";
import { settingsStatusBadges } from "@/lib/classes/scoring-status";
import { useInlineConfirm } from "@/lib/util/use-inline-confirm";

const STATUS_CLASS = "flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-[13.5px]";

// 연결이 마지막으로 확인된 날(#671) — 채점이 한 번 성공했거나, 저장 때 벤더·서버가 받아들였거나,
// 호환 서버 모델 시험 호출이 통과한 날. 확인된 적 없으면 내지 않는다.
function VerifiedDay({ classroom }: { classroom: ClassRow }) {
  if (!classroom.scoring_connection_verified_at) return null;
  return (
    <span data-testid="scoring-connection-verified" className="text-[12px] text-ink/45">
      {formatDay(classroom.scoring_connection_verified_at)} 확인
    </span>
  );
}

// 상태 한 줄(#636, 시안 v2) — 배지 · 종류 · 마스킹(또는 호스트). 문장은 두지 않는다: 배지가 상태를,
// 오른쪽 「바꾸기」가 할 일을 말한다. 배지의 낱말·톤은 클래스 상세 「채점」 카드와 같은 함수가 정한다
// (`settingsStatusBadges`, #669) — 여기서 따로 셈하지 않는다.
function ConnectionStatus({ classroom }: { classroom: ClassRow }) {
  const badges = settingsStatusBadges(classroom).map((badge) => (
    <Badge key={badge.label} tone={badge.tone}>
      {badge.label}
    </Badge>
  ));
  if (!classroom.has_openai_key) {
    return (
      <p data-testid="openai-key-status" className={STATUS_CLASS}>
        {badges}
      </p>
    );
  }
  if (classroom.scoring_connection_kind === "compatible_server") {
    return (
      <p data-testid="scoring-connection-status" className={STATUS_CLASS}>
        {badges}
        <span>호환 서버</span>
        <span data-testid="scoring-server-host" className="font-mono text-ink/70">
          {classroom.scoring_server_host}
        </span>
        {classroom.scoring_auth_masked ? (
          <span className="font-mono text-ink/50">{classroom.scoring_auth_masked}</span>
        ) : null}
        <VerifiedDay classroom={classroom} />
      </p>
    );
  }
  const anthropic = classroom.scoring_connection_kind === "anthropic_key";
  return (
    <p data-testid={anthropic ? "anthropic-key-status" : "openai-key-status"} className={STATUS_CLASS}>
      {badges}
      <span>{anthropic ? CLAUDE_KEY_LABEL : "OpenAI 키"}</span>
      <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
      <VerifiedDay classroom={classroom} />
    </p>
  );
}

type VendorKind = "openai_key" | "anthropic_key";

const VENDOR_LABELS: Record<ConnectionKind, string> = {
  openai_key: "OpenAI",
  anthropic_key: "Claude",
  compatible_server: "호환 서버",
};

// 채점 벤더 스위치(#1269) — 넣어 둔 키 가운데 어느 쪽으로 채점할지. 키가 없거나 거부된 쪽은 고를 수 없다
// (`VendorKey.switchable`, 서버도 거절한다). 「호환 서버」는 셋째 선택이다 — 누르면 서버 폼이 열리고 저장해야 넘어간다.
function VendorSwitch({
  classroom,
  compatibleOpen,
  onSwitch,
  onCompatible,
  busy,
}: {
  classroom: ClassRow;
  compatibleOpen: boolean;
  onSwitch: (kind: VendorKind) => void;
  onCompatible: () => void;
  busy: boolean;
}) {
  const options = connectionKindOptions(classroom.anthropic_key_selectable);
  const current = classroom.has_openai_key ? classroom.scoring_connection_kind : null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <FieldLabel>채점</FieldLabel>
      <div role="radiogroup" aria-label="채점 벤더" className="flex flex-wrap gap-2">
        {options.map((option) => {
          const vendorKey =
            option.kind === "openai_key"
              ? classroom.openai_key
              : option.kind === "anthropic_key"
                ? classroom.anthropic_key
                : null;
          const checked = option.kind === current || (option.kind === "compatible_server" && compatibleOpen);
          const disabled = busy || (option.kind !== "compatible_server" && !vendorKey?.switchable);
          return (
            <button
              key={option.kind}
              type="button"
              role="radio"
              aria-checked={checked}
              disabled={disabled}
              data-testid={`scoring-connection-kind-${option.kind}`}
              onClick={() => {
                if (option.kind === "compatible_server") onCompatible();
                else if (option.kind !== current) onSwitch(option.kind);
              }}
              className={buttonClass(checked ? "primary" : "secondary", "sm")}
            >
              {VENDOR_LABELS[option.kind]}
            </button>
          );
        })}
      </div>
    </div>
  );
}

const KEY_STATUS_BADGE: Record<VendorKey["status"], { label: string; tone: "verified" | "neutral" | "error" }> = {
  verified: { label: "확인함", tone: "verified" },
  unverified: { label: "미검증", tone: "neutral" },
  rejected: { label: "거부됨", tone: "error" },
};

// 넣어 둔 벤더 키 한 줄(#1269) — 이름 · 끝 네 자리 · 상태 · 바꾸기 · 지우기. 키 값은 다시 보이지 않는다.
function VendorKeyRow({
  classroom,
  provider,
  onSaved,
  announce,
}: {
  classroom: ClassRow;
  provider: "openai" | "anthropic";
  onSaved: () => void;
  announce: (message: string) => void;
}) {
  const vendorKey = provider === "anthropic" ? classroom.anthropic_key : classroom.openai_key;
  const label = provider === "anthropic" ? CLAUDE_KEY_LABEL : "OpenAI 키";
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deleteConfirm = useInlineConfirm(confirming, () => setConfirming(false));
  // 지우면 「지우기」가 사라진다 — 초점은 늘 있는 「넣기」로.
  const changeButtonRef = useRef<HTMLButtonElement>(null);
  const active = classroom.scoring_connection_kind === `${provider}_key`;

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    const result = await deleteVendorKey(classroom.id, provider);
    setDeleting(false);
    if (result.ok) {
      changeButtonRef.current?.focus();
      announce(`${label}를 지웠습니다.`);
      onSaved();
    } else {
      setError(result.detail);
    }
    setConfirming(false);
  }

  const badge = vendorKey ? KEY_STATUS_BADGE[vendorKey.status] : null;
  return (
    <div data-testid={`vendor-key-${provider}`} className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className={STATUS_CLASS}>
          <span className="min-w-[132px]">{label}</span>
          {vendorKey ? (
            <>
              <span data-testid={`vendor-key-${provider}-masked`} className="font-mono text-ink/60">
                {vendorKey.masked}
              </span>
              {badge ? <Badge tone={badge.tone}>{badge.label}</Badge> : null}
            </>
          ) : (
            <span className="text-ink/45">없음</span>
          )}
        </p>
        <div className="flex gap-2">
          <button
            ref={changeButtonRef}
            type="button"
            data-testid={`vendor-key-${provider}-change`}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className={buttonClass("secondary", "sm")}
          >
            {open ? "닫기" : vendorKey ? "바꾸기" : "넣기"}
          </button>
          {vendorKey && !confirming ? (
            <button
              ref={deleteConfirm.triggerRef}
              type="button"
              data-testid={`vendor-key-${provider}-delete`}
              onClick={() => setConfirming(true)}
              className={buttonClass("secondary", "sm")}
            >
              지우기
            </button>
          ) : null}
        </div>
      </div>
      {vendorKey && confirming ? (
        <div
          data-testid={`vendor-key-${provider}-delete-confirm`}
          onKeyDown={deleteConfirm.onKeyDown}
          className="flex flex-wrap items-center gap-2 border border-rule bg-paper px-3 py-2.5"
        >
          <span className="text-[12.5px] text-ink/70">
            {active ? `${label}를 지우면 채점이 멈춥니다.` : `${label}를 지웁니다.`}
          </span>
          <button
            type="button"
            data-testid={`vendor-key-${provider}-delete-confirm-button`}
            disabled={deleting}
            onClick={() => void handleDelete()}
            className={buttonClass("dangerFilled", "sm")}
          >
            {deleting ? "지우는 중..." : "지우기"}
          </button>
          <button
            ref={deleteConfirm.keepRef}
            type="button"
            disabled={deleting}
            onClick={() => setConfirming(false)}
            className={buttonClass("secondary", "sm")}
          >
            그대로 두기
          </button>
        </div>
      ) : null}
      {error ? (
        <ErrorNote>
          <span data-testid={`vendor-key-${provider}-delete-error`}>{error}</span>
        </ErrorNote>
      ) : null}
      {open ? (
        <KeyForm
          classId={classroom.id}
          provider={provider}
          onSaved={() => {
            setOpen(false);
            // 저장하면 폼과 누른 저장 단추가 사라진다 — 초점은 늘 있는 「바꾸기」로(삭제와 같다).
            changeButtonRef.current?.focus();
            announce(`${label}를 저장했습니다.`);
            onSaved();
          }}
        />
      ) : null}
    </div>
  );
}

function KeyForm({
  classId,
  provider,
  onSaved,
}: {
  classId: number;
  provider: "openai" | "anthropic";
  onSaved: () => void;
}) {
  const anthropic = provider === "anthropic";
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 저장 전에 브라우저가 직접 벤더에게 물어 미리 말한다(#357) — 문이 아니라 안내다, 저장 버튼은
  // 이 값과 무관하게 항상 눌린다. 입력이 멎은 뒤 한 번만 친다.
  const [liveCheck, setLiveCheck] = useState<OpenAIKeyCheckResult | "checking" | "idle">("idle");
  const liveId = `${provider}-key-live-check`;
  const errorId = `${provider}-key-error`;
  // 확정된 오류만 aria-invalid — 저장이 거절됐거나 벤더가 키를 거부했다. 확인 중·확인 못 함은 오류가 아니다.
  const invalid = error !== null || liveCheck === "invalid";
  const describedBy = [liveCheck !== "idle" ? liveId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;

  useEffect(() => {
    const trimmed = apiKey.trim();
    // 브라우저에서 벤더에 바로 묻는 것은 OpenAI 만이다 — Claude 키는 저장 때 서버가 확인한다.
    if (anthropic || trimmed === "") {
      setLiveCheck("idle");
      return;
    }
    setLiveCheck("checking");
    let cancelled = false;
    const timer = setTimeout(() => {
      checkOpenAIKeyFromBrowser(trimmed).then((result) => {
        if (!cancelled) setLiveCheck(result);
      });
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [apiKey, anthropic]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const result = await (anthropic ? setAnthropicKey : setOpenAIKey)(classId, apiKey);
    if (result.ok) {
      setApiKey("");
      onSaved();
    } else {
      setError(result.detail);
    }
    setSaving(false);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2.5">
      <label htmlFor={`${provider}-api-key`}>
        <FieldLabel>채점 키</FieldLabel>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          id={`${provider}-api-key`}
          data-testid={`${provider}-key-input`}
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          required
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={`${INPUT_CLASS} min-w-[240px] flex-1 font-mono`}
          placeholder={anthropic ? "sk-ant-..." : "sk-..."}
        />
        <button
          type="submit"
          data-testid={`${provider}-key-submit`}
          disabled={saving || apiKey.trim() === ""}
          className={buttonClass("primary")}
        >
          {saving ? "저장하는 중..." : "저장"}
        </button>
      </div>
      <p id={liveId} role="status" data-testid={liveId} className="text-[12px] text-ink/45 empty:hidden">
        {liveCheck === "checking" ? (
          "확인하는 중..."
        ) : liveCheck === "valid" ? (
          <Badge tone="verified">이 키를 쓸 수 있습니다</Badge>
        ) : liveCheck === "invalid" ? (
          <Badge tone="error">이 키는 쓸 수 없습니다</Badge>
        ) : liveCheck === "unknown" ? (
          <Badge tone="neutral">지금은 확인할 수 없습니다</Badge>
        ) : null}
      </p>
      {error ? (
        <ErrorNote>
          <span id={errorId} data-testid={errorId}>
            {error}
          </span>
        </ErrorNote>
      ) : null}
    </form>
  );
}

function CompatibleServerForm({
  classroom,
  onSaved,
}: {
  classroom: ClassRow;
  onSaved: () => void;
}) {
  const [serverUrl, setServerUrl] = useState(classroom.scoring_server_url ?? "");
  const [authValue, setAuthValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const result = await setCompatibleServer(classroom.id, serverUrl.trim(), authValue);
    if (result.ok) {
      setAuthValue("");
      onSaved();
    } else {
      setError(result.detail);
    }
    setSaving(false);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2.5">
      <label htmlFor="scoring-server-url" className="flex flex-col gap-1.5">
        <FieldLabel>주소</FieldLabel>
        <input
          id="scoring-server-url"
          data-testid="scoring-server-url-input"
          type="url"
          inputMode="url"
          value={serverUrl}
          onChange={(event) => setServerUrl(event.target.value)}
          required
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "scoring-server-error" : undefined}
          className={`${INPUT_CLASS} font-mono`}
          placeholder="https://llm.example.com/v1"
        />
      </label>
      <label htmlFor="scoring-server-auth" className="flex flex-col gap-1.5">
        <FieldLabel>인증 값 (Authorization: Bearer)</FieldLabel>
        <input
          id="scoring-server-auth"
          data-testid="scoring-server-auth-input"
          type="password"
          value={authValue}
          onChange={(event) => setAuthValue(event.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "scoring-server-error" : undefined}
          className={`${INPUT_CLASS} font-mono`}
          placeholder="선택"
        />
      </label>
      <div>
        <button
          type="submit"
          data-testid="scoring-server-submit"
          disabled={saving || serverUrl.trim() === ""}
          className={buttonClass("primary")}
        >
          {saving ? "서버에 닿아 보는 중..." : "확인하고 저장"}
        </button>
      </div>
      {error ? (
        <ErrorNote>
          <span id="scoring-server-error" data-testid="scoring-server-error">
            {error}
          </span>
        </ErrorNote>
      ) : null}
    </form>
  );
}

export function ScoringConnectionSection({
  classroom,
  isOwner,
  onSaved,
}: {
  classroom: ClassRow;
  isOwner: boolean;
  onSaved: () => void;
}) {
  const compatible = classroom.has_openai_key && classroom.scoring_connection_kind === "compatible_server";
  // 호환 서버 폼은 「호환 서버」를 누르거나(새로 잇기), 호환 서버 연결의 「바꾸기」로 열린다.
  const [compatibleOpen, setCompatibleOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  // 저장·삭제 결과를 늘 떠 있는 상태 영역으로 알린다 — 폼이 사라지는 동작이라 결과가 눈에도 귀에도 남아야 한다.
  const [notice, setNotice] = useState("");
  const statusRef = useRef<HTMLDivElement>(null);
  // 시행일 전에는(#803) Claude 키 줄을 보이지 않는다 — 이미 넣어 둔 키가 있으면 보인다.
  const showClaude = classroom.anthropic_key_selectable || classroom.anthropic_key !== null;

  async function handleSwitch(kind: VendorKind) {
    setSwitching(true);
    setSwitchError(null);
    const result = await switchScoringVendor(classroom.id, kind);
    setSwitching(false);
    if (result.ok) onSaved();
    else setSwitchError(result.detail);
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div ref={statusRef} tabIndex={-1} className="min-w-0 focus:outline-none focus-visible:ring-1 focus-visible:ring-ink">
          <ConnectionStatus classroom={classroom} />
        </div>
        {!isOwner ? (
          <span data-testid="openai-key-owner-only">
            <Badge>소유자만</Badge>
          </span>
        ) : compatible ? (
          <button
            type="button"
            data-testid="scoring-connection-change"
            aria-expanded={compatibleOpen}
            onClick={() => setCompatibleOpen((value) => !value)}
            className={buttonClass("secondary", "sm")}
          >
            {compatibleOpen ? "닫기" : "바꾸기"}
          </button>
        ) : null}
      </div>
      <p role="status" data-testid="scoring-connection-notice" className="text-[12.5px] text-ink/60 empty:hidden">
        {notice}
      </p>
      {isOwner ? (
        <div className="flex flex-col gap-4 border-t border-rule pt-4">
          <VendorSwitch
            classroom={classroom}
            compatibleOpen={compatibleOpen && !compatible}
            busy={switching}
            onSwitch={handleSwitch}
            onCompatible={() => setCompatibleOpen((value) => !value)}
          />
          {switchError ? (
            <ErrorNote>
              <span data-testid="scoring-vendor-error">{switchError}</span>
            </ErrorNote>
          ) : null}
          {compatibleOpen ? (
            <div className="flex flex-col gap-2.5">
              {!compatible && classroom.openai_key ? (
                <p data-testid="scoring-connection-switch-note" className="text-[12.5px] text-warning">
                  호환 서버를 저장하면 OpenAI 키가 지워집니다.
                </p>
              ) : null}
              <CompatibleServerForm
                classroom={classroom}
                onSaved={() => {
                  setCompatibleOpen(false);
                  // 서버 폼이 닫히며 저장 단추가 사라진다 — 초점은 연결 상태로.
                  statusRef.current?.focus();
                  setNotice("호환 서버를 저장했습니다.");
                  onSaved();
                }}
              />
            </div>
          ) : null}
          <VendorKeyRow classroom={classroom} provider="openai" onSaved={onSaved} announce={setNotice} />
          {showClaude ? <VendorKeyRow classroom={classroom} provider="anthropic" onSaved={onSaved} announce={setNotice} /> : null}
        </div>
      ) : null}
    </div>
  );
}
