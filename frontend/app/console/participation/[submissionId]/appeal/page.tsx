"use client";

// 이의 제기 화면 (#74) — Developer 가 채점 결과를 보고, 이의를 걸고, 자기 소스가
// 몇 번 열렸는지 확인한다.
//
// **채점 결과가 먼저 온다.** 무엇에 이의를 제기하는지 보지 못한 채 사유를 쓰라고
// 하는 화면은 화면이 아니다. 그래서 이 화면을 짜다가 "Developer 가 자기 점수를
// 볼 방법이 없다"는 구멍을 먼저 메웠다.
//
// **열람 기록은 약속의 증거다**(ADR-0022). 운영자는 심판을 위해 소스를 읽을 수
// 있고, 대신 읽을 때마다 기록이 남는다. 그 기록을 제출자 본인이 볼 수 있어야
// 약속이 검증 가능해진다 — 그래서 이의를 아직 걸지 않았어도 여기 있다.
// 운영자의 이름은 주지 않는다: 시각과 횟수만으로 약속은 검증된다.
import Link from "next/link";
import { use, useState } from "react";

import { ErrorNote, INPUT_CLASS, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
import { useSession } from "@/lib/auth/use-session";
import {
  submitAppeal,
  useAppealPage,
  type Appeal,
  type OwnScore,
  type SourceReading,
} from "@/lib/appeals/use-appeal-page";
import { HiddenSummaryLine, modelLineOf } from "@/lib/submissions/score-summary";
import { formatPoints, formatQualityTotal, type SubmissionQuality } from "@/lib/submissions/quality";
import { badgeClass } from "@/lib/ui/classnames";

const APPEAL_STATUS_LABELS: Record<string, string> = {
  pending: "심판을 기다리는 중입니다",
  upheld: "이의가 받아들여졌습니다",
  rejected: "이의가 기각되었습니다",
};

export default function AppealPage({ params }: { params: Promise<{ submissionId: string }> }) {
  const { submissionId } = use(params);
  const session = useSession();
  const { state, reload } = useAppealPage(submissionId);

  // 세션이 죽었는지를 로딩 게이트보다 **먼저** 본다 — 반대로 두면 만료 시
  // 영원히 "불러오는 중"에 갇힌다(#69).
  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || state.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="appeal-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <PageShell>
      <Link className="text-sm text-ink/60" href="/console/participation" data-testid="appeal-back">
        ← 내 참가 현황
      </Link>
      <PageHeader title="채점 결과와 이의 제기" titleTestId="appeal-heading" />

      {state.status === "error" ? (
        <ErrorNote>
          <span data-testid="appeal-error">채점 결과를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.</span>
        </ErrorNote>
      ) : state.score === null ? (
        // 채점 전이다. 이의를 걸 대상이 아직 없다 — 실패가 아니라 순서다.
        <p className="mt-6" data-testid="appeal-not-scored">
          아직 채점되지 않았습니다. 채점이 끝나면 결과와 함께 이의를 제기할 수 있습니다.
        </p>
      ) : (
        <>
          <ScoreSection score={state.score} />
          {/* 완성도(#884, ADR-0072) — 본인 것만 온다. 등수는 남의 제출과 견준 값이라 없다. 이의 대상이 아니다. */}
          {state.score.quality ? <QualitySection quality={state.score.quality} /> : null}
          {state.appeal ? (
            <ExistingAppeal appeal={state.appeal} />
          ) : state.score.is_free ? (
            // 무료 공모전(#417, ADR-0048)에는 이의제기 절차 자체가 없다 —
            // 「기한이 지났다」(아래 appeal-closed 분기)와는 다른 사실이라
            // 다른 문구로 말한다.
            <p className="mt-8 text-ink/60" data-testid="appeal-not-available-free">
              무료 공모전에는 이의제기 절차가 없습니다.
            </p>
          ) : state.score.can_appeal ? (
            <AppealForm submissionId={submissionId} onSubmitted={reload} />
          ) : (
            // **폼이 없는 이유를 말한다.** 버튼이 그냥 없으면 "왜 없지"가
            // 남고, 사용자는 자기 잘못인지 고장인지 모른다. 낼 수 있는지는
            // 서버가 판정한다 — `create_appeal` 의 전제와 같은 함수다.
            <p className="mt-8 text-ink/60" data-testid="appeal-closed">
              이의 제기 기한(심사기간 종료)이 지나 더 이상 접수할 수 없습니다.
            </p>
          )}
          <ReadingsSection readings={state.readings} failed={state.readingsFailed} />
        </>
      )}
    </PageShell>
  );
}

function ScoreSection({ score }: { score: OwnScore }) {
  return (
    <section className="mt-6" data-testid="appeal-score">
      <p className="text-lg">
        필수 요건 달성률{" "}
        <strong data-testid="appeal-score-percentage">{score.percentage}%</strong>
      </p>
      {/* 자동 0%(ADR-0030/0031)는 AI가 판정하지 않았다 — 내부 표식 문자열
          (`model_version`의 sentinel)을 그대로 보여주지 않는다(#251).
          `scoring_basis`로만 갈린다 — `submit-score-model`과 같은 함수
          (`modelLineOf`)를 써서 두 화면이 같은 사유를 말하게 한다. */}
      <p className="text-sm text-ink/60" data-testid="appeal-score-model">
        {modelLineOf(score)}
      </p>

      {/* 근거가 없으면 이의를 쓸 수 없다 — 무엇을 반박할지 모른다. */}
      {/* **기한이 화면에 있을 사실이어야 한다**(#74 스토리 15). 기한을 만들어
          놓고 적지 않으면 그것은 달력을 들고 계산한 사람에게만 유리한 함정이
          된다. */}
      {score.appeal_deadline ? (
        <p className="mt-2 text-sm" data-testid="appeal-deadline">
          이의 제기 기한 {new Date(score.appeal_deadline).toLocaleString("ko-KR")}
        </p>
      ) : null}

      <div className="mt-3">
        <HiddenSummaryLine summary={score.hidden_summary} testId="appeal-hidden-summary" />
      </div>
      <ul className="mt-3 flex flex-col gap-2" data-testid="appeal-score-reasoning">
        {score.reasoning.map((item, index) => (
          <li key={index} className="border border-rule bg-surface p-3 text-sm">
            {String(item.reasoning ?? "")}
          </li>
        ))}
      </ul>
    </section>
  );
}

function QualitySection({ quality }: { quality: SubmissionQuality }) {
  return (
    <section className="mt-6" data-testid="own-quality">
      <p className="text-lg">
        완성도 <strong data-testid="own-quality-completeness">{formatQualityTotal(quality.total, quality.max_total)}</strong>
      </p>
      <ul className="mt-3 flex flex-col gap-2" data-testid="own-quality-items">
        {quality.items.map((item) => (
          <li key={item.item_id} className="border border-rule bg-surface p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className={badgeClass(item.required ? "attention" : "neutral")}>
                {item.bonus ? "가산" : item.required ? "필수" : "선택"}
              </span>
              <span>{item.label}</span>
              <span className="ml-auto font-mono" data-testid={`own-quality-item-${item.item_id}`}>
                {item.score}/5 · {formatPoints(item.item_points)} / {item.points}점
              </span>
            </div>
            {item.hidden ? null : <p className="mt-1 text-ink/70">{item.reasoning}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ExistingAppeal({ appeal }: { appeal: Appeal }) {
  return (
    <section className="mt-8 border border-rule bg-surface p-4" data-testid="appeal-existing">
      {/* 한 Submission 에 이의는 하나다 — 폼 대신 낸 것을 보여준다. */}
      <p className="font-semibold" data-testid="appeal-existing-status">
        {APPEAL_STATUS_LABELS[appeal.status] ?? appeal.status}
      </p>
      <p className="mt-2 whitespace-pre-wrap text-sm" data-testid="appeal-existing-reason">
        {appeal.reason}
      </p>
      {appeal.ruling_note ? (
        <p className="mt-3 whitespace-pre-wrap text-sm text-ink/60" data-testid="appeal-existing-note">
          심판 의견: {appeal.ruling_note}
        </p>
      ) : null}
      {/* **내 이의가 배분을 붙잡고 있다**(#74). 침묵은 상금이 사라진 것으로
          읽힌다(ADR-0020) — 왜 아직 안 움직이는지, 그리고 사라진 게 아니라는
          것을 여기서 말한다. */}
      {appeal.is_holding_distribution ? (
        <p className="mt-3 text-sm" data-testid="appeal-existing-holding">
          이 이의가 심판될 때까지 이 공모전의 상금 배분은 진행되지 않습니다. 상금은 그대로
          남아 있습니다.
        </p>
      ) : null}

      {appeal.correction_amount != null ? (
        <p className="mt-2 text-sm" data-testid="appeal-existing-correction">
          정정 금액 {appeal.correction_amount.toLocaleString()}원
        </p>
      ) : null}
    </section>
  );
}

function AppealForm({
  submissionId,
  onSubmitted,
}: {
  submissionId: string;
  onSubmitted: () => void;
}) {
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setMessage(null);

    const result = await submitAppeal(submissionId, reason);
    if (result.ok) {
      // **낙관적 갱신을 하지 않는다** — 서버에서 다시 읽는다. 이의는 되돌릴 수
      // 없어서, 접수됐다고 먼저 그렸다가 틀리면 낸 적 없는 이의를 봤다고 믿게
      // 된다.
      onSubmitted();
      return;
    }

    // 서버가 준 문구를 그대로 보여준다 — 기한이 지났다·이미 냈다는 다른
    // 사실이고, 화면이 짐작해 다시 쓰면 언젠가 갈라진다.
    setMessage(result.message);
    setPending(false);
  }

  return (
    <form className="mt-8 flex flex-col gap-3" onSubmit={handleSubmit} data-testid="appeal-form">
      <label className="text-sm" htmlFor="appeal-reason">
        어느 판정이 왜 잘못됐는지 적어주세요. 운영자가 이 글과 채점 근거를 함께 봅니다.
      </label>
      <textarea
        id="appeal-reason"
        className={`min-h-32 ${INPUT_CLASS}`}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        data-testid="appeal-reason"
        required
        maxLength={4000}
      />
      <button
        className={`self-start ${buttonClass("primary")}`}
        type="submit"
        disabled={pending || reason.trim().length === 0}
        data-testid="appeal-submit"
      >
        {pending ? "접수하는 중..." : "이의 제기"}
      </button>
      {message ? (
        <ErrorNote>
          <span data-testid="appeal-submit-error">{message}</span>
        </ErrorNote>
      ) : null}
    </form>
  );
}

function ReadingsSection({
  readings,
  failed,
}: {
  readings: SourceReading[];
  failed: boolean;
}) {
  return (
    <section className="mt-10 border-t border-rule pt-6" data-testid="appeal-readings">
      <h2 className="font-semibold">내 소스 열람 기록</h2>
      <p className="mt-1 text-sm text-ink/60">
        운영자는 이의를 심판하기 위해 제출 소스를 열어볼 수 있고, 열 때마다 아래에 기록이
        남습니다. 누가 읽었는지는 공개하지 않습니다 — 언제 몇 번 열렸는지만 보여줍니다.
      </p>

      {failed ? (
        // 열람 기록만 따로 실패할 수 있다. 그때 "0건"으로 보이면 "아무도 안
        // 봤다"는 거짓말이 된다 — 이 화면이 지키려는 약속이 정확히 그것이다.
        <ErrorNote>
          <span data-testid="appeal-readings-error">
            열람 기록을 불러오지 못했습니다. 「아무도 열지 않았다」는 뜻이 아닙니다.
          </span>
        </ErrorNote>
      ) : readings.length === 0 ? (
        <p className="mt-3 text-sm" data-testid="appeal-readings-empty">
          아직 아무도 열어보지 않았습니다.
        </p>
      ) : (
        <ul className="mt-3 flex flex-col gap-1 text-sm" data-testid="appeal-readings-list">
          {readings.map((reading, index) => (
            <li key={index} data-testid="appeal-readings-row">
              {new Date(reading.read_at).toLocaleString("ko-KR")}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
