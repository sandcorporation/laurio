"use client";

// 「채점 연결」(#601, CONTEXT.md 「채점 연결」) — 클래스 설정 「채점」 카드의 첫 구획. 이 클래스의
// 채점이 모델에 닿는 길을 소유자가 고른다: 「OpenAI 키」 또는 「호환 서버」(소유자가 바깥에 열어 둔
// OpenAI 호환 주소와 Bearer 값). 공동 강사는 지금 연결의 종류와 호스트만 본다(ADR-0055).
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Badge, CardSection, ErrorNote, FieldLabel, INPUT_CLASS, Note, buttonClass } from "@/app/components/ui";
import { setCompatibleServer, setOpenAIKey, type ClassRow } from "@/lib/classes/api";
import { checkOpenAIKeyFromBrowser, type OpenAIKeyCheckResult } from "@/lib/classes/openai-key-check";

type ConnectionKind = ClassRow["scoring_connection_kind"];

const STATUS_CLASS = "flex flex-wrap items-center gap-2.5 text-[13.5px]";

function ConnectionStatus({ classroom }: { classroom: ClassRow }) {
  if (!classroom.has_openai_key) {
    return (
      <p data-testid="openai-key-status" className={STATUS_CLASS}>
        <Badge tone="attention">없음</Badge>
        <span className="text-ink/60">채점 연결이 없으면 이 클래스의 제출은 채점되지 않습니다.</span>
      </p>
    );
  }
  if (classroom.scoring_connection_kind === "compatible_server") {
    return (
      <p data-testid="scoring-connection-status" className={STATUS_CLASS}>
        {classroom.openai_key_status === "rejected" ? (
          <Badge tone="attention">거부됨</Badge>
        ) : classroom.scoring_server_unreachable ? (
          <Badge tone="attention">연결 불가</Badge>
        ) : (
          <Badge tone="verified">호환 서버</Badge>
        )}
        <span data-testid="scoring-server-host" className="font-mono text-ink/70">
          {classroom.scoring_server_host}
        </span>
        {classroom.scoring_auth_masked ? (
          <span className="font-mono text-ink/50">{classroom.scoring_auth_masked}</span>
        ) : null}
        {classroom.openai_key_status === "rejected" ? (
          <span className="text-ink/60">
            서버가 인증 값을 거절했습니다 — 다시 저장해야 채점이 다시 시작됩니다.
          </span>
        ) : classroom.scoring_server_unreachable ? (
          <span className="text-ink/60">
            이 서버에 닿지 않아 채점이 멈췄습니다 — 서버를 살린 뒤 다시 저장하면 바로 이어지고, 저장하지
            않아도 10분 안에 다시 확인해 이어집니다.
          </span>
        ) : null}
      </p>
    );
  }
  if (classroom.openai_key_status === "rejected") {
    return (
      <p data-testid="openai-key-status" className={STATUS_CLASS}>
        <Badge tone="attention">거부됨</Badge>
        <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
        <span className="text-ink/60">벤더가 이 키를 거절했습니다 — 새 키를 저장해야 채점이 다시 시작됩니다.</span>
      </p>
    );
  }
  if (classroom.scoring_quota_exhausted) {
    return (
      <p data-testid="openai-key-status" className={STATUS_CLASS}>
        <Badge tone="attention">크레딧 소진</Badge>
        <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
        <span className="text-ink/60">
          이 키의 OpenAI 크레딧이 떨어져 채점이 멈췄습니다 — 충전한 뒤 키를 다시 저장하면 바로 이어지고,
          저장하지 않아도 10분 안에 다시 확인해 이어집니다.
        </span>
      </p>
    );
  }
  if (classroom.openai_key_status === "unverified") {
    return (
      <p data-testid="openai-key-status" className={STATUS_CLASS}>
        <Badge tone="neutral">미검증</Badge>
        <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
        <span className="text-ink/60">
          저장할 때 벤더에 닿지 못해 확인하지 못했습니다 — 채점 시도에서 다시 확인됩니다.
        </span>
      </p>
    );
  }
  return (
    <p data-testid="openai-key-status" className="flex items-center gap-2.5 text-[13.5px]">
      <Badge tone="verified">OpenAI 키</Badge>
      <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
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
        <FieldLabel>새 채점 키</FieldLabel>
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
      <span className="text-[11.5px] leading-relaxed text-ink/45">
        저장 뒤에는 다시 볼 수 없습니다 — 화면에도 로그에도 남지 않고, 채점 요청을 보낼 때만 복호화됩니다.
        참여자에게는 어떤 형태로도 보이지 않습니다.
      </span>
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
          placeholder="인증을 받지 않는 서버면 비워 두세요"
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
      <span className="text-[11.5px] leading-relaxed text-ink/45">
        https 이고 바깥에서 열려 있는 서버만 받습니다. 저장할 때 서버에 한 번 닿아 모델 목록을 받아 보고,
        학생의 소스는 채점할 때 이 서버로 갑니다. 인증 값은 저장 뒤에 다시 볼 수 없습니다.
      </span>
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
  const switching = classroom.has_openai_key && kind !== classroom.scoring_connection_kind;

  return (
    <CardSection id="scoring-key" title="채점 연결" hint="이 클래스의 채점이 모델에 닿는 길입니다">
      <div className="flex flex-col gap-4 p-4">
        <ConnectionStatus classroom={classroom} />
        {!isOwner ? (
          <Note>
            <span data-testid="openai-key-owner-only">
              채점 연결은 소유자만 바꿀 수 있습니다 — 채점 비용이 소유자의 몫입니다.
            </span>
          </Note>
        ) : (
          <>
            <KindChoice value={kind} onChange={setKind} />
            {switching ? (
              <Note>
                <span data-testid="scoring-connection-switch-note">
                  {kind === "compatible_server"
                    ? "호환 서버를 저장하면 지금의 OpenAI 키는 지워집니다."
                    : "OpenAI 키를 저장하면 지금의 호환 서버 주소와 인증 값은 지워집니다."}
                </span>
              </Note>
            ) : null}
            {kind === "openai_key" ? (
              <OpenAIKeyForm classId={classroom.id} onSaved={onSaved} />
            ) : (
              <CompatibleServerForm classroom={classroom} onSaved={onSaved} />
            )}
          </>
        )}
      </div>
    </CardSection>
  );
}
