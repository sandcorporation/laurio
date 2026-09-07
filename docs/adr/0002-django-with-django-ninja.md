# Django + django-ninja를 쓴다

Status: Amended by ADR-0019 (2026-08-28 결정)

이 서비스는 HTTP 처리량보다 운영 화면(이의제기 심판, 정산 감사, 부정행위 조사)과 스키마 진화가 부담이 크다. FastAPI는 인증·권한·마이그레이션·백오피스를 전부 직접 조립해야 해서 초기 비용이 크고, Django + DRF는 그 문제가 없는 대신 API 계층이 장황하다. Django의 ORM·마이그레이션·admin·인증을 그대로 쓰면서 API만 django-ninja로 얹어, Pydantic 스키마와 OpenAPI 자동 생성을 함께 얻는다.

## Consequences

운영 백오피스는 Django admin으로 공짜로 시작하고, 필요해지면 `admin/`의 별도 SPA로 옮긴다. django-ninja는 DRF보다 생태계가 작으므로, DRF 전용 서드파티 패키지에 의존하는 설계는 피한다.
