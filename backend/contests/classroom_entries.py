"""「공모전에도 내기」의 공모전 쪽 (#549, 스펙 #546, ADR-0054, CONTEXT.md 「공모전에도 내기」).

참여자가 공모전 문제의 시도를 「공모전에도 내기」로 내면, 강의실이 시도를 커밋한 뒤 공유층
`core.contest_catalog.contest_entry_requested` 신호로 `ContestEntry` 하나를 보낸다. 여기서
받아 **직접 제출과 같은 검증**(마감 전·허용 켜짐·동의·확인 위치 모양·필수 자료)을 거쳐
ContestSubmission 을 만들거나 고치고, `contest_entry_resolved` 로 결과를 돌려준다.

- **직접 낸 제출과 구별되지 않는다.** 공모전 제출에는 클래스를 가리키는 칸이 없고,
  `attempt_id` 는 결과를 짝짓는 데만 쓰고 저장하지 않는다.
- **시도의 소스는 공모전 업로드 대상으로 옮긴다.** 강의실 업로드 대상의 파일을 그대로
  가리키면 열람 규칙(공모전은 Award 뒤 개최자, 강의실은 본인만)이 어긋나고, 강의실 쪽에서
  문제가 지워지면 공모전 제출의 필수 자료가 함께 사라진다.
- **기존 제출은 통째로 바뀐다** — 직접 제출의 수정(`PUT .../submissions/me`)과 같다: 자료는
  이번 내기에 실린 것만 남고, 자가 응답은 새로 쓴다. 바꾸기 전 확인은 강의실 화면이 받는다.
- **확인 위치는 이번 내기의 선택 자료를 순번으로 가리킨다**(`EntryEvidence.asset_index`) —
  강의실에서 낸 자료는 아직 공모전 쪽 id 가 없으므로, 받아서 자료를 저장한 뒤 새 asset id 로
  잇는다(직접 제출의 `asset_id` 와 같은 결과).

미리 거르기(`check_entry`)와 받을 때의 검증은 같은 함수(`_validate`)다 — 마감·허용 철회
경합은 그 사이에 생기므로 받을 때 한 번 더 본다. 개최자가 필수로 정한 시연 영상·스크린샷
(`Contest.require_*`)만은 미리 거르기에서 빼고 받을 때 본다 — 클래스 시도는 접수되고 공모전
제출만 「내지 못했다(사유)」로 남는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from ninja.errors import HttpError
from pydantic import ValidationError

from accounts.models import DeveloperProfile
from core.clock import Clock
from core.contest_catalog import (
    ContestEntry,
    ContestEntryContext,
    EntryAsset,
    EntryEvidence,
    EntryResponse,
    contest_entry_resolved,
)
from core.contest_switch import contest_product_enabled
from storage.adapters import StorageAdapterError, get_storage_adapter
from storage.api import new_object_key
from submissions.models import Submission, SubmissionAsset
from submissions.schemas import EvidenceIn, RequirementResponseIn, SubmissionAssetIn

from .models import Contest, ContestSubmission
from .submission_api import (
    SOURCE_ACCESS_CONSENT_REQUIRED_MESSAGE,
    _clean_assets_in,
    _merge_assets,
    _replace_requirement_responses,
    validate_requirement_responses,
)
from .submission_target_refs import (
    demo_video_target_ref,
    screenshot_target_ref,
    source_target_ref,
)

logger = logging.getLogger(__name__)

NOT_ACCEPTING_MESSAGE = "이 공모전은 지금 출품을 받지 않습니다 — 마감됐거나 개최자가 허용을 거뒀습니다."
OPTIONAL_KIND_MESSAGE = "선택 자료는 데모 URL·시연 영상·시연 영상 링크·스크린샷만 받습니다."
EVIDENCE_SHAPE_MESSAGE = "확인 위치의 모양이 맞지 않습니다 — 길이와 종류를 확인해 주세요."
EVIDENCE_ASSET_MESSAGE = "이 제출물에 속하지 않은 자료를 확인 위치로 지정했습니다."
SOURCE_COPY_FAILED_MESSAGE = "시도의 소스를 공모전에 옮기지 못했습니다 — 잠시 뒤 다시 내 주세요."
UNEXPECTED_FAILURE_MESSAGE = "공모전에 내지 못했습니다 — 잠시 뒤 다시 내 주세요."

#: 「공모전에도 내기」가 받는 선택 자료 — 소스·저장소는 시도가 채운다.
OPTIONAL_ASSET_KINDS = frozenset(
    {
        SubmissionAsset.Kind.DEMO_URL,
        SubmissionAsset.Kind.DEMO_VIDEO,
        SubmissionAsset.Kind.VIDEO_LINK,
        SubmissionAsset.Kind.SCREENSHOT,
    }
)


class _Rejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class _Validated:
    contest: Contest
    responses: list[RequirementResponseIn]


def accepts_entries(contest: Contest) -> bool:
    return (
        contest_product_enabled()
        and contest.is_free
        and contest.allows_classroom_import
        and contest.status == Contest.Status.PUBLISHED
        and contest.deadline_at > Clock.now()
    )


def _existing_submission(contest_id: int, user_id: int) -> ContestSubmission | None:
    return ContestSubmission.objects.filter(contest_id=contest_id, developer__user_id=user_id).first()


def _assets_in(scoring_asset: EntryAsset, optional_assets) -> list[SubmissionAssetIn]:
    return [
        SubmissionAssetIn(
            kind=asset.kind,
            value=asset.value,
            label=asset.label,
            content_type=asset.content_type,
            order=index,
        )
        for index, asset in enumerate([scoring_asset, *optional_assets])
    ]


def _responses_in(
    entry: ContestEntry, asset_ids_by_index: dict[int, int] | None = None
) -> list[RequirementResponseIn]:
    """자가 응답을 직접 제출의 입력 모양으로 바꾼다. 확인 위치의 `asset_index` 는 자료가 저장된
    뒤(`asset_ids_by_index`)에야 id 로 이을 수 있다 — 그 전(미리 거르기)에는 범위만 본다."""

    count = len(entry.optional_assets)
    responses = []
    for r in entry.responses:
        evidence = []
        for e in r.evidence:
            if e.asset_index is not None and not 0 <= e.asset_index < count:
                raise _Rejected(EVIDENCE_ASSET_MESSAGE)
            asset_id = (asset_ids_by_index or {}).get(e.asset_index) if e.asset_index is not None else None
            evidence.append(EvidenceIn(kind=e.kind, value=e.value, asset_id=asset_id))
        responses.append(
            RequirementResponseIn(
                requirement_id=r.requirement_id, is_met=r.is_met, note=r.note, evidence=evidence
            )
        )
    return responses


def _validate(
    entry: ContestEntry, *, scoring_asset: EntryAsset, required_media: bool = True
) -> _Validated:
    """받을 수 있는 내기인지 본다 — 아무것도 쓰지 않는다. `scoring_asset` 은 공모전 쪽 모양의
    필수 자료다(소스면 공모전 업로드 대상의 키). `required_media` 가 거짓이면 개최자가 필수로
    정한 시연 영상·스크린샷(`Contest.require_*`)은 보지 않는다 — 시도 접수 전 사전 검사용."""

    contest = Contest.objects.filter(pk=entry.contest_id, is_free=True).first()
    if contest is None or not accepts_entries(contest):
        raise _Rejected(NOT_ACCEPTING_MESSAGE)
    if not entry.source_access_consent:
        raise _Rejected(SOURCE_ACCESS_CONSENT_REQUIRED_MESSAGE)
    if any(asset.kind not in OPTIONAL_ASSET_KINDS for asset in entry.optional_assets):
        raise _Rejected(OPTIONAL_KIND_MESSAGE)

    existing = _existing_submission(contest.pk, entry.user_id)
    existing_values = (
        set(existing.assets.values_list("kind", "value")) if existing is not None else set()
    )
    try:
        assets_in = _assets_in(scoring_asset, entry.optional_assets)
        responses = _responses_in(entry)
    except ValidationError as exc:
        raise _Rejected(EVIDENCE_SHAPE_MESSAGE) from exc
    try:
        _clean_assets_in(
            assets_in,
            contest=contest,
            developer_user_id=entry.user_id,
            existing_asset_values=existing_values,
            enforce_required_media=required_media,
        )
        validate_requirement_responses(
            contest, responses, own_asset_ids=set(), removed_asset_ids=set()
        )
    except HttpError as exc:
        raise _Rejected(exc.message) from exc
    return _Validated(contest=contest, responses=responses)


def check_entry(entry: ContestEntry) -> str | None:
    """시도를 만들기 전에 거른다(강의실의 422). 소스는 아직 옮기지 않았으므로 공모전 쪽
    모양의 자리표시 키로 필수 자료 검사를 통과시킨다 — 실제 키는 받을 때 생긴다.

    개최자가 필수로 정한 시연 영상·스크린샷은 여기서 보지 않는다. 클래스 시도는 그것 없이도
    성립하므로 시도는 접수(201)하고, 공모전이 받을 때(`_apply`) 「내지 못했다(사유)」로 남긴다."""

    return _precheck(entry, required_media=False)


def _precheck(entry: ContestEntry, *, required_media: bool) -> str | None:
    scoring_asset = entry.scoring_asset
    if scoring_asset.kind == SubmissionAsset.Kind.SOURCE:
        scoring_asset = EntryAsset(
            kind=scoring_asset.kind,
            value=f"{source_target_ref(entry.contest_id, entry.user_id)}/check",
            content_type=scoring_asset.content_type,
        )
    try:
        _validate(entry, scoring_asset=scoring_asset, required_media=required_media)
    except _Rejected as rejected:
        return rejected.reason
    return None


def entry_context(contest_id: int, user_id: int) -> ContestEntryContext | None:
    contest = Contest.objects.filter(pk=contest_id, is_free=True).first()
    if contest is None or not accepts_entries(contest):
        return None
    upload_target_refs = {
        SubmissionAsset.Kind.DEMO_VIDEO.value: demo_video_target_ref(contest_id, user_id),
        SubmissionAsset.Kind.SCREENSHOT.value: screenshot_target_ref(contest_id, user_id),
    }
    existing = _existing_submission(contest_id, user_id)
    if existing is None:
        return ContestEntryContext(
            has_entry=False,
            upload_target_refs=upload_target_refs,
            require_demo_video=contest.require_demo_video,
            require_screenshot=contest.require_screenshot,
        )
    optional_rows = list(
        existing.assets.filter(kind__in=OPTIONAL_ASSET_KINDS).order_by("order", "id")
    )
    index_by_asset_id = {a.pk: index for index, a in enumerate(optional_rows)}
    responses = tuple(
        EntryResponse(
            requirement_id=r.requirement_id,
            is_met=r.is_met,
            note=r.note,
            evidence=tuple(
                EntryEvidence(
                    kind=e.kind, value=e.value, asset_index=index_by_asset_id.get(e.asset_id)
                )
                for e in r.evidence_items.all()
            ),
        )
        for r in existing.requirement_responses.prefetch_related("evidence_items").all()
    )
    optional_assets = tuple(
        EntryAsset(kind=a.kind, value=a.value, label=a.label, content_type=a.content_type)
        for a in optional_rows
    )
    return ContestEntryContext(
        has_entry=True,
        responses=responses,
        optional_assets=optional_assets,
        upload_target_refs=upload_target_refs,
        require_demo_video=contest.require_demo_video,
        require_screenshot=contest.require_screenshot,
    )


def entries_updated_at(contest_id: int, user_ids: set[int]) -> dict[int, datetime]:
    return dict(
        ContestSubmission.objects.filter(
            contest_id=contest_id, developer__user_id__in=user_ids
        ).values_list("developer__user_id", "updated_at")
    )


def _copy_source(entry: ContestEntry) -> EntryAsset:
    """시도의 소스를 공모전 업로드 대상으로 옮긴다. 저장소는 그대로 쓴다."""

    scoring = entry.scoring_asset
    if scoring.kind != SubmissionAsset.Kind.SOURCE:
        return scoring
    storage = get_storage_adapter()
    try:
        content = storage.read_object(scoring.value)
        if content is None:
            raise _Rejected(SOURCE_COPY_FAILED_MESSAGE)
        object_key = new_object_key(source_target_ref(entry.contest_id, entry.user_id))
        storage.write_object(object_key, content, content_type=scoring.content_type or None)
    except StorageAdapterError as exc:
        raise _Rejected(SOURCE_COPY_FAILED_MESSAGE) from exc
    return EntryAsset(kind=scoring.kind, value=object_key, content_type=scoring.content_type)


def _apply(entry: ContestEntry) -> None:
    # 받을 수 없는 내기에 파일부터 옮기지 않는다 — 자리표시 키로 먼저 거른다(필수 자료 포함).
    reason = _precheck(entry, required_media=True)
    if reason is not None:
        raise _Rejected(reason)
    scoring_asset = _copy_source(entry)
    with transaction.atomic():
        validated = _validate(entry, scoring_asset=scoring_asset)
        contest = validated.contest
        developer, _ = DeveloperProfile.objects.get_or_create(user_id=entry.user_id)
        submission = (
            ContestSubmission.objects.select_for_update()
            .filter(contest=contest, developer=developer)
            .first()
        )
        if submission is None:
            try:
                with transaction.atomic():
                    submission = ContestSubmission.objects.create(
                        user_id=entry.user_id,
                        product=Submission.Product.CONTEST,
                        contest=contest,
                        developer=developer,
                        source_access_consent_at=Clock.now(),
                    )
            except IntegrityError:
                # 같은 사람이 같은 순간 직접 냈다 — 그 행을 이 내기로 바꾼다.
                submission = ContestSubmission.objects.select_for_update().get(
                    contest=contest, developer=developer
                )
        submission.source_access_consent_at = Clock.now()
        submission.save(update_fields=["source_access_consent_at", "updated_at"])
        cleaned = _clean_assets_in(
            _assets_in(scoring_asset, entry.optional_assets),
            contest=contest,
            developer_user_id=entry.user_id,
            existing_asset_values=set(submission.assets.values_list("kind", "value")),
        )
        removed = _merge_assets(submission, cleaned)
        # 확인 위치가 가리키는 선택 자료는 방금 저장됐다 — 순번을 새 asset id 로 잇는다.
        id_by_value = {
            (kind, value): pk for pk, kind, value in submission.assets.values_list("id", "kind", "value")
        }
        # cleaned 는 [시도의 필수 자료, *선택 자료] 순서 그대로다 — 값은 정리된(공백·금칙) 최종 값.
        asset_ids_by_index = {
            index: id_by_value[(item.kind, item.value)]
            for index, item in enumerate(cleaned[1:])
            if (item.kind, item.value) in id_by_value
        }
        _replace_requirement_responses(
            submission,
            contest,
            _responses_in(entry, asset_ids_by_index),
            removed_asset_ids=removed,
        )


def on_contest_entry_requested(sender, entry: ContestEntry, **kwargs) -> None:
    """공유층 신호 수신자 — 언제나 `contest_entry_resolved` 로 답한다."""

    accepted, reason = True, ""
    try:
        _apply(entry)
    except _Rejected as rejected:
        accepted, reason = False, rejected.reason
    except HttpError as exc:
        accepted, reason = False, exc.message
    except Exception:  # noqa: BLE001 — 어떤 실패든 강의실은 결과를 받아야 한다
        logger.exception(
            "공모전에도 내기 처리 실패(contest=%s, attempt=%s)", entry.contest_id, entry.attempt_id
        )
        accepted, reason = False, UNEXPECTED_FAILURE_MESSAGE
    contest_entry_resolved.send(
        sender=Contest, attempt_id=entry.attempt_id, accepted=accepted, reason=reason
    )
