import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type {
  GoldLabelStatus,
  SpecItemRead,
  VerificationDecision,
} from "../types/api";
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
  pending: boolean;
  defaultExpanded?: boolean;
  /** px-смещение для «прилипания» строки при разворачивании (под шапкой). */
  stickyTop?: number;
  /** Массовый выбор: строка отмечена / переключатель. */
  selected?: boolean;
  onToggleSelect?: (specItemId: string) => void;
  /** Закладка: строка помечена закладкой / переключатель (одна на спеку). */
  bookmarked?: boolean;
  onToggleBookmark?: (specItemId: string) => void;
  /** Подсветка + автопрокрутка к строке (переход «К закладке»). */
  highlight?: boolean;
}

export function SpecItemRow({
  item,
  onVerify,
  onUnverify,
  pending,
  defaultExpanded = false,
  stickyTop = 0,
  selected = false,
  onToggleSelect,
  bookmarked = false,
  onToggleBookmark,
  highlight = false,
}: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const rowRef = useRef<HTMLTableRowElement>(null);

  // Переход «К закладке»: когда строка становится подсвеченной — прокручиваем
  // её в центр области просмотра.
  useEffect(() => {
    if (highlight && rowRef.current) {
      rowRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlight]);

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
        ref={rowRef}
        className={
          "border-t border-slate-200 hover:bg-slate-50 " +
          (highlight
            ? "bg-amber-100 ring-2 ring-inset ring-amber-400 transition-colors "
            : bookmarked
              ? "bg-amber-50/60 "
              : item.verification
                ? "bg-slate-50/40"
                : "")
        }
      >
        <td className={`${td} text-center${tdSticky}`} style={stickyStyle}>
          {onToggleSelect && (
            <input
              type="checkbox"
              aria-label={`Выбрать строку ${item.line_number}`}
              checked={selected}
              onChange={() => onToggleSelect(item.id)}
              className="cursor-pointer"
            />
          )}
        </td>
        <td
          className={`px-2 py-2 tabular-nums text-slate-500${tdSticky}`}
          style={stickyStyle}
        >
          <div className="flex items-center gap-1">
            <span>{item.line_number}</span>
            {onToggleBookmark && (
              <button
                type="button"
                aria-pressed={bookmarked}
                title={bookmarked ? "Снять закладку" : "Поставить закладку (одна на спецификацию)"}
                onClick={() => onToggleBookmark(item.id)}
                className={
                  "text-base leading-none transition-colors " +
                  (bookmarked
                    ? "text-amber-500 hover:text-amber-600"
                    : "text-slate-300 hover:text-amber-500")
                }
              >
                {bookmarked ? "⚑" : "⚐"}
              </button>
            )}
            <GoldCell
              specItemId={item.id}
              goldRowId={item.gold_row_id}
              goldLabelStatus={item.gold_label_status}
            />
          </div>
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
              <button
                type="button"
                title="Передать в МОС (менеджеры отдела снабжения)"
                onClick={() => onVerify(item.id, "forwarded", null)}
                disabled={pending}
                className="inline-flex h-7 w-7 items-center justify-center rounded border border-slate-300 text-slate-500 hover:border-blue-500 hover:bg-blue-50 hover:text-blue-600 disabled:opacity-50"
              >
                ↗
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
          <td colSpan={8} className="bg-slate-50 px-4 py-4">
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
                  onClick={() => onVerify(item.id, "forwarded", null)}
                  disabled={pending}
                  title="Передать в группу МОС (менеджеры отдела снабжения)"
                >
                  ↗ Передать
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

const GOLD_STATUSES: GoldLabelStatus[] = [
  "найдено",
  "аналог",
  "не найдено",
  "сомнительно",
];

/**
 * Контрол gold dataset в колонке «№» (справа от закладки). Если строка уже в
 * эталоне — звезда подсвечена, по клику можно сменить статус-метку или убрать.
 * Если нет — по клику выбираешь статус («найдено»/«аналог»/…), строка сеется в
 * gold через POST /gold-rows/from-spec-item (эталон берётся из выбранной позиции).
 */
function GoldCell({
  specItemId,
  goldRowId,
  goldLabelStatus,
}: {
  specItemId: string;
  goldRowId: string | null;
  goldLabelStatus: GoldLabelStatus | null;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inGold = goldRowId != null;

  // Широкая инвалидация ["specifications"] обновит и список строк (индикатор).
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["specifications"] });
    qc.invalidateQueries({ queryKey: ["gold-rows"] });
    setOpen(false);
  };
  const onErr = () => window.alert("Не удалось изменить gold dataset");

  const add = useMutation({
    mutationFn: (status: GoldLabelStatus) =>
      api.createGoldRowFromSpecItem({
        spec_item_id: specItemId,
        label_status: status,
      }),
    onSuccess: invalidate,
    onError: onErr,
  });
  const change = useMutation({
    mutationFn: (status: GoldLabelStatus) =>
      api.updateGoldRow(goldRowId as string, { label_status: status }),
    onSuccess: invalidate,
    onError: onErr,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteGoldRow(goldRowId as string),
    onSuccess: invalidate,
    onError: onErr,
  });
  const busy = add.isPending || change.isPending || remove.isPending;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        title={
          inGold
            ? `В gold dataset: ${goldLabelStatus}`
            : "Добавить в gold dataset"
        }
        className={
          "text-base leading-none transition-colors disabled:opacity-50 " +
          (inGold
            ? "text-amber-500 hover:text-amber-600"
            : "text-slate-300 hover:text-amber-500")
        }
      >
        {inGold ? "★" : "☆"}
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-48 rounded-md border border-slate-200 bg-white p-1 text-left shadow-lg">
          <div className="px-2 py-1 text-[10px] uppercase tracking-wide text-slate-400">
            {inGold ? "Входит в gold dataset" : "В gold dataset как…"}
          </div>
          {GOLD_STATUSES.map((s) => {
            const active = inGold && s === goldLabelStatus;
            return (
              <button
                key={s}
                type="button"
                disabled={busy || active}
                onClick={() => (inGold ? change.mutate(s) : add.mutate(s))}
                className={
                  "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sm hover:bg-slate-50 disabled:opacity-60 " +
                  (active ? "font-semibold text-amber-700" : "text-slate-700")
                }
              >
                <span className="text-amber-500">{active ? "●" : "○"}</span>
                {s}
              </button>
            );
          })}
          {inGold && (
            <button
              type="button"
              disabled={busy}
              onClick={() => remove.mutate()}
              className="mt-1 flex w-full items-center rounded px-2 py-1 text-left text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              ✕ Убрать из gold dataset
            </button>
          )}
        </div>
      )}
    </div>
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
    case "forwarded":
      return <Badge tone="info">Передано в МОС</Badge>;
    default:
      return <Badge>{v.decision}</Badge>;
  }
}
