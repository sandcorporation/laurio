"""테스트 전용 TargetStateResolver.

storage 앱은 Submission/Contest 모델을 모른다(#8, #10 소관). 그래서 실제
리졸버 대신, target_ref 문자열 자체에 상태를 인코딩해 해석하는 더블을 쓴다.
형식: ``"<public|private>:<owner_id 또는 none>:<label>"``.

예: ``"private:1:submission-42-source"`` -> private, owner_id=1
    ``"public:none:submission-42-demo"``  -> public
"""

from __future__ import annotations

from storage.policy import TargetState, Visibility


class FakeTargetStateResolver:
    def resolve(self, target_ref: str) -> TargetState:
        visibility_raw, owner_raw, *_ = target_ref.split(":", 2)
        visibility = Visibility.PUBLIC if visibility_raw == "public" else Visibility.PRIVATE
        owner_id = None if owner_raw == "none" else int(owner_raw)
        return TargetState(visibility=visibility, owner_id=owner_id)
