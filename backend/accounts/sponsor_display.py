"""개최자의 공개용 표시 이름이 비어 있는지 확인하는 문 (#447).

무료 공모전 공개(`contests.api.publish_free_contest`)와 유료 공모전 결제
시작(`payments.api.initiate_payment`, 결제로 공개되는 경로) 둘 다 이 문 앞에서
같은 조건을 본다 — 공개된 뒤 참가자에게 개최자가 익명으로 보이지 않게
하기 위해서다. 초안 생성·수정(`create_contest`/`create_free_contest`/
`update_contest`)은 이 확인을 거치지 않는다 — draft에서는 아직 아무도 그
이름을 볼 일이 없고, published에서 다시 고칠 때는 표시 이름이 이미 공개를
통과했을 때만 도달할 수 있는 상태이기 때문이다(#473).

`accounts`(공유층)에 둔 이유는 `contests`·`payments` 둘 다 이 조건을
그대로 써야 하기 때문이다 — 한쪽에만 두면 다른 쪽이 복붙하거나 지연
import로 상대 앱을 끌어와야 한다(#269 앱 경계표에서 둘 다 공모전
계열이라 서로 불러도 되지만, 조건을 두 벌로 쓰면 언젠가 갈라진다).
"""

from ninja.errors import HttpError

from .models import SponsorProfile


def require_sponsor_display_name(sponsor: SponsorProfile) -> None:
    if not sponsor.display_name:
        raise HttpError(422, "공개하려면 먼저 개최자 표시 이름을 등록해야 합니다.")
