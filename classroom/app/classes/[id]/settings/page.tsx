"use client";

// 클래스 설정 (#284/#285/#323). 「채점 설정」이던 이름이 넓어졌다 — 강사 본인의
// 채점 키를 넣고 클래스 기본 채점 모델을 고르는 일 말고도, 채점과 무관한 이름들
// (클래스 이름·강사 이름 #299)과 클래스를 템플릿으로 공개하는 일(#319)까지 이
// 화면 하나가 담는다. 카드는 「이름」 → 「채점」(키·기본 모델·예산 세 구획) →
// 템플릿 공개 → 삭제 순이다.
// 키는 저장 뒤 마스킹된 형태로만 보인다 — 평문은 다시 보여주지 않는다.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  Badge,
  Card,
  CardHeader,
  CardSection,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  Note,
  Num,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { publishClassAsTemplate, takedownClassTemplate } from "@/lib/class-templates/api";
import {
  deleteClass,
  renameMyInstructorName,
  setOpenAIKey,
  updateClass,
  type ClassRow,
  type PublishedClassTemplateSummary,
} from "@/lib/classes/api";
import { isDeleteConfirmationTyped } from "@/lib/classes/delete-confirmation";
import { classNamesPatch } from "@/lib/classes/name-patch";
import {
  checkOpenAIKeyFromBrowser,
  type OpenAIKeyCheckResult,
} from "@/lib/classes/openai-key-check";
import { useClass } from "@/lib/classes/use-class";
import { checkDisplayNameForBannedWords } from "@/lib/members/display-name-check";
import { useMembers } from "@/lib/members/use-members";
import { checkPublicTextForBannedWords } from "@/lib/moderation/public-text-check";
import { useProblems } from "@/lib/problems/use-problems";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { isSelectedModelReasoning, REASONING_EFFORT_OPTIONS } from "@/lib/scoring/reasoning";
import { useScoringModels } from "@/lib/scoring/use-scoring-models";
import { liveTemplateFrom, type LiveTemplate } from "@/lib/problem-templates/live-state";

function ClassTemplatePublishCard({
  classId,
  initialPublishedTemplate,
}: {
  classId: number;
  initialPublishedTemplate: PublishedClassTemplateSummary | null;
}) {
  const [publisherDisplayName, setPublisherDisplayName] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  // 초기값은 서버가 새로고침 시점에 내려준 「지금 살아 있는 템플릿」이다
  // (#333) — 이전에는 이 상태가 화면 안에만 있어 새로고침하면 사라지고
  // 공개 폼이 다시 떠 같은 원본이 두 번 공개됐다. 마운트 이후의 흐름(공개·
  // 내리기)은 여전히 그 응답으로만 갱신한다 — 부모가 다시 부를 때마다 이
  // 초기값으로 되돌리지 않는다.
  //
  // **판단은 `liveTemplateFrom` 한 곳에 있다**(2026-09-16) — 내려간 템플릿을
  // 살아 있는 것으로 세는 바람에, 내린 뒤 새로고침해야 다시 공개할 수 있었다.
  // 문제 화면이 같은 버그를 갖고 있었고 같은 함수로 함께 고쳤다.
  const [liveTemplate, setLiveTemplate] = useState<LiveTemplate>(() =>
    liveTemplateFrom(initialPublishedTemplate),
  );
  // 「방금 내렸다」는 이 카드 안의 일이라 따로 든다 — 공개 폼을 막지 않는다.
  const [justTakenDown, setJustTakenDown] = useState(false);

  const [takingDown, setTakingDown] = useState(false);
  const [takedownError, setTakedownError] = useState<string | null>(null);

  async function handlePublish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedPublisherDisplayName = publisherDisplayName.trim();
    // 제출을 누르는 순간에만 검사한다 — 서버가 진짜 문이고(spec #474,
    // #477) 이건 편의다. 템플릿 갤러리는 로그인한 모두가 본다.
    const bannedWordMessage = checkDisplayNameForBannedWords(trimmedPublisherDisplayName);
    if (bannedWordMessage) {
      setPublishError(bannedWordMessage);
      return;
    }
    setPublishError(null);
    setPublishing(true);
    const result = await publishClassAsTemplate(classId, trimmedPublisherDisplayName);
    if (result.ok) {
      setLiveTemplate(liveTemplateFrom(result.data));
      setJustTakenDown(false);
    } else {
      setPublishError(result.detail);
    }
    setPublishing(false);
  }

  async function handleTakedown() {
    if (!liveTemplate) return;
    setTakedownError(null);
    setTakingDown(true);
    const result = await takedownClassTemplate(liveTemplate.shareCode);
    if (result.ok) {
      setLiveTemplate(liveTemplateFrom(result.data));
      setJustTakenDown(true);
    } else {
      setTakedownError(result.detail);
    }
    setTakingDown(false);
  }

  return (
    <Card>
      <CardHeader title="클래스를 템플릿으로 공개" hint="문제와 순서까지 통째로 다른 강사에게 공유" />
      <div className="flex flex-col gap-2.5 p-4">
        {liveTemplate ? (
          <div className="flex flex-col gap-2">
            <p data-testid="publish-class-template-done" className="text-[13px] leading-relaxed">
              공개되었습니다. 아래 주소를 다른 강사에게 전달하세요.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/class-templates/${liveTemplate.shareCode}`}
                data-testid="publish-class-template-share-link"
                className="min-w-0 flex-1 break-all border border-rule bg-surface px-3 py-2 font-mono text-[12.5px] hover:underline"
              >
                /class-templates/{liveTemplate.shareCode}
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
            {takedownError ? (
              <ErrorNote>
                <span data-testid="publish-class-template-takedown-error">{takedownError}</span>
              </ErrorNote>
            ) : null}
          </div>
        ) : (
          <>
            {justTakenDown ? (
              <p data-testid="publish-class-template-taken-down" className="flex items-start gap-2 text-[13px]">
                <Badge tone="neutral">내려짐</Badge>
                <span className="text-ink/60">
                  더 이상 다른 강사가 가져갈 수 없습니다. 다시 공개하면 새 주소가 나옵니다.
                </span>
              </p>
            ) : null}
            {takedownError ? (
              <ErrorNote>
                <span data-testid="publish-class-template-takedown-error">{takedownError}</span>
              </ErrorNote>
            ) : null}
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
          </>
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

function DeleteClassCard({ classId, classroom }: { classId: number; classroom: ClassRow }) {
  // 삭제 — 없던 일로 한다(#330). 보관과 달리 되돌릴 수 없다. 제출이 있으면
  // 백엔드가 판정해 내려준 `has_submissions`를 그대로 믿는다 — 이 화면이 문제·
  // 제출물 목록을 다시 합쳐 스스로 셈하지 않는다.
  const router = useRouter();
  const { state: problemsState } = useProblems(classId);
  const { state: membersState } = useMembers(classId);

  const [confirming, setConfirming] = useState(false);
  const [typedName, setTypedName] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const previewReady = problemsState.status === "ready" && membersState.status === "ready";
  const problemCount = problemsState.status === "ready" ? problemsState.problems.length : null;
  const checklistItemCount =
    problemsState.status === "ready"
      ? problemsState.problems.reduce((sum, problem) => sum + problem.checklist_items.length, 0)
      : null;
  const memberCount = membersState.status === "ready" ? membersState.members.length : null;

  function openConfirm() {
    setError(null);
    setTypedName("");
    setConfirming(true);
  }

  function cancel() {
    setConfirming(false);
    setTypedName("");
    setError(null);
  }

  async function handleDelete() {
    setError(null);
    setDeleting(true);
    const result = await deleteClass(classId);
    if (result.ok) {
      router.push("/");
    } else {
      setError(result.detail);
      setDeleting(false);
    }
  }

  if (classroom.has_submissions) {
    return (
      <Card>
        <CardHeader title="클래스 삭제" hint="되돌릴 수 없습니다" />
        <div className="p-4">
          <Note tone="attention">
            <span data-testid="delete-class-blocked">
              제출이 있어 지울 수 없습니다 — 참여자가 낸 제출과 판정은 그 사람의
              기록이라 강사가 지울 수 없습니다. 수업이 끝났다면 클래스 상세에서
              대신 보관해주세요.
            </span>
          </Note>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader title="클래스 삭제" hint="제출이 없을 때만 가능합니다 — 되돌릴 수 없습니다" />
      <div className="flex flex-col gap-3 p-4">
        {!confirming ? (
          <button
            type="button"
            data-testid="delete-class-open"
            onClick={openConfirm}
            disabled={!previewReady}
            className={buttonClass("danger", "sm")}
          >
            {previewReady ? "클래스 삭제" : "불러오는 중..."}
          </button>
        ) : (
          <div className="flex flex-col gap-3">
            <Note tone="attention">
              <div className="flex flex-col gap-1">
                <span data-testid="delete-class-warning">
                  지우면 문제 {problemCount}개, 체크리스트 항목 {checklistItemCount}개,
                  참여자 {memberCount}명의 가입이 모두 함께 사라지고 되돌릴 수 없습니다.
                </span>
                <span data-testid="delete-class-template-note">
                  이 클래스에서 템플릿으로 공개한 것은 그 시점의 사본이라 영향받지
                  않습니다.
                </span>
              </div>
            </Note>
            <label htmlFor="delete-class-confirm-input">
              <FieldLabel>
                계속하려면 클래스 이름 <b className="text-ink">{classroom.name}</b>을 그대로
                입력하세요
              </FieldLabel>
            </label>
            <input
              id="delete-class-confirm-input"
              data-testid="delete-class-confirm-input"
              value={typedName}
              onChange={(event) => setTypedName(event.target.value)}
              className={INPUT_CLASS}
              autoComplete="off"
            />
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                data-testid="delete-class-confirm"
                onClick={handleDelete}
                disabled={!isDeleteConfirmationTyped(classroom.name, typedName) || deleting}
                className={buttonClass("dangerFilled", "sm")}
              >
                {deleting ? "지우는 중..." : "정말 삭제"}
              </button>
              <button
                type="button"
                data-testid="delete-class-cancel"
                onClick={cancel}
                disabled={deleting}
                className={buttonClass("secondary", "sm")}
              >
                취소
              </button>
            </div>
          </div>
        )}
        {error ? (
          <ErrorNote>
            <span data-testid="delete-class-error">{error}</span>
          </ErrorNote>
        ) : null}
      </div>
    </Card>
  );
}

export default function ClassSettingsPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state, reload } = useClass(classId);
  const { state: modelsState, reload: reloadModels } = useScoringModels(classId);

  const [apiKey, setApiKey] = useState("");
  const [keySaving, setKeySaving] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  // 저장 전에 브라우저가 직접 벤더에게 물어 미리 말한다(#357) — 문이
  // 아니라 안내다, 저장 버튼은 이 값과 무관하게 항상 눌린다. 타자 한
  // 글자마다 치지 않고 입력이 멎은 뒤 한 번만 친다.
  const [liveKeyCheck, setLiveKeyCheck] = useState<OpenAIKeyCheckResult | "checking" | "idle">(
    "idle",
  );

  useEffect(() => {
    const trimmed = apiKey.trim();
    if (trimmed === "") {
      setLiveKeyCheck("idle");
      return;
    }
    setLiveKeyCheck("checking");
    let cancelled = false;
    const timer = setTimeout(() => {
      checkOpenAIKeyFromBrowser(trimmed).then((result) => {
        if (!cancelled) setLiveKeyCheck(result);
      });
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [apiKey]);

  const [defaultModel, setDefaultModel] = useState("");
  const [defaultReasoningEffort, setDefaultReasoningEffort] = useState("low");
  const [modelSaving, setModelSaving] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  const [classNameDraft, setClassNameDraft] = useState("");
  const [instructorDisplayName, setInstructorDisplayName] = useState("");
  const [nameSaving, setNameSaving] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);

  const [tokenBudget, setTokenBudget] = useState("");
  const [warningThreshold, setWarningThreshold] = useState("");
  const [budgetSaving, setBudgetSaving] = useState(false);
  const [budgetError, setBudgetError] = useState<string | null>(null);

  useClassroomTabTitle({
    screenName: "클래스 설정",
    className: state.status === "ready" ? state.classroom.name : undefined,
  });

  useEffect(() => {
    if (state.status === "ready") {
      setDefaultModel(state.classroom.default_model);
      setDefaultReasoningEffort(state.classroom.default_reasoning_effort);
      setClassNameDraft(state.classroom.name);
      setInstructorDisplayName(state.classroom.my_instructor_display_name);
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
  // 채점 키·예산·클래스 삭제는 소유자만 바꾼다(#561, ADR-0055) — 공동 강사에게는 그 입력을
  // 그리지 않고, 지금 값과 「소유자만」이라는 사실만 보여 준다. 강사 이름은 누구나 **자기**
  // 것을 바꾼다(#565) — 이 칸은 보는 사람의 이름이다.
  const isOwner = classroom.role === "owner";
  const namesPatch = classNamesPatch(
    { name: classroom.name, instructorDisplayName: classroom.my_instructor_display_name },
    { name: classNameDraft, instructorDisplayName },
  );

  async function handleKeySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setKeySaving(true);
    setKeyError(null);
    const result = await setOpenAIKey(classId, apiKey);
    if (result.ok) {
      setApiKey("");
      reload();
      // 키가 바뀌면 그 키로 실제로 쓸 수 있는 모델이 달라진다(#401) — 이
      // 화면을 떠나지 않아도 모델 선택지가 새 키 기준으로 바로 갱신된다.
      reloadModels();
    } else {
      setKeyError(result.detail);
    }
    setKeySaving(false);
  }

  async function handleNameSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // 제출을 누르는 순간에만 검사한다 — 서버가 진짜 문이고(spec #474, #477,
    // #479) 이건 편의다. 강사 이름은 가입 미리보기에도 뜨므로 만들 때만
    // 막으면 그 뒤에 바꾸면 그만이고, 클래스 이름은 욕설만 본다.
    if (namesPatch?.instructor_display_name !== undefined) {
      const bannedWordMessage = checkDisplayNameForBannedWords(namesPatch.instructor_display_name);
      if (bannedWordMessage) {
        setNameError(bannedWordMessage);
        return;
      }
    }
    if (namesPatch?.name !== undefined) {
      const bannedWordMessage = checkPublicTextForBannedWords(namesPatch.name, "클래스 이름");
      if (bannedWordMessage) {
        setNameError(bannedWordMessage);
        return;
      }
    }
    setNameSaving(true);
    setNameError(null);
    // 클래스 이름은 클래스 설정으로, 강사 이름은 부른 사람 자신의 자리로(#565) 보낸다.
    let failure: string | null = null;
    if (namesPatch?.name !== undefined) {
      const result = await updateClass(classId, { name: namesPatch.name });
      if (!result.ok) failure = result.detail;
    }
    if (failure === null && namesPatch?.instructor_display_name !== undefined) {
      const result = await renameMyInstructorName(classId, namesPatch.instructor_display_name);
      if (!result.ok) failure = result.detail;
    }
    setNameError(failure);
    reload();
    setNameSaving(false);
  }

  async function handleModelSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setModelSaving(true);
    setModelError(null);
    const result = await updateClass(classId, {
      default_model: defaultModel,
      default_reasoning_effort: defaultReasoningEffort,
    });
    if (result.ok) {
      reload();
    } else {
      setModelError(result.detail);
    }
    setModelSaving(false);
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
    const result = await updateClass(classId, {
      token_budget: parsedBudget,
      token_budget_warning_threshold_percent: parsedThreshold,
    });
    if (result.ok) {
      reload();
    } else {
      setBudgetError(result.detail);
    }
    setBudgetSaving(false);
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow={classroom.name}
        title="클래스 설정"
        description={
          isOwner
            ? "클래스·강사 이름, 채점 키와 모델·예산, 템플릿 공개까지 이 클래스의 설정을 여기서 관리합니다."
            : "클래스 이름과 내 강사 이름, 채점 모델, 템플릿 공개를 여기서 관리합니다. 채점 키·예산과 클래스 삭제는 소유자가 맡습니다."
        }
        actions={
          <Link href={`/classes/${classId}`} className={buttonClass()}>
            클래스로 돌아가기
          </Link>
        }
      />

      <div className="flex flex-col gap-5">
        <Card>
          <CardHeader
            title="이름"
            hint={
              isOwner
                ? "참여자 화면과 가입 미리보기에 이 이름들이 보입니다"
                : "가입 미리보기에 내 강사 이름이 소유자의 이름과 함께 보입니다"
            }
          />
          <div className="flex flex-col gap-3 p-4">
            <form onSubmit={handleNameSubmit} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="class-name-input">
                  <FieldLabel>클래스 이름</FieldLabel>
                </label>
                <input
                  id="class-name-input"
                  data-testid="class-name-input"
                  value={classNameDraft}
                  onChange={(event) => setClassNameDraft(event.target.value)}
                  required
                  maxLength={200}
                  className={INPUT_CLASS}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="class-instructor-display-name-input">
                  <FieldLabel>이 클래스에서 불릴 내 강사 이름</FieldLabel>
                </label>
                <input
                  id="class-instructor-display-name-input"
                  data-testid="class-instructor-display-name-input"
                  value={instructorDisplayName}
                  onChange={(event) => setInstructorDisplayName(event.target.value)}
                  required
                  maxLength={100}
                  className={INPUT_CLASS}
                />
                <span className="text-[11.5px] leading-relaxed text-ink/45">
                  참여자 명단과 제출물에 보이는 이름과는 별개입니다 — 그곳은 참여자 본인이 정한
                  이름을 그대로 씁니다.
                </span>
              </div>
              <div className="flex justify-end">
                <button
                  type="submit"
                  data-testid="class-instructor-display-name-submit"
                  disabled={nameSaving || namesPatch === null}
                  className={buttonClass("primary")}
                >
                  {nameSaving ? "저장하는 중..." : "저장"}
                </button>
              </div>
            </form>
            {nameError ? (
              <ErrorNote>
                <span data-testid="class-instructor-display-name-error">{nameError}</span>
              </ErrorNote>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardHeader title="채점" hint="누구의 키로, 어떤 모델로, 얼마까지 채점할지" />
          <div className="divide-y divide-rule">
            <CardSection id="scoring-key" title="채점 키" hint="이 클래스의 채점에만 쓰입니다">
              <div className="flex flex-col gap-4 p-4">
                {!classroom.has_openai_key ? (
                  <p data-testid="openai-key-status" className="flex flex-wrap items-center gap-2.5 text-[13.5px]">
                    <Badge tone="attention">없음</Badge>
                    <span className="text-ink/60">키가 없으면 이 클래스의 제출은 채점되지 않습니다.</span>
                  </p>
                ) : classroom.openai_key_status === "rejected" ? (
                  <p data-testid="openai-key-status" className="flex flex-wrap items-center gap-2.5 text-[13.5px]">
                    <Badge tone="attention">거부됨</Badge>
                    <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
                    <span className="text-ink/60">
                      벤더가 이 키를 거절했습니다 — 새 키를 저장해야 채점이 다시 시작됩니다.
                    </span>
                  </p>
                ) : classroom.openai_key_status === "unverified" ? (
                  <p data-testid="openai-key-status" className="flex flex-wrap items-center gap-2.5 text-[13.5px]">
                    <Badge tone="neutral">미검증</Badge>
                    <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
                    <span className="text-ink/60">
                      저장할 때 벤더에 닿지 못해 확인하지 못했습니다 — 채점 시도에서 다시 확인됩니다.
                    </span>
                  </p>
                ) : (
                  <p data-testid="openai-key-status" className="flex items-center gap-2.5 text-[13.5px]">
                    <Badge tone="verified">확인함</Badge>
                    <span className="font-mono text-ink/60">{classroom.openai_key_masked}</span>
                  </p>
                )}

                {!isOwner ? (
                  <Note>
                    <span data-testid="openai-key-owner-only">
                      채점 키는 소유자만 바꿀 수 있습니다 — 채점 비용이 소유자의 몫입니다.
                    </span>
                  </Note>
                ) : (
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
                    {/* 저장을 누르기 전에 브라우저가 먼저 말해준다(#357) — 문이
                        아니라 안내다, 판정과 무관하게 위 저장 버튼은 항상 눌린다. */}
                    {liveKeyCheck === "checking" ? (
                      <p data-testid="openai-key-live-check" className="text-[12px] text-ink/45">
                        확인하는 중...
                      </p>
                    ) : liveKeyCheck === "valid" ? (
                      <p data-testid="openai-key-live-check">
                        <Badge tone="verified">이 키를 쓸 수 있습니다</Badge>
                      </p>
                    ) : liveKeyCheck === "invalid" ? (
                      <p data-testid="openai-key-live-check">
                        <Badge tone="attention">이 키는 쓸 수 없습니다</Badge>
                      </p>
                    ) : liveKeyCheck === "unknown" ? (
                      <p data-testid="openai-key-live-check">
                        <Badge tone="neutral">지금은 확인할 수 없습니다</Badge>
                      </p>
                    ) : null}
                    <span className="text-[11.5px] leading-relaxed text-ink/45">
                      저장 뒤에는 다시 볼 수 없습니다 — 화면에도 로그에도 남지 않고, 채점 요청을 보낼
                      때만 복호화됩니다. 참여자에게는 어떤 형태로도 보이지 않습니다.
                    </span>
                  </form>
                )}
                {keyError ? (
                  <ErrorNote>
                    <span data-testid="openai-key-error">{keyError}</span>
                  </ErrorNote>
                ) : null}
              </div>
            </CardSection>

            <CardSection id="scoring-model" title="기본 채점 모델" hint="문제가 자기 모델을 갖지 않으면 이 값을 씁니다">
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
                    {modelsState.source === "fallback" ? (
                      <Note>
                        <span data-testid="scoring-models-unavailable-note">
                          {modelsState.unavailableReason === "no_api_key"
                            ? isOwner
                              ? "키를 넣으면 이 키로 쓸 수 있는 모델을 보여드립니다 — 지금은 기본 목록입니다."
                              : "소유자가 키를 넣으면 그 키로 쓸 수 있는 모델을 보여드립니다 — 지금은 기본 목록입니다."
                            : "지금은 모델 목록을 확인할 수 없어 기본 목록을 보여드립니다."}
                        </span>
                      </Note>
                    ) : null}
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
                            {model.label} · 컨텍스트{" "}
                            {model.context_window ? `${model.context_window.toLocaleString("ko-KR")} 토큰` : "크기 미확인"}
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
                    {isSelectedModelReasoning(defaultModel, modelsState.models, defaultModel === classroom.default_model ? classroom.default_model_is_reasoning : false) ? (
                      <div className="flex flex-col gap-1.5 border-t border-rule pt-3">
                        <label htmlFor="class-default-reasoning-effort">
                          <FieldLabel>기본 추론 강도</FieldLabel>
                        </label>
                        <select
                          id="class-default-reasoning-effort"
                          data-testid="class-default-reasoning-effort-select"
                          value={defaultReasoningEffort}
                          onChange={(event) => setDefaultReasoningEffort(event.target.value)}
                          className={`${INPUT_CLASS} max-w-[200px]`}
                        >
                          {REASONING_EFFORT_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                        <span className="text-[11.5px] leading-relaxed text-ink/45">
                          높을수록 느리고 채점 예산을 더 씁니다.
                        </span>
                      </div>
                    ) : null}
                  </form>
                )}
                {modelError ? (
                  <ErrorNote>
                    <span data-testid="class-default-model-error">{modelError}</span>
                  </ErrorNote>
                ) : null}
              </div>
            </CardSection>

            {/* `id`는 예산 경고 알림(#329)이 이 자리를 가리킬 때 쓰는 앵커다 —
                `lib/notifications/link.ts`가 같은 이름을 짓는다. */}
            <CardSection id="token-budget" title="채점 예산" hint="한도에 닿으면 채점만 멈추고 제출은 쌓입니다">
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

                {!isOwner ? (
                  <Note>
                    <span data-testid="token-budget-owner-only">
                      예산 한도와 경고 기준은 소유자만 바꿀 수 있습니다.
                    </span>
                  </Note>
                ) : (
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
                )}

                {/* 예산 경고 알림은 소유자에게만 간다(ADR-0055) — 공동 강사에게 「알립니다」는
                    거짓이 된다. */}
                {isOwner ? (
                  <Note>
                    기준에 닿으면 <b className="text-ink">서비스 안 알림</b>으로 알립니다 — 메일이나 문자가
                    아니라 이 서비스에 들어오면 보이는 알림입니다. 한도에 닿아도 제출은 계속 쌓이고,
                    예산을 채우면 쌓인 시도부터 순서대로 이어서 채점됩니다.
                  </Note>
                ) : null}
              </div>
            </CardSection>
          </div>
        </Card>

        <ClassTemplatePublishCard
          classId={classId}
          initialPublishedTemplate={classroom.published_template}
        />

        {isOwner ? <DeleteClassCard classId={classId} classroom={classroom} /> : null}
      </div>
    </PageShell>
  );
}
