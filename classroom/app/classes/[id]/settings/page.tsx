"use client";

// 클래스 설정 (#284/#285/#323, 시안 v2 #636). 왼쪽 목차(sticky 180px)와 구획 여섯: 채점 연결(`#scoring-key`) ·
// 기본 모델(`#scoring-model`) · 사용량(`#token-usage`) · 이름 · 템플릿으로 공개 · 보관과 삭제. 앵커 둘은
// 알림이 가리킨다. 공동 강사에게는 소유자 전용 입력(채점 연결 폼·클래스 삭제)을 그리지 않는다.
// 키는 저장 뒤 마스킹된 형태로만 보인다 — 평문은 다시 보여주지 않는다.

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ReasoningModelSwitch } from "@/app/components/ReasoningModelSwitch";
import { ScoringConnectionSection } from "@/app/components/ScoringConnectionSection";
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
import { publishClassAsTemplate, takedownClassTemplate } from "@/lib/class-templates/api";
import {
  copyClass,
  deleteClass,
  renameMyInstructorName,
  updateClass,
  type ClassRow,
  type PublishedClassTemplateSummary,
} from "@/lib/classes/api";
import { isDeleteConfirmationTyped } from "@/lib/classes/delete-confirmation";
import { classNamesPatch } from "@/lib/classes/name-patch";
import { useClass } from "@/lib/classes/use-class";
import { checkDisplayNameForBannedWords } from "@/lib/members/display-name-check";
import { useMembers } from "@/lib/members/use-members";
import { checkPublicTextForBannedWords } from "@/lib/moderation/public-text-check";
import { useProblems } from "@/lib/problems/use-problems";
import { useClassroomTabTitle } from "@/lib/rendering/use-tab-title";
import { isSelectedModelReasoning, REASONING_EFFORT_OPTIONS } from "@/lib/scoring/reasoning";
import { findCostRow, formatKrw, usageCostText, usageKrw } from "@/lib/scoring/cost";
import { useScoringCost } from "@/lib/scoring/use-scoring-cost";
import { useScoringModels } from "@/lib/scoring/use-scoring-models";
import { liveTemplateFrom, type LiveTemplate } from "@/lib/problem-templates/live-state";

import { DefaultModelTable } from "./model-table";
import { SettingsToc, type SettingsSection } from "./settings-toc";

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
    <div className="flex flex-col gap-2.5 p-4">
        {liveTemplate ? (
          <div className="flex flex-col gap-2">
            <p data-testid="publish-class-template-done">
              <Badge tone="verified">공개됨</Badge>
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
              <p data-testid="publish-class-template-taken-down">
                <Badge tone="neutral">내려짐</Badge>
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
    </div>
  );
}

const ROW = "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3";

// 「보관과 삭제」(#636, 시안 v2) — 복사·보관·삭제. 클래스 상세의 머리와 가입 링크 띠에 있던 「복사해서
// 새로 열기」·「보관하기」·「보관 되돌리기」가 여기로 왔다. 보관된 클래스에서는 복사가 주 행동이라
// 주 버튼으로 그린다 — 지난 클래스를 복사해 다음 기수를 여는 것이 흔한 쓰임이다. 삭제는 소유자만.
function ClassLifecycleCard({
  classId,
  classroom,
  isOwner,
  archiveError,
  onSetArchived,
}: {
  classId: number;
  classroom: ClassRow;
  isOwner: boolean;
  archiveError: boolean;
  onSetArchived: (archived: boolean) => void;
}) {
  const router = useRouter();
  const [copying, setCopying] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  async function handleCopy() {
    setCopyError(null);
    setCopying(true);
    const result = await copyClass(classId);
    if (result.ok) {
      router.push(`/classes/${result.data.id}`);
    } else {
      setCopyError(result.detail);
      setCopying(false);
    }
  }

  return (
    <div className="divide-y divide-rule">
      <div className={ROW}>
        <span className="text-[13.5px]">복사</span>
        <button
          type="button"
          data-testid="copy-class-button"
          onClick={handleCopy}
          disabled={copying}
          className={buttonClass(classroom.archived ? "primary" : "secondary", "sm")}
        >
          {copying ? "복사하는 중..." : "복사해서 새로 열기"}
        </button>
      </div>
      {copyError ? (
        <div className="px-4 py-3">
          <ErrorNote>
            <span data-testid="copy-class-error">{copyError}</span>
          </ErrorNote>
        </div>
      ) : null}
      <div className={ROW}>
        <span className="flex items-center gap-2.5 text-[13.5px]">
          보관
          <span data-testid="class-archive-status">
            <Badge tone={classroom.archived ? "neutral" : "verified"}>{classroom.archived ? "보관됨" : "진행중"}</Badge>
          </span>
        </span>
        <button
          type="button"
          data-testid={classroom.archived ? "classroom-unarchive" : "classroom-archive"}
          onClick={() => onSetArchived(!classroom.archived)}
          className={buttonClass("secondary", "sm")}
        >
          {classroom.archived ? "보관 되돌리기" : "보관하기"}
        </button>
      </div>
      {archiveError ? (
        <div className="px-4 py-3">
          <ErrorNote>
            <span data-testid="classroom-archive-error">
              {classroom.archived ? "되돌리지 못했습니다. 다시 시도해주세요." : "보관하지 못했습니다. 다시 시도해주세요."}
            </span>
          </ErrorNote>
        </div>
      ) : null}
      {isOwner ? <DeleteClassRow classId={classId} classroom={classroom} /> : null}
    </div>
  );
}

function DeleteClassRow({ classId, classroom }: { classId: number; classroom: ClassRow }) {
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
      <div className={ROW}>
        <span className="text-[13.5px]">삭제</span>
        <span data-testid="delete-class-blocked">
          <Badge tone="attention">제출이 있어 지울 수 없습니다</Badge>
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className={ROW}>
        <span className="text-[13.5px]">삭제</span>
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
        ) : null}
      </div>
      <div className="flex flex-col gap-3 px-4 pb-4 empty:hidden">
        {!confirming ? null : (
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
    </div>
  );
}

export default function ClassSettingsPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state, reload, setArchived } = useClass(classId);
  const { state: modelsState, reload: reloadModels } = useScoringModels(classId);
  const { reload: reloadCost, ...costState } = useScoringCost(classId);

  const [defaultModel, setDefaultModel] = useState("");
  const [defaultReasoningEffort, setDefaultReasoningEffort] = useState("low");
  // 「호환 서버」의 「추론 모델」 스위치(#602) — 이름으로 알 수 없어 강사가 정한다.
  const [defaultModelIsReasoning, setDefaultModelIsReasoning] = useState(false);
  const [modelSaving, setModelSaving] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  const [classNameDraft, setClassNameDraft] = useState("");
  const [instructorDisplayName, setInstructorDisplayName] = useState("");
  const [nameSaving, setNameSaving] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);

  useClassroomTabTitle({
    screenName: "클래스 설정",
    className: state.status === "ready" ? state.classroom.name : undefined,
  });

  // 읽은 클래스로 칸을 맞추는 일은 렌더 중에 한다(#675) — 효과로 넣으면 빈 칸이 먼저 그려져 그 틈에
  // 친 값을 덮는다. 다시 읽어 새 객체가 오면(저장·보관 뒤) 다시 맞춘다.
  const [seededClassroom, setSeededClassroom] = useState<ClassRow | null>(null);
  if (state.status === "ready" && state.classroom !== seededClassroom) {
    setSeededClassroom(state.classroom);
    setDefaultModel(state.classroom.default_model);
    setDefaultReasoningEffort(state.classroom.default_reasoning_effort);
    setDefaultModelIsReasoning(state.classroom.default_model_is_reasoning);
    setClassNameDraft(state.classroom.name);
    setInstructorDisplayName(state.classroom.my_instructor_display_name);
  }

  // 주소의 `#구획`(예: 보관 행·보관 클래스 머리의 `#class-archive`, #658)은 구획이 클래스를 읽은
  // 뒤에야 그려져 브라우저의 첫 이동이 놓친다 — 처음 그려졌을 때 한 번 그 구획으로 옮긴다.
  const ready = state.status === "ready";
  const scrolledToHash = useRef(false);
  useEffect(() => {
    if (!ready || scrolledToHash.current) return;
    scrolledToHash.current = true;
    const id = window.location.hash.slice(1);
    if (id) document.getElementById(id)?.scrollIntoView();
  }, [ready]);

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
  // 채점 키·클래스 삭제는 소유자만 바꾼다(#561, ADR-0055) — 공동 강사에게는 그 입력을
  // 그리지 않고, 지금 값과 「소유자만」이라는 사실만 보여 준다. 강사 이름은 누구나 **자기**
  // 것을 바꾼다(#565) — 이 칸은 보는 사람의 이름이다.
  const isOwner = classroom.role === "owner";
  const isCompatibleServer = classroom.scoring_connection_kind === "compatible_server";
  const usageKrwText =
    costState.status === "ready" && costState.estimate.unit === "krw"
      ? usageCostText(
          classroom.token_usage_total,
          findCostRow(costState.estimate, classroom.default_model, classroom.default_reasoning_effort),
          classroom.default_model,
        )
      : null;
  const selectedIsReasoning =
    modelsState.status === "ready" &&
    isSelectedModelReasoning(
      defaultModel,
      modelsState.models,
      defaultModel === classroom.default_model ? classroom.default_model_is_reasoning : false,
      isCompatibleServer ? defaultModelIsReasoning : undefined,
    );
  const namesPatch = classNamesPatch(
    { name: classroom.name, instructorDisplayName: classroom.my_instructor_display_name },
    { name: classNameDraft, instructorDisplayName },
  );

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
      ...(isCompatibleServer ? { default_model_is_reasoning: defaultModelIsReasoning } : {}),
    });
    if (result.ok) {
      reload();
    } else {
      setModelError(result.detail);
    }
    setModelSaving(false);
  }

  const costReady = costState.status === "ready" ? costState.estimate : null;
  const scoredCount = classroom.scored_attempt_count;
  const averageTokens = scoredCount > 0 ? Math.round(classroom.token_usage_total / scoredCount) : null;
  const averageKrw =
    averageTokens !== null && costReady?.unit === "krw"
      ? usageKrw(averageTokens, findCostRow(costReady, classroom.default_model, classroom.default_reasoning_effort))
      : null;
  const sections: SettingsSection[] = [
    { id: "scoring-key", label: "채점 연결" },
    { id: "scoring-model", label: "기본 모델" },
    { id: "token-usage", label: "사용량" },
    { id: "class-names", label: "이름" },
    { id: "class-template", label: "템플릿으로 공개" },
    { id: "class-archive", label: "보관과 삭제" },
  ];

  return (
    <PageShell>
      <PageHeader
        eyebrow={classroom.name}
        title="클래스 설정"
        actions={
          <Link href={`/classes/${classId}`} className={buttonClass()}>
            클래스로 돌아가기
          </Link>
        }
      />

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:gap-7">
        <SettingsToc sections={sections} />

        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <SettingsCard id="scoring-key" title="채점 연결">
            <ScoringConnectionSection
              key={`${classroom.scoring_connection_kind}:${classroom.scoring_server_url ?? ""}`}
              classroom={classroom}
              isOwner={isOwner}
              onSaved={() => {
                reload();
                // 연결이 바뀌면 그 연결로 실제로 쓸 수 있는 모델이 달라진다(#401, #601) — 이 화면을
                // 떠나지 않아도 모델 선택지가 바로 갱신된다.
                reloadModels();
                reloadCost();
              }}
            />
          </SettingsCard>

          <SettingsCard id="scoring-model" title="기본 모델">
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
                <form onSubmit={handleModelSubmit} className="flex flex-col gap-3">
                  {modelsState.source === "fallback" ? (
                    <span data-testid="scoring-models-unavailable-note">
                      <Badge>기본 목록</Badge>
                    </span>
                  ) : null}
                  {modelsState.source === "manual" ? (
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="class-default-model">
                        <FieldLabel>모델 이름</FieldLabel>
                      </label>
                      <input
                        id="class-default-model"
                        data-testid="class-default-model-input"
                        value={defaultModel}
                        onChange={(event) => setDefaultModel(event.target.value)}
                        required
                        maxLength={200}
                        className={`${INPUT_CLASS} font-mono`}
                      />
                    </div>
                  ) : (
                    <DefaultModelTable
                      models={modelsState.models}
                      savedModel={classroom.default_model}
                      selected={defaultModel}
                      onSelect={setDefaultModel}
                      costState={costState}
                      reasoningEffort={defaultReasoningEffort}
                    />
                  )}
                  {isCompatibleServer ? (
                    <ReasoningModelSwitch
                      checked={defaultModelIsReasoning}
                      onChange={setDefaultModelIsReasoning}
                      testId="class-default-reasoning-switch"
                      showHint={false}
                    />
                  ) : null}
                  {selectedIsReasoning ? (
                    <div className="flex flex-wrap items-center gap-3">
                      <label htmlFor="class-default-reasoning-effort">
                        <FieldLabel>추론 강도</FieldLabel>
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
                    </div>
                  ) : null}
                  <div>
                    <button
                      type="submit"
                      data-testid="class-default-model-submit"
                      disabled={modelSaving || defaultModel.trim() === ""}
                      className={buttonClass("primary")}
                    >
                      {modelSaving ? "저장하는 중..." : "저장"}
                    </button>
                  </div>
                </form>
              )}
              {modelError ? (
                <ErrorNote>
                  <span data-testid="class-default-model-error">{modelError}</span>
                </ErrorNote>
              ) : null}
            </div>
          </SettingsCard>

          {/* 누적 사용량(#629) — 상한은 없다. 원화는 OpenAI 키 연결일 때 지금 기본 모델의 단가로 셈한
              어림이고, 호환 서버는 토큰만이다. 1회 평균은 누적 / 채점 횟수(#632). */}
          <SettingsCard id="token-usage" title="사용량">
            <div data-testid="token-usage" className="flex flex-col gap-3 p-4">
              <div className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1">
                <span data-testid="token-usage-total" className="font-mono text-[26px] font-semibold">
                  {classroom.token_usage_total.toLocaleString("ko-KR")}
                </span>
                <span className="text-[13px] text-ink/60">토큰</span>
                {usageKrwText ? (
                  <span data-testid="token-usage-krw" className="font-mono text-[15px] sm:ml-auto">
                    {usageKrwText}
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap items-baseline gap-x-7 gap-y-1.5 text-[12.5px]">
                <span data-testid="token-usage-count">
                  <span className="text-ink/60">채점</span> <Num>{scoredCount.toLocaleString("ko-KR")}회</Num>
                </span>
                <span data-testid="token-usage-average">
                  <span className="text-ink/60">1회 평균</span>{" "}
                  <Num>
                    {averageTokens === null
                      ? "—"
                      : `${averageTokens.toLocaleString("ko-KR")} 토큰${averageKrw ? ` · ${formatKrw(averageKrw)}` : ""}`}
                  </Num>
                </span>
                {classroom.token_usage_estimated > 0 ? (
                  <span data-testid="token-usage-estimated">
                    <span className="text-ink/60">어림</span>{" "}
                    <Num>{classroom.token_usage_estimated.toLocaleString("ko-KR")} 토큰</Num>
                  </span>
                ) : null}
                {isCompatibleServer ? null : (
                  <a
                    href={
                      classroom.scoring_connection_kind === "anthropic_key"
                        ? "https://platform.claude.com/usage"
                        : "https://platform.openai.com/usage"
                    }
                    target="_blank"
                    rel="noreferrer noopener"
                    data-testid="token-usage-openai-link"
                    className="text-ink/45 hover:text-ink sm:ml-auto"
                  >
                    {classroom.scoring_connection_kind === "anthropic_key" ? "Claude" : "OpenAI"} 사용량 화면 ↗
                  </a>
                )}
              </div>
            </div>
          </SettingsCard>

          <SettingsCard id="class-names" title="이름">
            <form onSubmit={handleNameSubmit} className="flex flex-col gap-3 p-4">
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
              {nameError ? (
                <ErrorNote>
                  <span data-testid="class-instructor-display-name-error">{nameError}</span>
                </ErrorNote>
              ) : null}
            </form>
          </SettingsCard>

          <SettingsCard id="class-template" title="템플릿으로 공개">
            <ClassTemplatePublishCard classId={classId} initialPublishedTemplate={classroom.published_template} />
          </SettingsCard>

          <SettingsCard id="class-archive" title="보관과 삭제">
            <ClassLifecycleCard
              classId={classId}
              classroom={classroom}
              isOwner={isOwner}
              archiveError={state.archiveError}
              onSetArchived={setArchived}
            />
          </SettingsCard>
        </div>
      </div>
    </PageShell>
  );
}

// 설정의 구획 하나 — 목차가 가리키는 `id` 를 단 카드. 알림·배너가 `#scoring-key` 로 곧장 온다.
function SettingsCard({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-6">
      <Card>
        <CardHeader title={title} />
        {children}
      </Card>
    </section>
  );
}
