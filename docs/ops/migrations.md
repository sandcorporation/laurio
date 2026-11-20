# 마이그레이션 — 호환되는 것만, 파괴적 변경은 두 단계

**직전 판 코드가 새 스키마에서 돌아야 한다**(spec #1079 결정 7). 배포는 migrate 를 먼저 돌리고 옛 컨테이너가
요청을 받는 채로 겹쳐 바꾼다([배포](deploy.md), ADR-0053). 되돌릴 때는 코드만 되돌리고 스키마는 그대로 둔다
(revert PR·`ROLLBACK_SHA`, 자동 되돌리기 #1092). 그래서 base(병합 대상) 코드가 읽고 쓰는 테이블·칸을 지우거나,
이름을 바꾸거나, 그 코드의 INSERT·UPDATE 가 깨지게 바꾸는 마이그레이션은 병합되지 않는다.

## 검사

`scripts/ci/migration_compat.py` — PR 검사의 static 묶음(`sub-checks-inside.sh` 「마이그레이션 호환」)이 돈다.
base 에 있던 마이그레이션까지 쌓은 상태를 「base 코드가 쓰는 스키마」로 보고, 이 변경이 더한 마이그레이션을
그래프 순서로 걸으며 그 스키마를 깨는 DB 연산을 찾는다. base 는 PR 이면 병합 대상, 대기열이면 머지 커밋의 base,
main push 면 직전 main 이다(`pr-check.yml` 의 `CODEMIT_MIGRATION_BASE`).

```bash
cd backend && uv run python ../scripts/ci/migration_compat.py --base origin/main   # DJANGO_* 환경 필요, DB 는 안 붙는다
```

| 거절 | 통과 |
| --- | --- |
| base 코드가 쓰는 칸·다대다·테이블을 지움(`RemoveField`·`DeleteModel`·`RunSQL DROP`) | 상태에서만 지움(`SeparateDatabaseAndState(state_operations=…)`) |
| 칸·테이블 이름 바꾸기(`RenameField`·`RenameModel`·`AlterModelTable`·`db_column`) | 이 변경이 만든 테이블에 대한 모든 연산 |
| DB 기본값 없는 NOT NULL 칸 더하기(`default=` 는 DB 에 남지 않는다) | `null=True` 또는 `db_default` 로 칸 더하기, 다대다 더하기 |
| null 막기, DB 기본값 지우기, 고유 제약 더하기, 칸 타입 바꾸기 | choices·help_text·`default`·검증기만 바꾸기, varchar 넓히기, varchar → text |
| 판정할 수 없는 RunSQL(`ALTER TABLE` 의 다른 동작, `TRUNCATE` 등) | `UPDATE`·`INSERT`·`DELETE`·`CREATE …`, `SET DEFAULT`·`DROP NOT NULL`, nullable `ADD COLUMN` |

보지 않는 것: `AddConstraint`·고유 색인(옛 코드의 쓰기가 새 제약을 어기는지는 코드를 봐야 안다), `RunPython`
(데이터만 바꾼다고 본다). 리뷰에서 본다.

**예외 표식은 없다.** 되돌리기가 늘 옛 코드를 새 스키마 위에 올리므로, 「이번만 호환되지 않음」을 허락하면
그 배포는 되돌릴 수 없다. 옛 `# ROLLING-DEPLOY-SAFE:` 주석은 기록으로만 남고 검사가 읽지 않는다.
`deploy.sh` 의 `ROLLING-DEPLOY-UNSAFE` 길(넷을 내리고 올림)은 닿지 않아 지웠다(#1092).

## 두 단계 — 코드 먼저, 정리는 다음 배포

첫 PR 이 main 에 들어가 배포된 뒤 둘째 PR 을 연다. 둘째 PR 의 base 에는 첫 PR 의 상태 변경이 있으므로 검사가
통과한다 — 같은 PR 에 둘을 넣으면 base 상태에 칸이 남아 있어 거절된다.

**칸 지우기**

1. 코드에서 그 칸을 지우고 마이그레이션을 상태에서만 지우게 고친다. 칸이 NOT NULL 이면 같은 마이그레이션의
   `database_operations` 에서 `null=True` 나 `db_default` 를 달아 새 코드의 INSERT 가 빼먹어도 되게 한다.
   ```python
   migrations.SeparateDatabaseAndState(
       database_operations=[migrations.AlterField("class", "token_budget", models.IntegerField(null=True))],
       state_operations=[migrations.RemoveField("class", "token_budget")],
   )
   ```
2. 다음 PR — DB 에서 지운다: `RunSQL("ALTER TABLE <테이블> DROP COLUMN IF EXISTS <칸>", reverse_sql=…)`.
   실제 예: `classroom.0029` → `classroom.0032`(#629·#665).

**테이블 지우기** — 첫 PR 은 `SeparateDatabaseAndState(state_operations=[DeleteModel(…)])`, 다음 PR 은
`RunSQL("DROP TABLE IF EXISTS <테이블>")`.

**이름 바꾸기** — 바꾸지 않는 것이 기본이다. 모델·필드 이름만 바꾸려면 `db_column`·`db_table` 로 옛 이름을 잡아
DB 를 그대로 둔다. DB 이름까지 바꿔야 하면 새 칸 더하기(nullable) → 코드가 둘 다 쓰고 옮김 → 옛 칸 상태에서
지우기 → 다음 배포에 DB 에서 지우기.

**NOT NULL 칸 더하기** — `db_default` 를 단다. 기본값이 없어야 하는 칸이면 DB 에는 nullable 로 더하고 모델만
NOT NULL 로 둔다(`SeparateDatabaseAndState` 의 `database_operations` 는 `null=True`, `state_operations` 는
`null=False`). 이미 있는 nullable 칸의 null 을 DB 에서 막는 것은 언제나 거절된다 — base 코드는 None 을 쓸 수 있다.

**타입 바꾸기** — 새 칸을 더해 두 단계로 옮긴다(이름 바꾸기와 같다).
