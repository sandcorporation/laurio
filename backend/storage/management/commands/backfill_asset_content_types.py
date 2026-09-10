"""content-type 이 비어 있는 제출 자료를 바이트로 판정해 채운다 (#268 후속).

**무엇을 고치는가.** `SubmissionAsset.content_type` 은 #241 이 만든 필드다. 그
전에 올라간 자료는 값이 비어 있고, 그러면 다운로드가 확장자 없는 `download` 로
떨어진다(`storage.filenames.build_download_filename` — 이름이 `download` 인 것은
설계다, 확장자만 이 값에서 온다). staging 실측(2026-09-10): 소스 37건·시연 영상
15건이 그 상태였고 과제 제출물은 전부 그랬다.

**왜 백필이 성립하는가.** 이 필드는 판정의 근거가 아니라 **표시용 파생값**이다 —
Score 도 원장도 이 값을 읽지 않는다. 그래서 나중에 채워 넣어도 「그때 무엇을 보고
판정했는가」를 흔들지 않는다(append-only 가 지키는 것과 다른 종류의 값이다, #240).

**모르는 것은 비워 둔다.** 판정하지 못한 바이트에 `application/octet-stream` 을
채우면 `build_download_filename` 이 그것을 다시 "모른다"로 해석하므로 결과는
같은데 DB 에만 거짓이 남는다. 그래서 그런 행은 손대지 않고 세기만 한다.

**오브젝트가 없는 행도 정상이다.** 파기된 시연 영상(ADR-0035)과, 시드가 값만
만들고 바이트를 안 쓴 옛 데이터가 그렇다 — 둘 다 실패가 아니라 「읽을 것이
없다」이므로 건너뛴다.

**멱등하다.** 이미 채워진 행은 조회 자체에서 빠지므로 몇 번을 돌려도 같다.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from storage.adapters import get_storage_adapter
from storage.sniffing import SNIFF_BYTES, sniff_content_type
from submissions.models import SubmissionAsset


class Command(BaseCommand):
    help = "content-type 이 비어 있는 제출 자료를 오브젝트 앞부분으로 판정해 채운다 (#268)"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="무엇이 바뀔지만 보고 쓰지 않는다.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]

        # object_key 를 갖는 종류만 대상이다 — 데모 URL·저장소는 storage 를 거치지
        # 않아 다운로드 파일명이라는 개념 자체가 없다(#241).
        targets = SubmissionAsset.objects.filter(
            kind__in=SubmissionAsset.OBJECT_KEY_KINDS, content_type=""
        ).order_by("id")

        adapter = get_storage_adapter()
        filled = 0
        missing = 0
        unknown = 0

        for asset in targets.iterator():
            head = adapter.read_object(asset.value, max_bytes=SNIFF_BYTES)
            if head is None:
                missing += 1
                continue

            content_type = sniff_content_type(head)
            if content_type is None:
                unknown += 1
                self.stderr.write(f"형식을 알 수 없다: 자료 {asset.id} ({asset.kind})")
                continue

            filled += 1
            if not dry_run:
                # `update` 로 이 필드 하나만 쓴다 — 같은 행의 다른 값(파기 시각 등)을
                # 이 명령이 실수로 되돌리지 않게.
                SubmissionAsset.objects.filter(pk=asset.pk).update(content_type=content_type)
            self.stdout.write(f"자료 {asset.id} ({asset.kind}) -> {content_type}")

        prefix = "채울 수 있다" if dry_run else "채웠다"
        self.stdout.write(
            f"{prefix}: {filled}건 · 오브젝트 없음 {missing}건 · 형식 모름 {unknown}건"
        )
