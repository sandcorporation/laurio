// 참여자 본인의 완성도(#883, ADR-0072) — 강사가 공개를 켰을 때만 그린다. 다른 참여자의 이름·점수는 없다.
import { Badge, Card, CardHeader, Num } from "@/app/components/ui";
import type { MyQuality } from "@/lib/quality/api";
import { formatPoints, formatQualityTotal, myRankLine } from "@/lib/quality/format";

export function MyQualityCard({ quality }: { quality: MyQuality }) {
  return (
    <Card>
      <CardHeader title="완성도" />
      <div className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span data-testid="my-quality-rank" className="text-[13.5px]">
            {myRankLine(quality.rank, quality.total)}
          </span>
          <Num className="text-[18px] font-semibold">
            <span data-testid="my-quality-completeness">{formatQualityTotal(quality.score_total, quality.max_total)}</span>
          </Num>
        </div>
        <ul className="flex flex-col gap-2.5 border-t border-rule pt-3">
          {quality.items.map((item) => (
            <li key={item.item_id} data-testid={`my-quality-item-${item.item_id}`} className="flex flex-col gap-0.5 text-[12.5px]">
              <span className="flex flex-wrap items-center gap-2">
                <Badge tone={item.required ? "verified" : "neutral"}>{item.required ? "필수" : "선택"}</Badge>
                <span className="min-w-0 flex-1 font-medium">{item.label}</span>
                <Num className="text-ink/60">
                  {item.score}/5 · {formatPoints(item.item_points)} / {item.points}점
                </Num>
              </span>
              <span className="text-ink/70">{item.reasoning}</span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
