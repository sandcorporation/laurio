"use client";

// 자료 종류 하나(소스·시연 영상·데모 URL·GitHub 저장소)를 다중 편집하는 구역
// (#192, ADR-0027). submit/page.tsx 가 네 번 인스턴스화한다 — 소스·시연 영상은
// 업로드, 데모 URL·저장소는 URL 텍스트라는 것만 `kind`로 갈라 안에서 처리한다.
//
// **종류별 개수 상한을 이 컴포넌트가 막지 않는다.** 상한(`max_*_assets`)은
// PlatformPolicy 에 있고 `GET /api/operator/policy` 가 이미 내려주지만, 그건
// 운영자 API 다 — 공개 앱 BFF 허용목록(lib/proxy/allowlist.ts)은 `/api/operator/*`
// 를 의도적으로 막는다(운영자 세션이 새는 길을 새로 만들지 않기 위해서다, #43).
// 그래서 이 화면은 상한을 하드코딩해 미리 막는 대신 "추가"를 항상 허용하고,
// 넘치면 서버가 저장 시점에 422 로 알리는 문구를 그대로 보여준다(submit-error).
import { checkGithubRepositoryUrl, commitUrl, shortSha } from "@codemit/bff-client/repository-url";

import { ErrorNote, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import { UploadField } from "@/components/upload/upload-field";

export type AssetKind = "source" | "demo_video" | "screenshot" | "demo_url" | "repository";

// 스크린샷 업로드가 받는 파일 형식(ADR-0036) — 서버 검증(submissions.api.
// ALLOWED_SCREENSHOT_CONTENT_TYPES)을 대신하지 않는다, 저장 전에 같은 실수를
// 미리 걸러 왕복을 줄일 뿐이다.
const SCREENSHOT_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";

export interface EditableAsset {
  /** React key — 안정적이어야 재정렬 중에도 입력 포커스를 잃지 않는다. */
  key: string;
  /** 기존 자료의 id. 새로 추가한 행에는 없다. */
  id?: number;
  value: string;
  label: string;
  testAccount: string;
  /** `repository` 자료만 의미가 있다 — #193 의 스캔이 채우기 전까지는 null. */
  isPublic?: boolean | null;
  /** `repository` 자료만 — 낸 브랜치·커밋을 찾았는가(#777). 저장소 주소만 낸 행·확인 전은 null. */
  refFound?: boolean | null;
  /** `repository` 자료만 — 고정 커밋(#777). 커밋 주소의 SHA 또는 첫 스캔이 박은 브랜치 HEAD. */
  commitSha?: string | null;
  /** `demo_video` 자료만 의미가 있다(#262) — 파일이 지워지는(또는 지워진) 시각.
   * 아직 정해지지 않았으면(진행 중 공모전) undefined. */
  retentionDeadline?: string | null;
  /** `demo_video` 자료만 의미가 있다(#262) — 보존 기간이 지나 파일이 이미
   * 지워졌는가. 자료 행·근거는 그대로 있지만 이 파일만 없다는 뜻이다. */
  retentionExpired?: boolean;
  // 방금 업로드한 File의 MIME 타입(#241) — `UploadField.onUploaded`가 채운다.
  // 기존 자료를 그대로 불러온 행(`assetsOfKind`)에는 없다 — 서버가 이 값을
  // 다시 내주지 않고(`SubmissionAssetOut`), 그래도 된다: value(object_key)가
  // 안 바뀐 자료는 서버가 이 필드를 건드리지 않는다(`submissions.api.
  // _merge_assets`).
  contentType?: string | null;
}

let localKeySeq = 0;
export function createEmptyAsset(): EditableAsset {
  localKeySeq += 1;
  return { key: `new-${Date.now()}-${localKeySeq}`, value: "", label: "", testAccount: "" };
}


// 시연 영상 파일의 보관 시점(#262) — 예측 가능해지도록 파기 전에 미리
// 알려준다("파기를 미리 말한다", 결정문). 알림을 새로 만들지 않는 대신
// 이 문구 하나가 그 역할을 한다.
function formatRetentionDate(iso: string): string {
  const date = new Date(iso);
  return `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, "0")}.${String(
    date.getDate()
  ).padStart(2, "0")}`;
}

function DemoVideoRetentionNote({
  retentionDeadline,
  retentionExpired,
}: {
  retentionDeadline: string | null | undefined;
  retentionExpired: boolean | undefined;
}) {
  if (retentionExpired) {
    return (
      <p className="text-xs text-attention" data-testid="demo-video-retention-expired">
        보관 기간이 지나 파일이 삭제되었습니다. 자료와 확인 위치는 그대로 남아 있습니다.
      </p>
    );
  }
  if (retentionDeadline) {
    return (
      <p className="text-xs text-ink/60" data-testid="demo-video-retention-deadline">
        {formatRetentionDate(retentionDeadline)}까지 보관되고, 그 뒤 파일이 삭제됩니다.
      </p>
    );
  }
  return (
    <p className="text-xs text-ink/60" data-testid="demo-video-retention-pending">
      마감·심사가 끝나고 일정 기간이 지나면 파일이 삭제됩니다. 자료와 확인 위치는 남습니다.
    </p>
  );
}

function RepositoryBadge({
  isPublic,
  refFound,
  isCommit,
}: {
  isPublic: boolean | null | undefined;
  /** 낸 브랜치·커밋을 GitHub 에서 찾았는가(#777) — 저장소 주소만 낸 행은 늘 null. */
  refFound?: boolean | null;
  /** 커밋 주소로 낸 행인가 — 못 찾았을 때 「브랜치」 대신 「커밋」이라 말한다. */
  isCommit?: boolean;
}) {
  if (isPublic === true && refFound === false) {
    // 비공개와 같은 줄의 새 상태 — 공개 저장소지만 낸 브랜치·커밋이 없다(오타·지워진 브랜치·
    // force push). 마감 전에 고치면 다시 확인된다. 기본 브랜치로 대신 채점하지 않는다.
    return (
      <p className="text-xs text-attention" data-testid="repository-ref-missing-badge">
        {isCommit ? "커밋을 찾을 수 없음" : "브랜치를 찾을 수 없음"} — 채점에 반영되지 않습니다.
      </p>
    );
  }
  if (isPublic === true) {
    return (
      <p className="text-xs text-verified" data-testid="repository-public-badge">
        공개 저장소 — 채점에 반영됩니다.
      </p>
    );
  }
  if (isPublic === false) {
    return (
      <p className="text-xs text-attention" data-testid="repository-private-badge">
        비공개 저장소 — 채점에 반영되지 않습니다.
      </p>
    );
  }
  return (
    <p className="text-xs text-ink/60" data-testid="repository-checking-badge">
      공개 여부 확인 중 — 마감 전 자동으로 확인됩니다.
    </p>
  );
}

export interface AssetKindSectionProps {
  kind: AssetKind;
  title: string;
  helperText?: React.ReactNode;
  rows: EditableAsset[];
  onChange: (rows: EditableAsset[]) => void;
  disabled: boolean;
  /** 최소 한 개가 있어야 하는 종류(현재는 source뿐) — 마지막 행은 지울 수 없다. */
  required?: boolean;
  addLabel: string;
  testIdPrefix: string;
  /** source·demo_video·screenshot 전용 presigned 업로드 대상. 나머지 종류는 쓰지 않는다. */
  targetRefPrefix?: string;
}

// 소스 업로드 칸의 파일 선택창이 기본으로 보여줄 형식(#260). **강제가
// 아니다** — `accept`는 브라우저 파일 선택창의 기본 필터일 뿐이고, 사용자가
// "모든 파일"로 바꾸면 그대로 통과한다. 백엔드가 zip이 아닌 단일 파일도 이미
// 받으므로(scoring/source_selection.py의 비-zip 폴백) 여기서 막을 이유가
// 없다 — zip이 "기본"이라는 것만 알리면 된다.
const SOURCE_UPLOAD_ACCEPT = ".zip";

export function AssetKindSection({
  kind,
  title,
  helperText,
  rows,
  onChange,
  disabled,
  required,
  addLabel,
  testIdPrefix,
  targetRefPrefix,
}: AssetKindSectionProps) {
  const isUploadKind = kind === "source" || kind === "demo_video" || kind === "screenshot";
  const canRemove = !required || rows.length > 1;
  // `required` 종류(오늘은 소스뿐)는 화면에 행이 하나 있어도 그 행이
  // **비어 있을 수 있다** — 첫 로드 때 항상 빈 행 하나로 시작하고
  // (submit/page.tsx), 마지막 행은 지울 수 없다(canRemove). 그래서
  // "행이 0개"가 아니라 "채워진 값이 하나도 없다"를 경고 조건으로 삼는다 —
  // 안 그러면 저장을 눌러 서버가 거부할 때까지 참가자가 소스 누락을 모른다.
  const hasFilledValue = rows.some((row) => row.value.trim() !== "");

  function update(index: number, patch: Partial<EditableAsset>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addRow() {
    onChange([...rows, createEmptyAsset()]);
  }

  function removeRow(index: number) {
    onChange(rows.filter((_, i) => i !== index));
  }

  function moveRow(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= rows.length) return;
    const next = [...rows];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <section className="flex flex-col gap-3" data-testid={`${testIdPrefix}-section`}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">
          {title}
          {required ? " (필수)" : ""}
        </h2>
        <button
          type="button"
          onClick={addRow}
          disabled={disabled}
          data-testid={`${testIdPrefix}-add`}
          className={buttonClass("secondary", "sm")}
        >
          {addLabel}
        </button>
      </div>
      {helperText}

      {required && !hasFilledValue && (
        <ErrorNote>
          <span data-testid={`${testIdPrefix}-missing-warning`}>
            아직 없습니다 — 없으면 제출이 거부됩니다.
          </span>
        </ErrorNote>
      )}
      {!required && rows.length === 0 && (
        <p className="text-sm text-ink/60" data-testid={`${testIdPrefix}-empty`}>
          아직 없습니다.
        </p>
      )}

      <div className="flex flex-col gap-3">
        {rows.map((row, index) => {
          // 강의실 제출 화면과 같은 판정(@codemit/bff-client/repository-url) — 서버 검증을
          // 대신하지 않고, 저장 전에 같은 실수(SSH 주소·파일 주소)를 바로 말해 준다. 끝의
          // .git·슬래시는 실수가 아니라 저장할 때 정리한다(page.tsx 의 rowsToAssetsIn).
          const repoCheck = kind === "repository" ? checkGithubRepositoryUrl(row.value) : null;
          const repoInvalid = repoCheck !== null && !repoCheck.ok ? repoCheck : null;

          return (
            <div
              key={row.key}
              className="flex flex-col gap-2 border border-rule bg-surface p-3"
              data-testid={`${testIdPrefix}-${index}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-ink/60">{index + 1}번째</span>
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => moveRow(index, -1)}
                    disabled={disabled || index === 0}
                    data-testid={`${testIdPrefix}-${index}-move-up`}
                    className={buttonClass("secondary", "sm")}
                  >
                    위로
                  </button>
                  <button
                    type="button"
                    onClick={() => moveRow(index, 1)}
                    disabled={disabled || index === rows.length - 1}
                    data-testid={`${testIdPrefix}-${index}-move-down`}
                    className={buttonClass("secondary", "sm")}
                  >
                    아래로
                  </button>
                  {canRemove && (
                    <button
                      type="button"
                      onClick={() => removeRow(index)}
                      disabled={disabled}
                      data-testid={`${testIdPrefix}-${index}-remove`}
                      className={buttonClass("secondary", "sm")}
                    >
                      삭제
                    </button>
                  )}
                </div>
              </div>

              <label className="flex flex-col gap-1 text-sm">
                라벨
                <input
                  className={INPUT_CLASS}
                  value={row.label}
                  disabled={disabled}
                  placeholder="예: 모바일 앱 데모"
                  onChange={(event) => update(index, { label: event.target.value })}
                  data-testid={`${testIdPrefix}-${index}-label`}
                />
              </label>

              {isUploadKind ? (
                <>
                  {targetRefPrefix && (
                    <UploadField
                      disabled={disabled}
                      targetRef={targetRefPrefix}
                      label={row.value ? "다른 파일로 교체" : "파일 선택"}
                      accept={
                        kind === "source"
                          ? SOURCE_UPLOAD_ACCEPT
                          : kind === "screenshot"
                            ? SCREENSHOT_ACCEPT
                            : undefined
                      }
                      testId={`${testIdPrefix}-${index}-upload`}
                      onUploaded={(objectKey, contentType) =>
                        update(index, { value: objectKey, contentType })
                      }
                    />
                  )}
                  {row.value && (
                    // 사람이 읽을 수 있는 이름을 보인다(#250) — 예전에는 여기
                    // `row.value`(스토리지 object_key, 예:
                    // `submission:33:27:source/1b5ef7092b...`)를 그대로
                    // 찍었다. 유출은 아니다(본인 자료다) — 다만 읽는 사람에게
                    // 아무 뜻이 없는 문자열이었다. 라벨을 채웠으면 그 라벨,
                    // 아니면 종류 이름 + 순번("소스코드 파일 1" 등)으로
                    // 대신한다. **순번을 붙이는 이유** — 라벨을 안 채운 행이
                    // 여럿이면(예: 소스 두 개를 그냥 올리기만 한 경우) 종류
                    // 이름만으로는 옛 raw key와 달리 행끼리 구별이 안 된다
                    // (#250 코드리뷰 지적) — 옛 key는 못 읽어도 최소한
                    // 서로 달랐다. 서버는 원본 파일명을 남기지 않는다(#241
                    // 결정, 응답 헤더 이스케이프 비용을 피하려고 다운로드
                    // 파일명도 고정 이름 + content-type 유도 확장자로 낸다) —
                    // 그래서 순번이 이 화면에서 낼 수 있는 가장 구체적인
                    // 구별자다.
                    <p
                      className="text-xs text-verified"
                      data-testid={`${testIdPrefix}-${index}-value`}
                    >
                      업로드됨: {row.label.trim() || `${title} 파일 ${index + 1}`}
                    </p>
                  )}
                  {row.value && kind === "demo_video" && (
                    <DemoVideoRetentionNote
                      retentionDeadline={row.retentionDeadline}
                      retentionExpired={row.retentionExpired}
                    />
                  )}
                </>
              ) : (
                <label className="flex flex-col gap-1 text-sm">
                  {kind === "repository" ? "저장소 URL" : "데모 URL"}
                  <input
                    className={INPUT_CLASS}
                    value={row.value}
                    disabled={disabled}
                    placeholder={
                      kind === "repository" ? "https://github.com/owner/repo" : "https://"
                    }
                    onChange={(event) =>
                      // 저장소 URL이 바뀌면 이전 URL에 대한 공개 여부 확인은
                      // 더 이상 이 값의 것이 아니다 — "확인 중"으로 되돌리지
                      // 않으면 아직 확인된 적 없는 새 URL이 옛 배지("공개 —
                      // 채점에 반영됩니다")를 그대로 붙인 채 거짓말한다.
                      update(index, {
                        value: event.target.value,
                        ...(kind === "repository" ? { isPublic: null, refFound: null, commitSha: null } : {}),
                      })
                    }
                    data-testid={`${testIdPrefix}-${index}-value`}
                  />
                </label>
              )}

              {repoInvalid && (
                <p
                  className="text-xs text-attention"
                  data-testid={`${testIdPrefix}-${index}-invalid`}
                >
                  {repoInvalid.message}
                  {repoInvalid.suggestion ? (
                    <>
                      {" "}
                      <button
                        type="button"
                        data-testid={`${testIdPrefix}-${index}-suggestion`}
                        disabled={disabled}
                        onClick={() =>
                          update(index, {
                            value: repoInvalid.suggestion ?? "",
                            isPublic: null,
                            refFound: null,
                            commitSha: null,
                          })
                        }
                        className="font-mono underline"
                      >
                        {repoInvalid.suggestion}
                      </button>
                      로 바꾸기
                    </>
                  ) : null}
                </p>
              )}

              {kind === "repository" && (
                <div className="flex items-center justify-between gap-2">
                  <RepositoryBadge
                    isPublic={row.isPublic}
                    refFound={row.refFound}
                    isCommit={/\/commit\/[0-9a-f]+$/i.test(row.value.trim())}
                  />
                  {/* 고정 커밋(#777) — 브랜치·커밋으로 낸 행만. 낸 주소 그대로를 위 입력칸이, 짧은 SHA 를 커밋 링크로. */}
                  {row.commitSha ? (
                    <a
                      href={commitUrl(row.value, row.commitSha)}
                      target="_blank"
                      rel="noreferrer"
                      className="shrink-0 font-mono text-xs text-ink/60 underline"
                      data-testid={`${testIdPrefix}-${index}-commit`}
                    >
                      {shortSha(row.commitSha)}
                    </a>
                  ) : null}
                </div>
              )}

              {kind === "demo_url" && (
                <label className="flex flex-col gap-1 text-sm">
                  테스트 계정
                  <input
                    className={INPUT_CLASS}
                    value={row.testAccount}
                    disabled={disabled}
                    onChange={(event) => update(index, { testAccount: event.target.value })}
                    data-testid={`${testIdPrefix}-${index}-test-account`}
                  />
                </label>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
