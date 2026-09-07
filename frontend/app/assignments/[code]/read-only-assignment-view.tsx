"use client";

// 마감 지난 과제의 학생 화면이 쓰는 읽기 전용 렌더러(#215).
//
// `AssetKindSection`·`RequirementField`(../console/contests/[contestId]/submit/*)는
// 공모전 제출 폼과 공유하는 컴포넌트라 마감 뒤에도 "추가"·"교체"·"삭제" 버튼과
// 업로드 필드를 계속 그린다(`disabled`는 클릭을 막을 뿐 화면에서 지우지
// 않는다) — 백엔드가 쓰기를 거부하니 데이터는 안전하지만, 학생은 파일을 골라
// 스토리지까지 업로드한 뒤에야 저장할 방법이 없다는 것을 안다(#215 배경).
//
// 그 둘을 고치는 대신(공모전 제출 화면까지 같이 바뀐다) 이 화면 전용으로
// "다 그려진 값만 읽는" 컴포넌트를 둔다 — 컨트롤 자체가 트리에 없으므로 지울
// 것도, 비활성화할 것도 없다.
import { ASSET_KIND_LABELS, EVIDENCE_KINDS, type EvidenceIn } from "@/lib/submissions/types";
import type { AssetKind, EditableAsset } from "../../console/contests/[contestId]/submit/asset-kind-section";
import type { RequirementFieldState } from "../../console/contests/[contestId]/submit/requirement-field";
import type { RequirementOut } from "@/lib/submissions/types";

function evidenceKindLabel(kind: string): string {
  return EVIDENCE_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

function ReadOnlyRepositoryBadge({ isPublic }: { isPublic: boolean | null | undefined }) {
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
  return null;
}

export function ReadOnlyAssetSection({
  kind,
  title,
  rows,
  testIdPrefix,
}: {
  kind: AssetKind;
  title: string;
  rows: EditableAsset[];
  testIdPrefix: string;
}) {
  const filled = rows.filter((row) => row.value.trim() !== "");
  const isUploadKind = kind === "source" || kind === "demo_video";

  return (
    <section className="flex flex-col gap-3" data-testid={`${testIdPrefix}-section`}>
      <h2 className="text-lg font-semibold">{title}</h2>

      {filled.length === 0 ? (
        <p className="text-sm text-ink/60" data-testid={`${testIdPrefix}-empty`}>
          없습니다.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {filled.map((row, index) => (
            <div
              key={row.key}
              className="flex flex-col gap-1 rounded-md border border-rule p-3"
              data-testid={`${testIdPrefix}-${index}`}
            >
              {row.label && <span className="text-xs text-ink/60">{row.label}</span>}
              <p
                className="font-mono text-sm text-ink/90"
                data-testid={`${testIdPrefix}-${index}-value`}
              >
                {isUploadKind ? `업로드됨: ${row.value}` : row.value}
              </p>
              {kind === "demo_url" && row.testAccount && (
                <p className="text-xs text-ink/60" data-testid={`${testIdPrefix}-${index}-test-account`}>
                  테스트 계정: {row.testAccount}
                </p>
              )}
              {kind === "repository" && <ReadOnlyRepositoryBadge isPublic={row.isPublic} />}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function ReadOnlyRequirementField({
  requirement,
  state,
  assets,
  testId,
}: {
  requirement: RequirementOut;
  state: RequirementFieldState;
  assets: { id: number; kind: string; label: string; value: string }[];
  testId: string;
}) {
  const isRequired = requirement.grade === "required";

  function assetLabelFor(assetId: number | null): string | null {
    if (assetId == null) return null;
    const asset = assets.find((a) => a.id === assetId);
    if (!asset) return null;
    return `${ASSET_KIND_LABELS[asset.kind] ?? asset.kind}: ${asset.label || asset.value}`;
  }

  return (
    <div data-testid={testId} className="flex flex-col gap-3 rounded-md border border-rule p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-sm border px-2 py-0.5 text-xs ${
              isRequired ? "border-attention text-attention" : "border-rule text-ink"
            }`}
          >
            {isRequired ? "필수" : "선택"}
          </span>
          <p className="text-sm">{requirement.text}</p>
        </div>
        <span className="shrink-0 text-sm" data-testid={`${testId}-is-met`}>
          {state.isMet ? "충족" : "미충족"}
        </span>
      </div>

      {state.note && (
        <p className="text-sm text-ink/70" data-testid={`${testId}-note`}>
          {state.note}
        </p>
      )}

      {state.evidence.length === 0 ? (
        <p className="text-xs text-ink/60" data-testid={`${testId}-evidence-empty`}>
          연결된 근거가 없습니다.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {state.evidence.map((item: EvidenceIn, index) => (
            <li key={index} className="text-xs text-ink/70" data-testid={`${testId}-evidence-${index}`}>
              {evidenceKindLabel(item.kind)}: {item.value}
              {assetLabelFor(item.asset_id ?? null) ? ` (${assetLabelFor(item.asset_id ?? null)})` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
