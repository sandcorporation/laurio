"""강의실 Celery 태스크 — 모델 단가 표 대조(#798)."""

from celery import shared_task


@shared_task(name="classroom.check_price_drift", ignore_result=True)
def check_price_drift() -> dict:
    """매일 04:10(서울) 모델 단가 표를 LiteLLM 단가 파일과 대조해 다르면 GlitchTip 으로 알린다(#798).
    표는 고치지 않는다 — `classroom.price_drift` 참고. 02:00 DB 백업과 겹치지 않는다."""

    from classroom.price_drift import run_price_drift_check

    return run_price_drift_check()


@shared_task(name="classroom.refresh_scoring_models", ignore_result=True)
def refresh_scoring_models(class_id: int) -> None:
    """5분 넘은 채점 모델 목록을 응답 뒤에 다시 묻고 캐시를 갈아 둔다(#1051). 실패하면 묵은 캐시를 둔다."""

    from classroom.scoring_model_catalog import refresh_cached_models

    refresh_cached_models(class_id)
