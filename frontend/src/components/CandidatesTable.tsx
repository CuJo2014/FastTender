import type { CandidateRead } from "../types/api";
import { Button } from "./ui/Button";
import { Badge } from "./ui/Badge";
import { ConfidenceCell } from "./ConfidenceCell";
import { formatPrice } from "../lib/format";

interface Props {
  title: string;
  candidates: CandidateRead[];
  selectedItemId: string | null;
  onConfirm: (itemId: string) => void;
  disabled?: boolean;
}

export function CandidatesTable({
  title,
  candidates,
  selectedItemId,
  onConfirm,
  disabled,
}: Props) {
  if (candidates.length === 0) {
    return (
      <div className="rounded-md border border-slate-200 p-3 text-sm text-slate-500">
        <div className="mb-1 text-xs font-medium uppercase text-slate-500">{title}</div>
        Нет кандидатов
      </div>
    );
  }

  return (
    <div className="rounded-md border border-slate-200">
      <div className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium uppercase text-slate-500">
        {title}
      </div>
      <table className="min-w-full text-sm">
        <thead className="text-left text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2 w-10">#</th>
            <th className="px-3 py-2 w-20">Conf.</th>
            <th className="px-3 py-2">Артикул</th>
            <th className="px-3 py-2">Наименование</th>
            <th className="px-3 py-2">Бренд</th>
            <th className="px-3 py-2 text-right">Цена</th>
            <th className="px-3 py-2 w-32" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200">
          {candidates.map((cand) => {
            const isSelected = cand.item_id === selectedItemId;
            return (
              <tr
                key={cand.item_id}
                className={isSelected ? "bg-green-50" : "hover:bg-slate-50"}
              >
                <td className="px-3 py-2 tabular-nums text-slate-500">
                  {cand.rank}
                </td>
                <td className="px-3 py-2">
                  <ConfidenceCell
                    confidence={cand.confidence}
                    explanation={cand.explanation}
                  />
                </td>
                <td className="px-3 py-2 font-mono text-xs">
                  {cand.article ?? "—"}
                  {cand.code_1c && (
                    <div className="mt-0.5 font-sans text-[10px] text-slate-400">
                      1С: {cand.code_1c}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2">
                  {cand.name}
                  {cand.category_path && (
                    <div className="mt-0.5 text-xs text-slate-400">
                      {cand.category_path}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-slate-600">
                  {cand.manufacturer ?? "—"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatPrice(cand.price)}
                  {cand.currency && (
                    <span className="ml-1 text-xs text-slate-400">
                      {cand.currency}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {isSelected ? (
                    <Badge tone="success">Выбрано</Badge>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onConfirm(cand.item_id)}
                      disabled={disabled}
                    >
                      Выбрать
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
