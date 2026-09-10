"use client";

// 채점 설정 (#284/#285). 강사 본인의 채점 키를 넣고, 클래스 기본 채점
// 모델을 고른다. 키는 저장 뒤 마스킹된 형태로만 보인다 — 평문은 다시
// 보여주지 않는다.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { BackendError } from "@/lib/backend/client";
import { setOpenAIKey, updateClass } from "@/lib/classes/api";
import { useClass } from "@/lib/classes/use-class";
import { useScoringModels } from "@/lib/scoring/use-scoring-models";

export default function ClassScoringSettingsPage() {
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

  const [tokenBudget, setTokenBudget] = useState("");
  const [warningThreshold, setWarningThreshold] = useState("");
  const [budgetSaving, setBudgetSaving] = useState(false);
  const [budgetError, setBudgetError] = useState<string | null>(null);

  useEffect(() => {
    if (state.status === "ready") {
      setDefaultModel(state.classroom.default_model);
      setTokenBudget(
        state.classroom.token_budget === null ? "" : String(state.classroom.token_budget),
      );
      setWarningThreshold(String(state.classroom.token_budget_warning_threshold_percent));
    }
  }, [state]);

  if (state.status === "loading") {
    return (
      <main>
        <p data-testid="scoring-settings-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "notFound") {
    return (
      <main>
        <h1 data-testid="scoring-settings-not-found">클래스를 찾을 수 없습니다</h1>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main>
        <p data-testid="scoring-settings-error">클래스 정보를 불러오지 못했습니다.</p>
      </main>
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
      setBudgetError("경고 임계는 1~100 사이의 정수여야 합니다.");
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
    <main>
      <p>
        <Link href={`/classes/${classId}`}>{classroom.name}(으)로 돌아가기</Link>
      </p>
      <h1>채점 설정</h1>

      <section>
        <h2>채점 키</h2>
        {classroom.has_openai_key ? (
          <p data-testid="openai-key-status">
            설정됨 ({classroom.openai_key_masked})
          </p>
        ) : (
          <p data-testid="openai-key-status">
            아직 설정되지 않았습니다 — 키가 없으면 이 클래스의 제출은 채점되지 않습니다.
          </p>
        )}

        <form onSubmit={handleKeySubmit}>
          <label htmlFor="openai-api-key">새 채점 키</label>
          <input
            id="openai-api-key"
            data-testid="openai-key-input"
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            required
          />
          <button type="submit" data-testid="openai-key-submit" disabled={keySaving || apiKey.trim() === ""}>
            {keySaving ? "저장하는 중..." : "저장"}
          </button>
        </form>
        {keyError ? <p data-testid="openai-key-error">{keyError}</p> : null}
      </section>

      <section>
        <h2>기본 채점 모델</h2>
        <p>문제가 자기 모델을 따로 갖지 않으면 이 값을 씁니다.</p>

        {modelsState.status === "loading" ? (
          <p data-testid="scoring-models-loading">불러오는 중...</p>
        ) : modelsState.status === "error" ? (
          <p data-testid="scoring-models-error">모델 목록을 불러오지 못했습니다.</p>
        ) : (
          <form onSubmit={handleModelSubmit}>
            <label htmlFor="class-default-model">기본 모델</label>
            <select
              id="class-default-model"
              data-testid="class-default-model-select"
              value={defaultModel}
              onChange={(event) => setDefaultModel(event.target.value)}
            >
              {modelsState.models.map((model) => (
                <option key={model.id} value={model.id} data-testid={`scoring-model-option-${model.id}`}>
                  {model.label} · 컨텍스트 {model.context_window.toLocaleString("ko-KR")} 토큰
                </option>
              ))}
            </select>
            <button type="submit" data-testid="class-default-model-submit" disabled={modelSaving}>
              {modelSaving ? "저장하는 중..." : "저장"}
            </button>
          </form>
        )}
        {modelError ? <p data-testid="class-default-model-error">{modelError}</p> : null}
      </section>

      <section>
        <h2>채점 예산</h2>
        <p>
          이 클래스의 채점이 강사님의 채점 키로 쓰는 토큰에 상한을 둡니다 —
          한도에 닿으면 새 채점이 멈추고, 제출은 그대로 쌓여 예산을 채우면
          순서대로 이어서 채점됩니다.
        </p>

        {classroom.token_budget === null ? (
          <p data-testid="token-budget-status">예산이 설정되지 않았습니다 — 채점 사용량에 상한이 없습니다.</p>
        ) : (
          <p data-testid="token-budget-status">
            사용량 {classroom.token_usage_total.toLocaleString("ko-KR")} /{" "}
            {classroom.token_budget.toLocaleString("ko-KR")} 토큰 · 남은 양{" "}
            {(classroom.token_budget_remaining ?? 0).toLocaleString("ko-KR")} 토큰
            {classroom.token_budget_exhausted ? (
              <strong data-testid="token-budget-exhausted-badge"> · 채점 정지 중(예산 소진)</strong>
            ) : null}
          </p>
        )}

        <form onSubmit={handleBudgetSubmit}>
          <label htmlFor="token-budget-input">예산 한도(토큰)</label>
          <input
            id="token-budget-input"
            data-testid="token-budget-input"
            type="number"
            min={1}
            step={1}
            value={tokenBudget}
            onChange={(event) => setTokenBudget(event.target.value)}
            placeholder="예: 1000000"
          />
          <label htmlFor="token-budget-warning-threshold-input">경고 임계(%)</label>
          <input
            id="token-budget-warning-threshold-input"
            data-testid="token-budget-warning-threshold-input"
            type="number"
            min={1}
            max={100}
            step={1}
            value={warningThreshold}
            onChange={(event) => setWarningThreshold(event.target.value)}
          />
          <button
            type="submit"
            data-testid="token-budget-submit"
            disabled={budgetSaving || tokenBudget.trim() === ""}
          >
            {budgetSaving ? "저장하는 중..." : "저장"}
          </button>
        </form>
        {budgetError ? <p data-testid="token-budget-error">{budgetError}</p> : null}
      </section>
    </main>
  );
}
