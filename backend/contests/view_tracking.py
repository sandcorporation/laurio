"""ContestView — 조회 집계 (#109, 부모 #105; DB로 옮기는 부분은 #446, spec #444).

`CONTEXT.md`의 `ContestView` 정의를 그대로 구현한다: 사건을 저장하지 않고
날짜별 고유 수만 남긴다. 중복을 가리는 식별자는 하루만 살고 스스로
사라진다 — 방문 기록이라는 개인정보 축을 새로 열지 않는다(ADR-0025가
"목적이 끝나면 파기"를 막 세운 직후, 새 보관 기간을 정해야 하는 데이터를
만들지 않는다).

**저장소는 관계형 DB가 아니라 캐시다.** 공개 상세는 트래픽이 가장 많은
화면이라, 조회마다 Contest 행을 갱신하면 그 행에 경합이 생긴다(#109
인수조건). 이 저장소가 이미 갖고 있는 Redis 캐시(`caches["sessions"]`,
ADR-0018이 Operator 세션을 위해 붙인 것)를 키 접두어로 나눠 함께 쓴다 — 새
Redis 인스턴스를 새로 배선하지 않는다. 그 대가로 `tests/conftest.py`의
`_reset_operator_sessions`가 이 카운터도 함께 비워 준다 — 테스트 격리가
공짜로 따라온다. 테스트에서 그 캐시는 LocMem 이라(`config/settings.py`의
`_RUNNING_TESTS`) 그 정리는 **이 프로세스 안만** 비운다. 예전에는 실물
Redis 의 FLUSHDB 였고, 그래서 호스트에서 돌린 pytest 가 떠 있는 dev 환경의
운영자 세션과 이 카운터까지 통째로 지웠다.

**중복 판별은 날짜 단위다.** Submission이 사람당 하나로 제약돼 있어(한
Developer는 한 Contest에 하나만 낸다) 전환율의 분모도 사람 단위여야
의미가 있다 — 세션(30분) 단위면 분모만 부풀어 전환율이 실제보다 낮게
나온다. 날짜는 `core.clock.Clock.now()`에서 오므로(ADR-0003) 시계를 하루
밀면 다음 날로 다시 세진다.

**방문자 식별.** 로그인한 사람은 `user:{id}`로, 아닌 사람은 IP+User-Agent를
해시한 값으로 식별한다 — 원문(IP·UA·user id)은 캐시 키에도 어디에도 남기지
않고 해시만 남긴다. 그 해시가 들어간 dedup 키 자체가 TTL로 스스로
사라지므로, 방문자를 식별할 값이 영구히 남는 곳은 없다.

**Sponsor 자신의 조회는 세지 않는다.** 자기가 새로고침한 것이 자기 지표를
부풀리면 그 지표는 쓸모가 없다.

**브라우저가 알린다.** 이 모듈은 `contests.api.record_contest_view`(POST,
클라이언트 컴포넌트가 마운트된 뒤에만 부른다)에서만 호출된다 —
`contests.api.get_contest`(SSR이 읽는 공개 상세 GET)는 이 모듈을
import조차 하지 않는다. 렌더를 몇 번 다시 그려도 조회수는 바뀌지 않는다
(ADR-0015가 공개 표면을 SSR로 유지하려고 지키는 것과 같은 자리의
side-effect-free 성질).

**이 캐시의 숫자는 DB에 영구히 남지 않는다 — 그래서 DB로도 옮긴다(#446).**
Redis가 재시작되거나 캐시가 비워지면 이 숫자는 그 시점에 사라진다. 그
대책은 `contests.view_flush`(10분마다 도는 옮기기 스캔)와
`contests.view_flush_store`(어느 Contest가 바뀌었는지 기억하는 작은
저장소)가 진다 — 이 모듈은 카운터를 올리고 「바뀌었다」고 표시하기만
한다. 개최자 지표 화면·공개 목록·랜딩 큐레이션은 이 모듈이 아니라
`Contest.view_count`(DB)를 읽는다.
"""

import hashlib
from datetime import timedelta

from django.core.cache import caches
from django.http import HttpRequest
from django.utils import timezone

from core.clock import Clock

from .models import Contest
from .view_flush_store import get_changed_contests_store

# 날짜가 키 자체에 들어 있어 자정이 지나면 어차피 새 키를 쓴다(그래서 TTL이
# 자정에 정확히 맞을 필요는 없다) — 이 TTL은 "언젠가는 반드시 사라진다"는
# 것만 보장하면 된다. 시계 오차·타임존 경계를 넉넉히 덮도록 하루보다 길게 둔다.
_DEDUP_TTL_SECONDS = int(timedelta(hours=26).total_seconds())

# Operator 세션이 사는 것과 같은 Redis 인스턴스(ADR-0018) — 키 접두어
# (`contestview:`)로만 나눈다. locmem인 "default"는 프로세스마다 메모리가
# 갈려 여러 gunicorn 워커·Celery 프로세스에서 집계가 맞지 않는다.
_CACHE_ALIAS = "sessions"


def _cache():
    return caches[_CACHE_ALIAS]


def _client_ip(request: HttpRequest) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _visitor_identity(request: HttpRequest) -> str:
    """이 요청을 낸 사람을 가리키는 짧은 해시. 원문은 어디에도 남기지 않는다."""

    auth_user = getattr(request, "auth_user", None)
    if auth_user is not None:
        raw = f"user:{auth_user.id}"
    else:
        ip = _client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        raw = f"anon:{ip}:{user_agent}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _today_str() -> str:
    now = Clock.now().astimezone(timezone.get_current_timezone())
    return now.date().isoformat()


def _count_key(contest_id: int) -> str:
    return f"contestview:count:{contest_id}"


def record_view(contest: Contest, request: HttpRequest) -> None:
    """이 요청을 조회 1건으로 셀지 판단하고, 세야 하면 집계를 올린다."""

    auth_user = getattr(request, "auth_user", None)
    if auth_user is not None and auth_user.id == contest.sponsor.user_id:
        return  # Sponsor 자신의 조회는 세지 않는다.

    identity = _visitor_identity(request)
    dedup_key = f"contestview:seen:{contest.id}:{_today_str()}:{identity}"

    cache = _cache()
    # `add`는 원자적이다(Redis SETNX와 동등) — 이미 있으면 아무것도 하지 않고
    # False를 돌려준다. 이 원자성이 "같은 사람이 같은 날 여러 번 열어도 1"을
    # 동시 요청 아래에서도 보장한다.
    first_time_today = cache.add(dedup_key, 1, timeout=_DEDUP_TTL_SECONDS)
    if not first_time_today:
        return

    count_key = _count_key(contest.id)
    # `incr`은 키가 없으면 ValueError를 낸다 — `add`로 먼저 심어 두면(이미
    # 있으면 아무 일도 하지 않는다) 그 다음 `incr`이 항상 성공한다. 심는
    # 값은 0이 아니라 **Contest.view_count**다(#446) — Redis가 비어 있는
    # 것(재시작·캐시 비움)과 "정말 아직 한 번도 안 봤다"를 구별할 수 없으므로,
    # DB에 이미 남아 있는 값에서 이어 센다. 둘 다 처음이면 그 값 자체가
    # 0이라 결과는 같다.
    cache.add(count_key, contest.view_count, timeout=None)
    cache.incr(count_key)

    # 이 Contest를 「바뀐 공모전」 집합에 올린다 — `contests.view_flush`의
    # 옮기기 스캔이 10분마다 이 집합만 보고 DB로 옮긴다(#446). 카운터를
    # 올리는 것과 같은 요청 안에서 함께 표시해야, 스캔이 두 자리 중 하나만
    # 본 상태(카운터는 올랐는데 표시가 안 됐거나 그 반대)가 생기지 않는다.
    get_changed_contests_store().mark_changed(contest.id)


def get_view_count(contest_id: int) -> int:
    """조회수 옮기기 스캔(`contests.view_flush`)과 기존 값 옮기기 명령 전용 —
    Redis의 지금 값 하나를 읽는다. 개최자 지표 화면·공개 목록·큐레이션은 이
    함수를 부르지 않는다(#446) — 그 화면들은 옮기기 스캔이 채운
    `Contest.view_count`(DB)를 읽어, 최대 10분 늦더라도 서로 항상 같은
    숫자를 본다."""

    return _cache().get(_count_key(contest_id), 0)


def get_view_counts(contest_ids: list[int]) -> dict[int, int]:
    """여러 Contest의 Redis 누적 수를 한 번에 읽는다 — 옮기기 스캔이 옮길
    id마다 따로 `get`을 부르면 그만큼 왕복이 늘어난다. 값이 없는 id는
    결과에서 빠진다(호출부가 "아직 하나도 안 봤다"와 "이미 DB에 있는
    값을 그대로 둬야 한다"를 가릴 수 있게 — `contests.view_flush` 참고)."""

    if not contest_ids:
        return {}
    keys_by_id = {contest_id: _count_key(contest_id) for contest_id in contest_ids}
    cached = _cache().get_many(list(keys_by_id.values()))
    return {
        contest_id: cached[key]
        for contest_id, key in keys_by_id.items()
        if key in cached
    }
