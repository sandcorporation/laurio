"""공개 GitHub 저장소를 스냅샷으로 보관해 채점 근거로 쓴다 (#193, ADR-0027).

`RepositorySnapshot`이 담는 것은 커밋 SHA 하나뿐이다 — clone한 파일 내용은 따로
보관하지 않는다. `Score.prompt`(scoring.models)가 이미 선별된 파일 내용을 그대로
보관하고 있어서(재현성을 위한 불변 스냅샷, ADR-0006), 같은 바이트를 여기 한 번
더 담으면 ADR-0014가 이미 대가로 적은 유출 리스크와 저장 비용을 이유 없이
키운다. 프롬프트에 없는 것은 "어느 커밋을 보았는가" 하나뿐이라 이 모델이 그것만
남긴다.

**참가자가 낸 것(`SubmissionAsset`)과 플랫폼이 그때 본 것을 한 행에 섞지
않는다.** 섞으면 참가자가 항목을 지울 때 채점 근거의 메타가 함께 사라진다 —
다만 지금 이 저장소에서 제출 자료는 마감 전에만 수정 가능하고 Score가 있는
Submission의 자산은 이미 바뀌지 않으므로 실제로 그 경로를 밟지는 않는다. 그래도
FK를 분리해 두면 그 불변식이 나중에 느슨해져도 이 모델의 의미가 바뀌지 않는다.
"""

from __future__ import annotations

from django.db import models


class RepositorySnapshot(models.Model):
    """이 자산을 채점 시점에 어떤 커밋으로 clone했는가 하나만 남기는 불변 기록.

    한 자산이 여러 번 clone 시도될 수 있으므로(채점이 실패한 회차의 clone
    결과는 남지 않지만, 성공한 회차는 재시도 없이 단 한 번만 있다 — Score는
    Submission당 정확히 한 번만 만들어진다, ADR-0006) `asset`에 유니크 제약을
    걸지 않는다 — related_name이 복수형(`snapshots`)인 이유다.
    """

    asset = models.ForeignKey(
        "submissions.SubmissionAsset", related_name="snapshots", on_delete=models.CASCADE
    )
    commit_sha = models.CharField(max_length=40)
    cloned_at = models.DateTimeField()

    class Meta:
        ordering = ["-cloned_at"]
        verbose_name = "저장소 스냅샷"
        verbose_name_plural = "저장소 스냅샷"

    def __str__(self) -> str:  # pragma: no cover
        return f"RepositorySnapshot(asset={self.asset_id}, commit_sha={self.commit_sha})"
