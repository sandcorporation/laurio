from django.conf import settings
from django.db import models


class ClockOverride(models.Model):
    """테스트가 시각을 고정·전진시키기 위한 오버라이드. 단일 행(pk=1)만 쓴다.

    ADR-0003: "시각은 주입 가능한 의존성이다". 앱 코드는 `datetime.now()` 나
    `django.utils.timezone.now()` 를 직접 부르지 않고 항상 `core.clock.Clock.now()` 를
    거친다. 이 행이 비어 있으면 `Clock.now()` 는 실제 시각을 돌려주고, 테스트가 이 행을
    채우면 그 시각을 고정된 "현재"로 취급한다. 프로덕션에서는 이 행이 채워질 일이 없다.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    overridden_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "시각 오버라이드"
        verbose_name_plural = "시각 오버라이드"

    def __str__(self) -> str:  # pragma: no cover - admin 편의용
        return f"ClockOverride(overridden_at={self.overridden_at!r})"


class ScheduledStateDemo(models.Model):
    """ADR-0003 조건부 UPDATE 전이 메커니즘의 최소 증명용 스캐폴딩.

    실제 `Contest` 모델은 아직 없다(#8, 다른 체인 소관). 이 모델은 오직
    "전이 시각이 지난 행을 스캔해 `UPDATE ... WHERE id=? AND state='이전상태'` 로만
    전이시키고, rowcount 가 1일 때만 통과시킨다"는 메커니즘을 시연하기 위한 것이며
    도메인 로직을 담지 않는다. 이후 티켓이 실제 모델에 같은 메커니즘
    (`core.scans.transition_scan` / `core.transitions.claim_transition`)을
    재사용하면 된다.
    """

    class State(models.TextChoices):
        PENDING = "pending", "대기"
        DONE = "done", "완료"

    label = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    due_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "전이 스캐폴딩"
        verbose_name_plural = "전이 스캐폴딩"
        # 틱 스캔의 WHERE 절(state=... AND due_at<=...)이 타는 인덱스. 없으면 백로그가
        # 쌓였을 때 매 틱마다 시퀀셜 스캔이 된다.
        indexes = [models.Index(fields=["state", "due_at"], name="core_ssd_state_due_at_idx")]

    def __str__(self) -> str:  # pragma: no cover - admin 편의용
        return f"ScheduledStateDemo({self.pk}, {self.state})"


class DbConnectionAlertState(models.Model):
    """「DB 연결 사용률」 경고 스캔(`core.db_connection_scan`, #455)이 마지막으로
    언제 오류 수집기로 보냈는지 기억하는 단일 행(pk=1) — 없으면 만들어서 쓴다.

    `contests.models.ContestSearchReindexState`와 같은 역할이지만 기본값이
    다르다: 그쪽은 새 행을 "방금 찜됐다"로 보아 곧바로 다시 돌지 않게 하지만,
    여기서는 `last_alerted_at`이 비어 있는 것이 "한 번도 보낸 적 없다"는 뜻이라
    첫 번째 임계 초과는 간격을 기다리지 않고 곧바로 보낸다 — 사람이 500을 보기
    전에 알아야 한다는 요구가 "아직 안 심었으니 봐준다"보다 앞선다.
    """

    last_alerted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"DbConnectionAlertState(last_alerted_at={self.last_alerted_at})"


# --- 연결된 앱 (ADR-0052, #512, #870) ---------------------------------------------
#
# 사용자가 자기 계정으로 쓰도록 허락한 외부 AI 도구(CONTEXT.md 「연결된 앱」). 백엔드가
# MCP 규격의 OAuth 2.1 인가 서버를 직접 연다(`core.oauth`) — 아래 다섯이 그 상태 전부다.
# 강의실(`scope="classroom"`)과 공모전(`scope="contests"`)이 같은 표를 쓴다 — 처음에는
# `classroom` 앱에 있었고(#512), 공모전 MCP(#870)가 생기며 테이블 이름은 그대로 둔 채
# 여기로 올렸다. 토큰과 인가 코드는 **해시로만** 저장한다: DB 가 새도 그 값으로 닿을 수
# 없다. 시각은 전부 `Clock.now()`로 채운다(`auto_now_add`를 쓰지 않는다) —
# 90일 만료 스캔과 토큰 수명을 시험이 시계를 옮겨 확인한다(ADR-0003).


class OAuthClient(models.Model):
    """동적 클라이언트 등록(RFC 7591)으로 생긴 외부 앱 하나 — 아직 누구의 허락도
    아니다. 허락은 `ConnectedApp`이다. 아무도 허락하지 않은 등록은 스캔이 걷는다
    (`core.oauth.UNUSED_CLIENT_SCAN`) — 인증 없이 누구나 등록할 수 있어서다."""

    client_id = models.CharField(max_length=64, unique=True)
    #: 기밀 클라이언트(`client_secret_post`·`client_secret_basic`)만 갖는다. 해시다.
    client_secret_hash = models.CharField(max_length=64, blank=True, default="")
    token_endpoint_auth_method = models.CharField(max_length=32, default="none")
    #: 앱이 스스로 밝힌 이름 — 동의 화면과 「연결된 앱」 목록에 그대로 나온다.
    client_name = models.CharField(max_length=200, blank=True, default="")
    redirect_uris = models.JSONField(default=list)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "classroom_oauthclient"
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"OAuthClient(client_id={self.client_id!r})"


class ConnectedApp(models.Model):
    """사용자 한 명이 외부 앱 하나에 한 범위(`scope`)로 준 허락 — 화면의 「연결된 앱」
    한 줄이다. 강의실 범위는 그 강사의 모든 Class(ADR-0052), 공모전 범위는 그 사람이
    다룰 수 있는 무료 공모전이다(#870). 끊거나(`revoked_at`) 90일
    동안 쓰이지 않으면 끝나고, 끝난 허락에서 나온 토큰은 전부 거절된다 — 토큰을
    하나씩 지우지 않아도 이 행 하나가 문이다."""

    class RevokeReason(models.TextChoices):
        DISCONNECTED = "disconnected", "사용자가 끊음"
        EXPIRED = "expired", "90일 동안 쓰지 않음"
        WITHDRAWN = "withdrawn", "탈퇴"
        DORMANT = "dormant", "휴면"

    class Scope(models.TextChoices):
        CLASSROOM = "classroom", "강의실"
        CONTESTS = "contests", "공모전"

    #: 허락한 계정 — 이름이 `instructor` 인 것은 강의실에서 시작한 역사다(#512). 공모전
    #: 연결(`scope="contests"`)에서는 개최 자격자 본인이다. 클래스의 강사가 아니다.
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="connected_apps", on_delete=models.CASCADE
    )
    #: 이 허락이 여는 MCP 자원 하나(#870). 같은 앱이라도 범위마다 따로 허락한다.
    scope = models.CharField(
        max_length=20, choices=Scope.choices, default=Scope.CLASSROOM, db_default=Scope.CLASSROOM
    )
    client = models.ForeignKey(OAuthClient, related_name="grants", on_delete=models.CASCADE)
    #: 허락한 시점의 앱 이름 — 클라이언트가 나중에 다시 등록해도 목록이 흔들리지 않게.
    name = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=20, choices=RevokeReason.choices, blank=True, default="")

    class Meta:
        db_table = "classroom_connectedapp"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ConnectedApp(id={self.pk}, instructor={self.instructor_id})"


class OAuthAuthorizationCode(models.Model):
    """동의 화면에서 허락한 직후 한 번 쓰는 코드(PKCE S256). 짧게 살고 한 번만 바뀐다."""

    code_hash = models.CharField(max_length=64, unique=True)
    connected_app = models.ForeignKey(ConnectedApp, related_name="codes", on_delete=models.CASCADE)
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=128)
    resource = models.TextField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classroom_oauthauthorizationcode"



class OAuthToken(models.Model):
    """접근 토큰(1시간)과 갱신 토큰(쓸 때마다 새것으로 바뀐다). 해시만 저장한다."""

    class Kind(models.TextChoices):
        ACCESS = "access", "접근"
        REFRESH = "refresh", "갱신"

    token_hash = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    connected_app = models.ForeignKey(ConnectedApp, related_name="tokens", on_delete=models.CASCADE)
    resource = models.TextField()
    created_at = models.DateTimeField()
    #: 접근 토큰만 갖는다 — 갱신 토큰은 허락이 끝날 때까지 간다(90일 미사용 만료는
    #: 허락 쪽의 일이다).
    expires_at = models.DateTimeField(null=True, blank=True)
    #: 갱신 토큰이 새것으로 바뀌었거나, 회수(RFC 7009)된 시각.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classroom_oauthtoken"



class ConnectedAppConfirmation(models.Model):
    """연결된 앱이 되돌릴 수 없는 도구(#515)를 실행하기 전에 받는 확인 표 한 장.

    첫 호출이 미리보기와 함께 표를 내주고, 같은 도구를 **같은 인자로** 그 표와 함께 다시
    부르면 실행된다(`core.mcp_confirmation`). 표 자체는 저장하지 않고 해시만 둔다 —
    이 행을 읽을 수 있는 사람도 표를 다시 만들 수 없다.

    **한 번만, 그 앱·그 도구·그 인자에만, 짧게.** 인자는 `arguments_digest`(표를 뺀 인자의
    정규화 JSON 의 SHA-256)로 묶는다 — 대상 번호가 인자에 있으므로 다른 대상에는 쓰이지
    않는다. 실행이 성공한 트랜잭션에서 `used_at` 이 찍힌다; 실행이 거절되면(그 사이 참여자가
    냈다 등) 쓰기와 함께 되돌아가 표가 남지만, 같은 대상·같은 인자에만 쓰이고 시간이 지나면
    끝난다."""

    connected_app = models.ForeignKey(ConnectedApp, related_name="confirmations", on_delete=models.CASCADE)
    tool = models.CharField(max_length=64)
    arguments_digest = models.CharField(max_length=64)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "classroom_connectedappconfirmation"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ConnectedAppConfirmation(id={self.pk}, tool={self.tool})"
