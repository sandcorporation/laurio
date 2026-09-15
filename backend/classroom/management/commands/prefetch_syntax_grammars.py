"""문법 검사가 쓰는 tree-sitter 문법을 미리 받아 둔다(#409 후속).

백엔드 이미지를 구울 때와 CI 테스트 전에 부른다 — 채점 중에는 문법을 내려받지 않는다
(`classroom.syntax_check.prefetch_tree_sitter_grammars` 의 docstring 참고).
"""

from django.core.management.base import BaseCommand

from classroom.syntax_check import prefetch_tree_sitter_grammars


class Command(BaseCommand):
    help = "문법 검사가 쓰는 tree-sitter 문법을 캐시에 미리 받아 둔다."

    def handle(self, *args, **options):
        languages = prefetch_tree_sitter_grammars()
        self.stdout.write(f"tree-sitter 문법 {len(languages)}개 준비: {', '.join(languages)}")
