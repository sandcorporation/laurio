"""`manage.py feedback_report` — 대장 전달(`scripts/feedback.sh`, #1240)이 운영 backend 에서 부른다 (#1239).

읽기: `show <번호>` · `summary <번호>` · `list [--limit N]` · `screenshot <번호>`
전달: `take [--limit N]` · `untake <번호>` · `mark-forwarded <번호>`
쓰기: `status <번호> <상태> --note "<처리 글>"` — 운영자 화면과 같은 서비스 함수, 같은 알림.
      `--note -` 면 처리 글을 표준 입력에서 읽는다(ssh 를 거치며 따옴표·한글이 깨지지 않게).

`list`·`take`·`summary` 는 번호·갈래·앱·받은 시각만 JSON 한 줄씩 낸다 — 내용·그림은 전달 메일에 싣지 않는다.
`show` 는 사람이 읽는 글이다(내용·상태·이력, 스크린샷은 있는지만).
`screenshot` 은 그림 바이트를 표준출력에 그대로 낸다(#1347) — `feedback.sh screenshot` 이 ssh 로 받아 work 의 임시
파일로 쓴다. 서명 주소를 만들지 않으므로 주소·키가 어디에도 찍히지 않는다. 실패는 종료 코드로 가른다:
제보 없음 4 · 스크린샷 없음 5 · 버킷에 그림 없음(보존 기간이 지나 지워짐 등) 6.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError

from feedback import screenshots, services
from feedback.models import FeedbackReport

NO_REPORT = 4
NO_SCREENSHOT = 5
SCREENSHOT_GONE = 6


def _summary(report: FeedbackReport) -> str:
    return json.dumps(
        {
            "id": report.pk,
            "kind": report.kind,
            "app": report.app,
            "received_at": report.received_at.isoformat(),
        },
        ensure_ascii=False,
    )


class Command(BaseCommand):
    help = "건의·버그 제보 — 읽기·전달 표시·상태 바꾸기"

    def add_arguments(self, parser: ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="action", required=True)
        show = sub.add_parser("show")
        show.add_argument("report_id", type=int)
        for name in ("list", "take"):
            p = sub.add_parser(name)
            p.add_argument("--limit", type=int, default=20)
        for name in ("summary", "untake", "mark-forwarded", "screenshot"):
            p = sub.add_parser(name)
            p.add_argument("report_id", type=int)
        status = sub.add_parser("status")
        status.add_argument("report_id", type=int)
        status.add_argument("to_status", choices=FeedbackReport.Status.values)
        status.add_argument("--note", default="")

    def handle(self, *args: object, **options: object) -> None:
        action = options["action"]
        if action == "show":
            self._show(int(options["report_id"]))
        elif action == "list":
            for report in services.pending_reports(int(options["limit"])):
                self.stdout.write(_summary(report))
        elif action == "take":
            for report in services.take_reports(int(options["limit"])):
                self.stdout.write(_summary(report))
        elif action == "summary":
            report = FeedbackReport.objects.filter(pk=int(options["report_id"])).first()
            if report is None:
                raise CommandError(f"제보 #{options['report_id']} 이(가) 없습니다.")
            self.stdout.write(_summary(report))
        elif action == "screenshot":
            self._screenshot(int(options["report_id"]))
        elif action == "untake":
            if not services.untake_report(int(options["report_id"])):
                raise CommandError("되돌릴 제보가 없습니다(없거나 이미 전달됨).")
        elif action == "mark-forwarded":
            if not services.mark_forwarded(int(options["report_id"])):
                raise CommandError("표시할 제보가 없습니다(없거나 이미 전달됨).")
        elif action == "status":
            note = str(options["note"])
            if note == "-":
                note = sys.stdin.read()
            self._status(int(options["report_id"]), str(options["to_status"]), note)

    def _show(self, report_id: int) -> None:
        report = FeedbackReport.objects.select_related("reporter").filter(pk=report_id).first()
        if report is None:
            raise CommandError(f"제보 #{report_id} 이(가) 없습니다.")
        lines = [
            f"제보 #{report.pk} · {report.get_kind_display()} · {report.get_app_display()}",
            f"상태: {report.get_status_display()}",
            f"받은 시각: {report.received_at.isoformat()}",
            f"제보자: {report.reporter.pk}",
            f"화면: {report.page_url}",
            f"브라우저: {report.user_agent}",
            f"화면 크기: {report.screen_width or '-'}x{report.screen_height or '-'}",
            f"스크린샷: {'있음' if report.screenshot_key else '없음'}",
            "",
            report.body,
        ]
        if report.resolution_note:
            lines += ["", f"처리 글: {report.resolution_note}"]
        changes = list(report.status_changes.all())
        if changes:
            lines += ["", "이력:"]
            lines += [
                f"- {c.changed_at.isoformat()} {c.actor_label}: {c.from_status} → {c.to_status}"
                + (f" — {c.note}" if c.note else "")
                for c in changes
            ]
        self.stdout.write("\n".join(lines))

    def _screenshot(self, report_id: int) -> None:
        report = FeedbackReport.objects.filter(pk=report_id).first()
        if report is None:
            raise CommandError(f"제보 #{report_id} 이(가) 없습니다.", returncode=NO_REPORT)
        if not report.screenshot_key:
            raise CommandError(f"제보 #{report_id} 에는 스크린샷이 없습니다.", returncode=NO_SCREENSHOT)
        content = screenshots.read(report.screenshot_key)
        if content is None:
            raise CommandError(
                f"제보 #{report_id} 의 스크린샷이 저장소에 없습니다(보존 기간이 지났을 수 있다).",
                returncode=SCREENSHOT_GONE,
            )
        # 바이트는 글 출력(self.stdout)이 아니라 표준출력 그 자체로 낸다 — ssh 가 그대로 실어 나른다.
        sys.stdout.buffer.write(content)
        sys.stdout.buffer.flush()

    def _status(self, report_id: int, to_status: str, note: str) -> None:
        try:
            report = services.change_status(
                report_id=report_id,
                to_status=to_status,
                note=note,
                operator=None,
                actor_label=services.COMMAND_ACTOR_LABEL,
            )
        except (
            services.FeedbackNotFoundError,
            services.FeedbackConflictError,
            services.FeedbackValidationError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"제보 #{report.pk}: {report.get_status_display()}")
