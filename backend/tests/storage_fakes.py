"""테스트 전용 TargetStateResolver · MaxUploadSizeResolver.

storage 앱은 Submission/Contest 모델을 모른다(#8, #10 소관). 그래서 실제
리졸버 대신, target_ref 문자열 자체에 상태를 인코딩해 해석하는 더블을 쓴다.
형식: ``"<public|private>:<owner_id 또는 none>:<label>"``.

예: ``"private:1:submission-42-source"`` -> private, owner_id=1
    ``"public:none:submission-42-demo"``  -> public

형식을 안 지키는 target_ref(콜론이 없거나 owner_id가 정수가 아닌 경우)는
예외를 던지지 않는다 — 500이 아니라, 소유자 없는 private으로 fail-closed 한다.
"""

from __future__ import annotations

from storage.policy import TargetState, Visibility


class FakeTargetStateResolver:
    def resolve(self, target_ref: str) -> TargetState:
        parts = target_ref.split(":", 2)
        if len(parts) < 2:
            return TargetState(visibility=Visibility.PRIVATE, owner_id=None)

        visibility_raw, owner_raw = parts[0], parts[1]
        visibility = Visibility.PUBLIC if visibility_raw == "public" else Visibility.PRIVATE

        owner_id: int | None
        if owner_raw == "none":
            owner_id = None
        else:
            try:
                owner_id = int(owner_raw)
            except ValueError:
                owner_id = None

        return TargetState(visibility=visibility, owner_id=owner_id)


class FakeMaxUploadSizeResolver:
    """target_ref의 마지막 세그먼트가 ``"cap<N>"`` 이면 N바이트 상한, 아니면
    상한 없음(None) — #261. 실제 리졸버(`submissions.resolvers.
    SubmissionMaxUploadSizeResolver`)는 슬롯(source/demo-video/build-asset)을
    PlatformPolicy 필드에 매핑하지만, storage 앱은 그 형식을 몰라도 되므로
    이 더블은 target_ref 문자열에 상한을 직접 인코딩한다."""

    def resolve(self, target_ref: str) -> int | None:
        last = target_ref.rsplit(":", 1)[-1]
        if not last.startswith("cap"):
            return None
        try:
            return int(last[len("cap") :])
        except ValueError:
            return None


class FakeAlwaysDestroyedResolver:
    """storage.policy.ObjectDestructionResolver 더블(#262) — 항상 "파기됐다"고
    답한다. storage 앱이 실제 도메인 모델을 몰라도 다운로드의 "파기 응답" 경로를
    검증할 수 있게 한다."""

    def resolve(self, object_key: str) -> bool:
        return True
