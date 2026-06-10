import { useState } from "react";
import type { SpecItemRead, VerificationDecision } from "../types/api";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { CandidatesTable } from "./CandidatesTable";
import { CatalogSearchBox } from "./CatalogSearchBox";
import { ConfidenceCell } from "./ConfidenceCell";
import { formatQuantity } from "../lib/format";

interface Props {
  item: SpecItemRead;
  onVerify: (
    specItemId: string,
    decision: VerificationDecision,
    chosenItemId?: string | null,
  ) => void;
  onUnverify?: (specItemId: string) => void;
  onAddToGold?: (specItemId: string) => void;
  pending: boolean;
  defaultExpanded?: boolean;
  /** px-смещение для «прилипания» строки при разворачивании (под шапкой). */
  stickyTop?: number;
}

export function SpecItemRow({
  item,
  onVerify,
  onUnverify,
  onAddToGold,
  pending,
  defaultExpanded = false,
  stickyTop = 0,
}: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const verificationBadge = renderVerificationBadge(item);
  const topCatalog = item.candidates_catalog[0];
  // Топ-кандидат для инлайн-подтверждения: каталог приоритетнее прайсов.
  const topMatch = topCatalog ?? item.candidates_suppliers[0] ?? null;
  // «Выбранная позиция»: после подтверждения — реально выбранная (в т.ч.
  // найденная поиском, не из топ-кандидатов); до выбора — топ-кандидат.
  const chosen = item.verification?.chosen_item ?? null;
  // Уверенность сопоставления для строки: после матчинга и до решения это
  // топ-кандидат; если позиция уже выбрана — кандидат с этим item_id (поиск
  // вне топа кандидатов уверенности не несёт → прочерк).
  const chosenItemId = item.verification?.chosen_item_id ?? null;
  const matchCandidate = chosenItemId
    ? [...item.candidates_catalog, ...item.candidates_suppliers].find(
        (c) => c.item_id === chosenItemId,
      ) ?? null
    : topCatalog ?? null;

  // При разворачивании строка товара «прилипает» под шапкой — видно, что
  // подбираем, пока листаешь кандидатов/результаты поиска.
  const td = "px-4 py-2";
  const tdSticky = expanded
    ? " sticky z-10 bg-blue-50 border-b border-blue-200"
    : "";
  const stickyStyle = expanded ? { top: stickyTop } : undefined;

  return (
    <>
      <tr
        className={
          "border-t border-slate-200 hover:bg-slate-50 " +
          (item.verification ? "bg-slate-50/40" : "")
        }
      >
        <td
          className={`${td} tabular-nums text-slate-500${tdSticky}`}
          style={stickyStyle}
        >
          {item.line_number}
        </td>
        <td className={`${td}${tdSticky}`} style={stickyStyle}>
          <div className="font-medium">{item.name_raw}</div>
          <div className="mt-0.5 text-xs text-slate-500">
            {item.article_raw && (
              <span className="font-mono">{item.article_raw}</span>
            )}
            {item.manufacturer_raw && (
              <span className="ml-2">{item.manufacturer_raw}</span>
            )}
          </div>
          {item.attributes_raw && (
            <div
              className="mt-0.5 line-clamp-2 text-xs text-slate-400"
              title={item.attributes_raw}
            >
              ⚙ {item.attributes_raw}
            </div>
          )}
        </td>
        <td
          className={`${td} tabular-nums text-slate-600${tdSticky}`}
          style={stickyStyle}
        >
          {formatQuantity(item.quantity)}
          {item.quantity != null && item.unit_raw ? ` ${item.unit_raw}` : ""}
        </td>
        <td className={`${td}${tdSticky}`} style={stickyStyle}>
          {chosen ? (
            <div className="text-sm">
              <div
                className="line-clamp-2 font-medium text-emerald-700"
                title={chosen.name}
              >
                {chosen.name}
              </div>
              <div className="text-xs text-slate-500">
                {chosen.article}
              </div>
            </div>
          ) : topCatalog ? (
            <div className="text-sm">
              <div className="line-clamp-2" title={topCatalog.name}>
                {topCatalog.name}
              </div>
              <div className="text-xs text-slate-500">
                {topCatalog.article}
              </div>
            </div>
          ) : (
            <span className="text-sm text-slate-400">Нет совпадений</span>
          )}
        </td>
        <td className={`${td}${tdSticky}`} style={stickyStyle}>
          {matchCandidate ? (
            <ConfidenceCell
              confidence={matchCandidate.confidence}
              explanation={matchCandidate.explanation}
              muted={!!item.verification}
            />
          ) : (
            <span className="text-sm text-slate-400">—</span>
          )}
        </td>
        <td className={`${td}${tdSticky}`} style={stickyStyle}>
          {item.verification ? (
            <div className="flex items-center gap-2">
              {verificationBadge}
              {onUnverify && (
                <button
                  type="button"
                  title="Вернуть в работу"
                  onClick={() => onUnverify(item.id)}
                  disabled={pending}
                  className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
                >
                  ↩
                </button>
              )}
            </div>
          ) : topMatch ? (
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                title="Подтвердить выбранную позицию"
                onClick={() => onVerify(item.id, "confirmed", topMatch.item_id)}
                disabled={pending}
                className="inline-flex h-7 w-7 items-center justify-center rounded border border-slate-300 text-slate-500 hover:border-emerald-500 hover:bg-emerald-50 hover:text-emerald-600 disabled:opacity-50"
              >
                ✓
              </button>
              <button
                type="button"
                title="Отклонить"
                onClick={() => onVerify(item.id, "rejected", null)}
                disabled={pending}
                className="inline-flex h-7 w-7 items-center justify-center rounded border border-slate-300 text-slate-500 hover:border-red-500 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
              >
                ✕
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="text-sm text-blue-600 hover:underline"
            >
              Подобрать
            </button>
          )}
        </td>
        <td className={`${td} text-right${tdSticky}`} style={stickyStyle}>
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
          <td colSpan={7} className="bg-slate-50 px-4 py-4">
            <div className="space-y-3">
              {/* Поиск — наверху, предзаполнен именем позиции. Контекст
                  (что подбираем) виден в «прилипшей» строке товара выше. */}
              <CatalogSearchBox
                initialQuery={item.name_raw}
                onPick={(itemId) => onVerify(item.id, "confirmed", itemId)}
                disabled={pending}
              />

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
                allowRelink
              />

              <div className="flex items-center justify-end gap-2 pt-2">
                {item.verification && onUnverify && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mr-auto text-amber-700 hover:bg-amber-50"
                    onClick={() => onUnverify(item.id)}
                    disabled={pending}
                  >
                    ↺ Сбросить решение
                  </Button>
                )}
                {onAddToGold && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className={
                      (item.verification ? "" : "mr-auto ") +
                      "text-amber-800 hover:bg-amber-50"
                    }
                    onClick={() => onAddToGold(item.id)}
                    disabled={pending}
                    title="Добавить строку в золотой датасет (эталон берётся из выбранной позиции)"
                  >
                    ★ в gold dataset
                  </Button>
                )}
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
    return <Badge tone="neutral">Не проверено</Badge>;
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
