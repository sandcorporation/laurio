"""강의실 「다시 채점」 e2e(#1317)용 — 아직 점수가 없는 참여자 시도 하나에 「채점 실패」(실패 상한) 점수를 심고
`{submission_id, score_id}` JSON 을 마지막 줄에 찍는다.

실제로는 채점이 실패 상한(`SCORING_FAILURE_LIMIT`)까지 실패하거나 영구 오류일 때 생기는 점수다. e2e 스택의 흉내
채점기는 실패하지 않으므로 그 끝 상태를 채점과 같은 함수(`scoring._finalize_platform_failure`)로 직접 만든다 —
실패 상한에 이르는 길은 backend 시험이 지킨다. 호출마다 다른 시도에 심으므로 줄 세울 일이 없다.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from classroom import scoring
from classroom.current_score import original_score
from classroom.models import ClassroomSubmission
from core.management.stdout_utf8 import write_stdout_utf8


class Command(BaseCommand):
    help = "점수가 없는 강의실 시도 하나에 「채점 실패」 점수를 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--submission-id", type=int, required=True)

    def handle(self, *args, **options) -> None:
        submission = ClassroomSubmission.objects.select_related("problem", "member__user").filter(
            pk=options["submission_id"]
        ).first()
        if submission is None:
            raise CommandError("그 시도가 없다.")
        if original_score(submission) is not None:
            raise CommandError("이미 점수가 있는 시도다.")
        score = scoring._finalize_platform_failure(submission, list(submission.problem.checklist_items.all()))
        write_stdout_utf8(
            self.stdout, json.dumps({"submission_id": submission.pk, "score_id": score.pk}, ensure_ascii=False) + "\n"
        )
