import { useState } from "react";
import type { SpecItemRead, VerificationDecision } from "../types/api";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { CandidatesTable } from "./CandidatesTable";
import { CatalogSearchBox } from "./CatalogSearchBox";

interface Props {
  item: SpecItemRead;
  onVerify: (
    specItemId: string,
    decision: VerificationDecision,
    chosenItemId?: string | null,
  ) => void;
  pending: boolean;
  defaultExpanded?: boolean;
}

export function SpecItemRow({ item, onVerify, pending, defaultExpanded = false }: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const verificationBadge = renderVerificationBadge(item);
  const topCatalog = item.candidates_catalog[0];
  // «Выбранная позиция»: после подтверждения — реально выбранная (в т.ч.
  // найденная поиском, не из топ-кандидатов); до выбора — топ-кандидат.
  const chosen = item.verification?.chosen_item ?? null;

  return (
    <>
      <tr
        className={
          "border-t border-slate-200 hover:bg-slate-50 " +
          (item.verification ? "bg-slate-50/40" : "")
        }
      >
        <td className="px-4 py-2 tabular-nums text-slate-500">
          {item.line_number}
        </td>
        <td className="px-4 py-2">
          <div className="font-medium">{item.name_raw}</div>
          <div className="mt-0.5 text-xs text-slate-500">
            {item.article_raw && (
              <span className="font-mono">{item.article_raw}</span>
            )}
            {item.manufacturer_raw && (
              <span className="ml-2">{item.manufacturer_raw}</span>
            )}
          </div>
        </td>
        <td className="px-4 py-2 tabular-nums text-slate-600">
          {item.quantity ?? "—"} {item.unit_raw ?? ""}
        </td>
        <td className="px-4 py-2">
          {chosen ? (
            <div className="text-sm">
              <div className="line-clamp-1 font-medium text-emerald-700">
                {chosen.name}
              </div>
              <div className="text-xs text-slate-500">
                {chosen.article}
              </div>
            </div>
          ) : topCatalog ? (
            <div className="text-sm">
              <div className="line-clamp-1">{topCatalog.name}</div>
              <div className="text-xs text-slate-500">
                {topCatalog.article}
              </div>
            </div>
          ) : (
            <span className="text-sm text-slate-400">Нет совпадений</span>
          )}
        </td>
        <td className="px-4 py-2">{verificationBadge}</td>
        <td className="px-4 py-2 text-right">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Свернуть" : "Кандидаты"}
          </Button>
        </td>
      </tr>

      {expanded && (
        <tr>
          <td colSpan={6} className="bg-slate-50 px-4 py-4">
            <div className="space-y-3">
              <CandidatesTable
                title="Из каталога компании"
                candidates={item.candidates_catalog}
                selectedItemId={item.verification?.chosen_item_id ?? null}
                onConfirm={(itemId) => onVerify(item.id, "confirmed", itemId)}
                disabled={pending}
              />
              <CandidatesTable
                title="Из прайсов поставщиков"
                candidates={item.candidates_suppliers}
                selectedItemId={item.verification?.chosen_item_id ?? null}
                onConfirm={(itemId) => onVerify(item.id, "confirmed", itemId)}
                disabled={pending}
              />

              <CatalogSearchBox
                onPick={(itemId) => onVerify(item.id, "confirmed", itemId)}
                disabled={pending}
              />

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onVerify(item.id, "not_found", null)}
                  disabled={pending}
                >
                  Не найдено
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onVerify(item.id, "rejected", null)}
                  disabled={pending}
                >
                  Отклонить
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onVerify(item.id, "new_item_requested", null)}
                  disabled={pending}
                >
                  Завести новую позицию
                </Button>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function renderVerificationBadge(item: SpecItemRead) {
  const v = item.verification;
  if (!v) {
    return <Badge tone="neutral">Не верифицировано</Badge>;
  }
  switch (v.decision) {
    case "confirmed":
      return <Badge tone="success">Подтверждено</Badge>;
    case "rejected":
      return <Badge tone="danger">Отклонено</Badge>;
    case "not_found":
      return <Badge tone="warning">Не найдено</Badge>;
    case "new_item_requested":
      return <Badge tone="info">Новая позиция</Badge>;
    default:
      return <Badge>{v.decision}</Badge>;
  }
}
