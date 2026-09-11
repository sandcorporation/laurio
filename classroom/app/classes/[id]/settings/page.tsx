"use client";

// 클래스 설정 (#284/#285/#323). 「채점 설정」이던 이름이 넓어졌다 — 강사 본인의
// 채점 키를 넣고 클래스 기본 채점 모델을 고르는 일 말고도, 채점과 무관한 강사
// 이름과(#299) 클래스를 템플릿으로 공개하는 일(#319)까지 이 화면 하나가 담는다.
// 키는 저장 뒤 마스킹된 형태로만 보인다 — 평문은 다시 보여주지 않는다.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  Badge,
  Card,
  CardHeader,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  Num,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { BackendError } from "@/lib/backend/client";
import { publishClassAsTemplate, takedownClassTemplate, type ClassTemplateRow } from "@/lib/class-templates/api";
import { setOpenAIKey, updateClass } from "@/lib/classes/api";
import { useClass } from "@/lib/classes/use-class";
import { useScoringModels } from "@/lib/scoring/use-scoring-models";

function ClassTemplatePublishCard() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);

  const [publisherDisplayName, setPublisherDisplayName] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [publishedTemplate, setPublishedTemplate] = useState<ClassTemplateRow | null>(null);

  const [takingDown, setTakingDown] = useState(false);
  const [takedownError, setTakedownError] = useState<string | null>(null);

  async function handlePublish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPublishError(null);
    setPublishing(true);
    try {
      const template = await publishClassAsTemplate(classId, publisherDisplayName.trim());
      setPublishedTemplate(template);
    } catch {
      setPublishError("템플릿으로 공개하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setPublishing(false);
    }
  }

  async function handleTakedown() {
    if (!publishedTemplate) return;
    setTakedownError(null);
    setTakingDown(true);
    try {
      const template = await takedownClassTemplate(publishedTemplate.share_code);
      setPublishedTemplate(template);
    } catch {
      setTakedownError("내리지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setTakingDown(false);
    }
  }

  return (
    <Card>
      <CardHeader title="클래스를 템플릿으로 공개" hint="문제와 순서까지 통째로 다른 강사에게 공유" />
      <div className="flex flex-col gap-2.5 p-4">
        {publishedTemplate ? (
          <div className="flex flex-col gap-2">
            {publishedTemplate.taken_down ? (
              <p data-testid="publish-class-template-taken-down" className="flex items-center gap-2.5 text-[13px]">
                <Badge tone="neutral">내려짐</Badge>
                <span className="text-ink/60">더 이상 다른 강사가 가져갈 수 없습니다.</span>
              </p>
            ) : (
              <>
                <p data-testid="publish-class-template-done" className="text-[13px] leading-relaxed">
                  공개되었습니다. 아래 주소를 다른 강사에게 전달하세요.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/class-templates/${publishedTemplate.share_code}`}
                    data-testid="publish-class-template-share-link"
                    className="min-w-0 flex-1 break-all border border-rule bg-surface px-3 py-2 font-mono text-[12.5px] hover:underline"
                  >
                    /class-templates/{publishedTemplate.share_code}
                  </Link>
                  <button
                    type="button"
                    data-testid="publish-class-template-takedown"
                    onClick={handleTakedown}
                    disabled={takingDown}
                    className={buttonClass("danger", "sm")}
                  >
                    {takingDown ? "내리는 중..." : "내리기"}
                  </button>
                </div>
              </>
            )}
            {takedownError ? (
              <ErrorNote>
                <span data-testid="publish-class-template-takedown-error">{takedownError}</span>
              </ErrorNote>
            ) : null}
          </div>
        ) : (
          <form onSubmit={handlePublish} className="flex flex-col gap-2.5">
            <label htmlFor="publish-class-template-name">
              <FieldLabel>공개할 때 보일 이름</FieldLabel>
            </label>
            <input
              id="publish-class-template-name"
              data-testid="publish-class-template-name-input"
              value={publisherDisplayName}
              onChange={(event) => setPublisherDisplayName(event.target.value)}
              required
              placeholder="계정 이름과 달라도 됩니다"
              className={INPUT_CLASS}
            />
            <button
              type="submit"
              data-testid="publish-class-template-submit"
              disabled={publishing || publisherDisplayName.trim() === ""}
              className={buttonClass("secondary")}
            >
              {publishing ? "공개하는 중..." : "클래스를 템플릿으로 공개"}
            </button>
          </form>
        )}
        {publishError ? (
          <ErrorNote>
            <span data-testid="publish-class-template-error">{publishError}</span>
          </ErrorNote>
        ) : null}
        <span className="text-[11.5px] leading-relaxed text-ink/45">
          공개하는 순간 문제와 그 순서, 체크리스트까지 통째로 사본이 떠집니다 — 이후 이
          클래스를 고치거나 지워도 템플릿은 그대로입니다. 참여자·제출물·판정·가입 코드·채점
          키·채점 모델은 담기지 않습니다.
        </span>
      </div>
    </Card>
  );
}

export default function ClassSettingsPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state, reload } = useClass(classId);
  const modelsState = useScoringModels();

  const [apiKey, setApiKey] = useState("");
  const [keySaving, setKeySaving] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);

  const [defaultModel, setDefaultModel] = useState("");
  const [modelSaving, setModelSaving] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  const [instructorDisplayName, setInstructorDisplayName] = useState("");
  const [nameSaving, setNameSaving] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);

  const [tokenBudget, setTokenBudget] = useState("");
  const [warningThreshold, setWarningThreshold] = useState("");
  const [budgetSaving, setBudgetSaving] = useState(false);
  const [budgetError, setBudgetError] = useState<string | null>(null);

  useEffect(() => {
    if (state.status === "ready") {
      setDefaultModel(state.classroom.default_model);
      setInstructorDisplayName(state.classroom.instructor_display_name);
      setTokenBudget(
        state.classroom.token_budget === null ? "" : String(state.classroom.token_budget),
      );
      setWarningThreshold(String(state.classroom.token_budget_warning_threshold_percent));
    }
  }, [state]);

  if (state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="class-settings-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
      </PageShell>
    );
  }

  if (state.status === "notFound") {
    return (
      <PageShell>
        <h1 data-testid="class-settings-not-found" className="text-[22px] font-semibold">클래스를 찾을 수 없습니다</h1>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="class-settings-error">클래스 정보를 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const { classroom } = state;

  async function handleKeySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setKeySaving(true);
    setKeyError(null);
    try {
      await setOpenAIKey(classId, apiKey);
      setApiKey("");
      reload();
    } catch (err) {
      setKeyError(err instanceof BackendError ? err.message : "키를 저장하지 못했습니다.");
    } finally {
      setKeySaving(false);
    }
  }

  async function handleNameSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNameSaving(true);
    setNameError(null);
    try {
      await updateClass(classId, { instructor_display_name: instructorDisplayName.trim() });
      reload();
    } catch (err) {
      setNameError(err instanceof BackendError ? err.message : "강사 이름을 저장하지 못했습니다.");
    } finally {
      setNameSaving(false);
    }
  }

  async function handleModelSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setModelSaving(true);
    setModelError(null);
    try {
      await updateClass(classId, { default_model: defaultModel });
      reload();
    } catch (err) {
      setModelError(err instanceof BackendError ? err.message : "기본 모델을 저장하지 못했습니다.");
    } finally {
      setModelSaving(false);
    }
  }

  async function handleBudgetSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedBudget = Number(tokenBudget);
    const parsedThreshold = Number(warningThreshold);
    if (!Number.isInteger(parsedBudget) || parsedBudget < 1) {
      setBudgetError("예산 한도는 1 이상의 정수여야 합니다.");
      return;
    }
    if (!Number.isInteger(parsedThreshold) || parsedThreshold < 1 || parsedThreshold > 100) {
      setBudgetError("경고 기준은 1~100 사이의 정수여야 합니다.");
      return;
    }
    setBudgetSaving(true);
    setBudgetError(null);
    try {
      await updateClass(classId, {
        token_budget: parsedBudget,
        token_budget_warning_threshold_percent: parsedThreshold,
      });
      reload();
    } catch (err) {
      setBudgetError(err instanceof BackendError ? err.message : "채점 예산을 저장하지 못했습니다.");
    } finally {
      setBudgetSaving(false);
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow={classroom.name}
        title="클래스 설정"
        description="강사 이름·채점 키와 모델·예산, 템플릿 공개까지 이 클래스의 설정을 여기서 관리합니다."
        actions={
          <Link href={`/classes/${classId}`} className={buttonClass()}>
            클래스로 돌아가기
          </Link>
        }
      />

      <div className="flex max-w-[820px] flex-col gap-5">
        <Card>
          <CardHeader title="강사 이름" hint="가입 미리보기에서 이 이름으로 보입니다" />
          <div className="flex flex-col gap-3 p-4">
            <form onSubmit={handleNameSubmit} className="flex flex-col gap-2.5">
              <label htmlFor="class-instructor-display-name-input">
                <FieldLabel>이 클래스에서 불릴 이름</FieldLabel>
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  id="class-instructor-display-name-input"
                  data-testid="class-instructor-display-name-input"
                  value={instructorDisplayName}
                  onChange={(event) => setInstructorDisplayName(event.target.value)}
                  required
                  className={`${INPUT_CLASS} min-w-[240px] flex-1`}
                />
                <button
                  type="submit"
                  data-testid="class-instructor-display-name-submit"
                  disabled={nameSaving || instructorDisplayName.trim() === ""}
                  className={buttonClass("primary")}
                >
                  {nameSaving ? "저장하는 중..." : "저장"}
                </button>
              </div>
              <span className="text-[11.5px] leading-relaxed text-ink/45">
                참여자 명단과 제출물에 보이는 이름과는 별개입니다 — 그곳은 참여자 본인이 정한
                이름을 그대로 씁니다.
              </span>
            </form>
            {nameError ? (
              <ErrorNote>
                <span data-testid="class-instructor-display-name-error">{nameError}</span>
              </ErrorNote>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardHeader title="채점 키" hint="이 클래스의 채점에만 쓰입니다" />
          <div className="flex flex-col gap-4 p-4">
            {classroom.has_openai_key ? (
              <p data-testid="openai-key-status" className="flex items-center gap-2.5 text-[13.5px]">
                <Badge tone="verified">설정됨</Badge>
                <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
              </p>
            ) : (
              <p data-testid="openai-key-status" className="flex flex-wrap items-center gap-2.5 text-[13.5px]">
                <Badge tone="attention">없음</Badge>
                <span className="text-ink/60">키가 없으면 이 클래스의 제출은 채점되지 않습니다.</span>
              </p>
            )}

            <form onSubmit={handleKeySubmit} className="flex flex-col gap-2.5">
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
                  disabled={keySaving || apiKey.trim() === ""}
                  className={buttonClass("primary")}
                >
                  {keySaving ? "저장하는 중..." : "저장"}
                </button>
              </div>
              <span className="text-[11.5px] leading-relaxed text-ink/45">
                저장 뒤에는 다시 볼 수 없습니다 — 화면에도 로그에도 남지 않고, 채점 요청을 보낼
                때만 복호화됩니다. 참여자에게는 어떤 형태로도 보이지 않습니다.
              </span>
            </form>
            {keyError ? (
              <ErrorNote>
                <span data-testid="openai-key-error">{keyError}</span>
              </ErrorNote>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardHeader title="기본 채점 모델" hint="문제가 자기 모델을 갖지 않으면 이 값을 씁니다" />
          <div className="flex flex-col gap-3 p-4">
            {modelsState.status === "loading" ? (
              <p data-testid="scoring-models-loading" className="text-[13px] text-ink/45">
                불러오는 중...
              </p>
            ) : modelsState.status === "error" ? (
              <ErrorNote>
                <span data-testid="scoring-models-error">모델 목록을 불러오지 못했습니다.</span>
              </ErrorNote>
            ) : (
              <form onSubmit={handleModelSubmit} className="flex flex-col gap-2.5">
                <label htmlFor="class-default-model">
                  <FieldLabel>기본 모델</FieldLabel>
                </label>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    id="class-default-model"
                    data-testid="class-default-model-select"
                    value={defaultModel}
                    onChange={(event) => setDefaultModel(event.target.value)}
                    className={`${INPUT_CLASS} min-w-[280px] flex-1`}
                  >
                    {modelsState.models.map((model) => (
                      <option key={model.id} value={model.id} data-testid={`scoring-model-option-${model.id}`}>
                        {model.label} · 컨텍스트 {model.context_window.toLocaleString("ko-KR")} 토큰
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    data-testid="class-default-model-submit"
                    disabled={modelSaving}
                    className={buttonClass("primary")}
                  >
                    {modelSaving ? "저장하는 중..." : "저장"}
                  </button>
                </div>
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  모델마다 한 번에 받을 수 있는 소스의 양이 다릅니다 — 긴 문제에 작은 모델을 고르면
                  소스 뒷부분이 잘린 채 채점됩니다.
                </span>
              </form>
            )}
            {modelError ? (
              <ErrorNote>
                <span data-testid="class-default-model-error">{modelError}</span>
              </ErrorNote>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardHeader title="채점 예산" hint="한도에 닿으면 채점만 멈추고 제출은 쌓입니다" />
          <div className="flex flex-col gap-4 p-4">
            {classroom.token_budget === null ? (
              <p data-testid="token-budget-status" className="text-[13.5px] text-ink/60">
                예산이 설정되지 않았습니다 — 채점 사용량에 상한이 없습니다.
              </p>
            ) : (
              <div data-testid="token-budget-status" className="flex flex-col gap-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
                  <span className="text-ink/60">사용량</span>
                  <span className="font-mono">
                    {classroom.token_usage_total.toLocaleString("ko-KR")} /{" "}
                    {classroom.token_budget.toLocaleString("ko-KR")} 토큰
                  </span>
                </div>
                <div className="h-1.5 w-full border border-rule bg-paper">
                  <div
                    className={classroom.token_budget_exhausted ? "h-full bg-attention" : "h-full bg-ink"}
                    style={{
                      width: `${Math.min(
                        100,
                        Math.round((classroom.token_usage_total / classroom.token_budget) * 100),
                      )}%`,
                    }}
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2.5 text-[12.5px] text-ink/45">
                  <span>
                    남은 양{" "}
                    <Num className="text-ink/60">
                      {(classroom.token_budget_remaining ?? 0).toLocaleString("ko-KR")}
                    </Num>{" "}
                    토큰
                  </span>
                  {classroom.token_budget_exhausted ? (
                    <strong data-testid="token-budget-exhausted-badge" className="font-normal">
                      <Badge tone="attention">채점 정지 중 · 예산 소진</Badge>
                    </strong>
                  ) : null}
                </div>
              </div>
            )}

            <form onSubmit={handleBudgetSubmit} className="flex flex-col gap-3">
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex min-w-[200px] flex-1 flex-col gap-1.5">
                  <label htmlFor="token-budget-input">
                    <FieldLabel>예산 한도(토큰)</FieldLabel>
                  </label>
                  <input
                    id="token-budget-input"
                    data-testid="token-budget-input"
                    type="number"
                    min={1}
                    step={1}
                    value={tokenBudget}
                    onChange={(event) => setTokenBudget(event.target.value)}
                    placeholder="예: 1000000"
                    className={`${INPUT_CLASS} font-mono`}
                  />
                </div>
                <div className="flex w-[150px] flex-col gap-1.5">
                  <label htmlFor="token-budget-warning-threshold-input">
                    <FieldLabel>경고 기준(%)</FieldLabel>
                  </label>
                  <input
                    id="token-budget-warning-threshold-input"
                    data-testid="token-budget-warning-threshold-input"
                    type="number"
                    min={1}
                    max={100}
                    step={1}
                    value={warningThreshold}
                    onChange={(event) => setWarningThreshold(event.target.value)}
                    className={`${INPUT_CLASS} font-mono`}
                  />
                </div>
                <button
                  type="submit"
                  data-testid="token-budget-submit"
                  disabled={budgetSaving || tokenBudget.trim() === ""}
                  className={buttonClass("primary")}
                >
                  {budgetSaving ? "저장하는 중..." : "저장"}
                </button>
              </div>
              {budgetError ? (
                <ErrorNote>
                  <span data-testid="token-budget-error">{budgetError}</span>
                </ErrorNote>
              ) : null}
            </form>

            <Note>
              기준에 닿으면 <b className="text-ink">서비스 안 알림</b>으로 알립니다 — 메일이나 문자가
              아니라 이 서비스에 들어오면 보이는 알림입니다. 한도에 닿아도 제출은 계속 쌓이고,
              예산을 채우면 쌓인 시도부터 순서대로 이어서 채점됩니다.
            </Note>
          </div>
        </Card>

        <ClassTemplatePublishCard />
      </div>
    </PageShell>
  );
}
