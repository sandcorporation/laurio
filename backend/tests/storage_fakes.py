"""테스트 전용 TargetStateResolver.

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
