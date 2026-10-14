"use client";

// 「채점 연결」(#601, CONTEXT.md 「채점 연결」) — 클래스 설정의 첫 구획(`#scoring-key`, 카드는 쪽이
// 감싼다). 이 클래스의 채점이 모델에 닿는 길을 소유자가 고른다: 「OpenAI 키」 또는 「호환 서버」(소유자가
// 바깥에 열어 둔 OpenAI 호환 주소와 Bearer 값). 상태 한 줄이 먼저 보이고(#636) 폼은 「바꾸기」 뒤에
// 열린다. 공동 강사는 상태 한 줄만 본다(ADR-0055).
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Badge, ErrorNote, FieldLabel, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import { setCompatibleServer, setOpenAIKey, type ClassRow } from "@/lib/classes/api";
import { formatDay } from "@/lib/classes/format-day";
import { checkOpenAIKeyFromBrowser, type OpenAIKeyCheckResult } from "@/lib/classes/openai-key-check";
import { settingsStatusBadges } from "@/lib/classes/scoring-status";

type ConnectionKind = ClassRow["scoring_connection_kind"];

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
  return (
    <p data-testid="openai-key-status" className={STATUS_CLASS}>
      {badges}
      <span>OpenAI 키</span>
      <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
      <VerifiedDay classroom={classroom} />
    </p>
  );
}

function KindChoice({ value, onChange }: { value: ConnectionKind; onChange: (kind: ConnectionKind) => void }) {
  const options: { kind: ConnectionKind; label: string }[] = [
    { kind: "openai_key", label: "OpenAI 키" },
    { kind: "compatible_server", label: "호환 서버" },
  ];
  return (
    <div role="radiogroup" aria-label="채점 연결" className="flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={option.kind}
          type="button"
          role="radio"
          aria-checked={value === option.kind}
          data-testid={`scoring-connection-kind-${option.kind}`}
          onClick={() => onChange(option.kind)}
          className={buttonClass(value === option.kind ? "primary" : "secondary")}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function OpenAIKeyForm({ classId, onSaved }: { classId: number; onSaved: () => void }) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 저장 전에 브라우저가 직접 벤더에게 물어 미리 말한다(#357) — 문이 아니라 안내다, 저장 버튼은
  // 이 값과 무관하게 항상 눌린다. 입력이 멎은 뒤 한 번만 친다.
  const [liveCheck, setLiveCheck] = useState<OpenAIKeyCheckResult | "checking" | "idle">("idle");

  useEffect(() => {
    const trimmed = apiKey.trim();
    if (trimmed === "") {
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
  }, [apiKey]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const result = await setOpenAIKey(classId, apiKey);
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
      <label htmlFor="openai-api-key">
        <FieldLabel>채점 키</FieldLabel>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          id="openai-api-key"
          data-testid="openai-key-input"
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          required
          className={`${INPUT_CLASS} min-w-[240px] flex-1 font-mono`}
          placeholder="sk-..."
        />
        <button
          type="submit"
          data-testid="openai-key-submit"
          disabled={saving || apiKey.trim() === ""}
          className={buttonClass("primary")}
        >
          {saving ? "저장하는 중..." : "저장"}
        </button>
      </div>
      {liveCheck === "checking" ? (
        <p data-testid="openai-key-live-check" className="text-[12px] text-ink/45">
          확인하는 중...
        </p>
      ) : liveCheck === "valid" ? (
        <p data-testid="openai-key-live-check">
          <Badge tone="verified">이 키를 쓸 수 있습니다</Badge>
        </p>
      ) : liveCheck === "invalid" ? (
        <p data-testid="openai-key-live-check">
          <Badge tone="attention">이 키는 쓸 수 없습니다</Badge>
        </p>
      ) : liveCheck === "unknown" ? (
        <p data-testid="openai-key-live-check">
          <Badge tone="neutral">지금은 확인할 수 없습니다</Badge>
        </p>
      ) : null}
      {error ? (
        <ErrorNote>
          <span data-testid="openai-key-error">{error}</span>
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
          <span data-testid="scoring-server-error">{error}</span>
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
  const [kind, setKind] = useState<ConnectionKind>(classroom.scoring_connection_kind);
  // 연결이 없으면 바꿀 것이 없다 — 폼이 처음부터 열려 있고, 있으면 「바꾸기」를 눌러야 열린다.
  const [open, setOpen] = useState(!classroom.has_openai_key);
  const switching = classroom.has_openai_key && kind !== classroom.scoring_connection_kind;
  const formOpen = isOwner && open;
  const handleSaved = () => {
    setOpen(false);
    onSaved();
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <ConnectionStatus classroom={classroom} />
        {!isOwner ? (
          <span data-testid="openai-key-owner-only">
            <Badge>소유자만</Badge>
          </span>
        ) : classroom.has_openai_key ? (
          <button
            type="button"
            data-testid="scoring-connection-change"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className={buttonClass("secondary", "sm")}
          >
            {open ? "닫기" : "바꾸기"}
          </button>
        ) : null}
      </div>
      {formOpen ? (
        <div className="flex flex-col gap-4 border-t border-rule pt-4">
          <KindChoice value={kind} onChange={setKind} />
          {switching ? (
            <p data-testid="scoring-connection-switch-note" className="text-[12.5px] text-attention">
              {kind === "compatible_server"
                ? "저장하면 지금의 OpenAI 키가 지워집니다."
                : "저장하면 지금의 호환 서버 주소와 인증 값이 지워집니다."}
            </p>
          ) : null}
          {kind === "openai_key" ? (
            <OpenAIKeyForm classId={classroom.id} onSaved={handleSaved} />
          ) : (
            <CompatibleServerForm classroom={classroom} onSaved={handleSaved} />
          )}
        </div>
      ) : null}
    </div>
  );
}
