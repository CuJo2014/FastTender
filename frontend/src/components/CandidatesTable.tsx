import { useState } from "react";
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
  // Пустые секции свёрнуты по умолчанию — не занимают место, поиск поднимается выше.
  const [open, setOpen] = useState(candidates.length > 0);

  return (
    <div className="rounded-md border border-slate-200">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={
          "flex w-full items-center justify-between bg-slate-50 px-3 py-2 text-xs font-medium uppercase text-slate-500 hover:bg-slate-100 " +
          (open ? "border-b border-slate-200" : "")
        }
      >
        <span>
          {title} <span className="text-slate-400">({candidates.length})</span>
        </span>
        <span className="text-slate-400">{open ? "свернуть ▾" : "развернуть ▸"}</span>
      </button>

      {open && candidates.length === 0 && (
        <div className="p-3 text-sm text-slate-500">Нет кандидатов</div>
      )}

      {open && candidates.length > 0 && (
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
                  {cand.supplier_sku && (
                    <div
                      className="mt-0.5 font-sans text-[10px] text-slate-400"
                      title="Внутренний SKU прайса поставщика"
                    >
                      ID: {cand.supplier_sku}
                    </div>
                  )}
                  {cand.linked_catalog && (
                    <div
                      className={
                        "mt-0.5 inline-block rounded px-1 font-sans text-[10px] " +
                        (cand.catalog_link_source === "manual"
                          ? "bg-blue-50 text-blue-700"
                          : "bg-slate-100 text-slate-500")
                      }
                      title={
                        (cand.catalog_link_source === "manual"
                          ? "Связь установлена вручную: "
                          : "Авто-связка: ") +
                        cand.linked_catalog.name +
                        (cand.linked_catalog.manufacturer
                          ? ` (${cand.linked_catalog.manufacturer})`
                          : "")
                      }
                    >
                      → Каталог{" "}
                      {cand.linked_catalog.code_1c ??
                        cand.linked_catalog.article ??
                        ""}
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
      )}
    </div>
  );
}
