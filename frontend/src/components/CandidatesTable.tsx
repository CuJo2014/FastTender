import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { CandidateRead, CatalogSearchResult } from "../types/api";
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
  /** Разрешить ручную привязку прайс-позиции к карточке каталога (P3.6). */
  allowRelink?: boolean;
}

export function CandidatesTable({
  title,
  candidates,
  selectedItemId,
  onConfirm,
  disabled,
  allowRelink,
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
                  {allowRelink && cand.source_type === "supplier_pricelist" && (
                    <CatalogLinkEditor
                      itemId={cand.item_id}
                      hasLink={cand.linked_catalog != null}
                    />
                  )}
                </td>
                <td className="px-3 py-2">
                  {cand.name}
                  {cand.explanation.linked_via_supplier && (
                    <span
                      className="ml-1.5 inline-block rounded bg-amber-50 px-1 text-[10px] text-amber-700"
                      title={cand.explanation.human_readable}
                    >
                      ↳ через прайс
                    </span>
                  )}
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

/**
 * P3.6: ручная привязка прайс-позиции к карточке каталога компании.
 * Поиск ведём по каталогу (фильтруем company_catalog), на выбор —
 * PATCH /items/{id}/catalog-link; «↺ авто» сбрасывает на авто-связку.
 */
function CatalogLinkEditor({
  itemId,
  hasLink,
}: {
  itemId: string;
  hasLink: boolean;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const invalidate = () => qc.invalidateQueries({ queryKey: ["specifications"] });
  const search = useMutation({ mutationFn: (q: string) => api.searchCatalog(q, 20) });
  const link = useMutation({
    mutationFn: (catalogItemId: string) => api.setCatalogLink(itemId, catalogItemId),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      setQuery("");
    },
  });
  const auto = useMutation({
    mutationFn: () => api.resetCatalogLinkAuto(itemId),
    onSuccess: invalidate,
  });

  const results = (search.data ?? []).filter(
    (r: CatalogSearchResult) => r.source_type === "company_catalog",
  );
  const busy = link.isPending || auto.isPending;

  if (!open) {
    return (
      <div className="mt-1 flex gap-2">
        <button
          type="button"
          className="text-[10px] text-blue-600 hover:underline"
          onClick={() => setOpen(true)}
        >
          ✎ {hasLink ? "изменить карточку" : "привязать карточку"}
        </button>
        {hasLink && (
          <button
            type="button"
            className="text-[10px] text-slate-400 hover:underline disabled:opacity-50"
            onClick={() => auto.mutate()}
            disabled={busy}
            title="Сбросить на авто-связку"
          >
            ↺ авто
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="mt-1 rounded border border-blue-200 bg-blue-50/40 p-1.5">
      <form
        className="flex gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) search.mutate(query.trim());
        }}
      >
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="поиск по каталогу…"
          className="w-44 rounded border border-slate-300 px-1.5 py-0.5 text-xs"
        />
        <button type="submit" className="text-[10px] text-blue-600 hover:underline">
          найти
        </button>
        <button
          type="button"
          className="ml-auto text-[10px] text-slate-400 hover:underline"
          onClick={() => setOpen(false)}
        >
          закрыть
        </button>
      </form>
      {results.length > 0 && (
        <ul className="mt-1 max-h-40 divide-y divide-slate-200 overflow-y-auto">
          {results.map((r) => (
            <li
              key={r.item_id}
              className="flex items-center gap-2 py-0.5 text-[11px] hover:bg-white"
            >
              <span className="font-mono text-slate-500">
                {r.code_1c ?? r.article ?? "—"}
              </span>
              <span className="flex-1 truncate" title={r.name}>
                {r.name}
              </span>
              <button
                type="button"
                className="text-blue-600 hover:underline disabled:opacity-50"
                onClick={() => link.mutate(r.item_id)}
                disabled={busy}
              >
                выбрать
              </button>
            </li>
          ))}
        </ul>
      )}
      {search.isSuccess && results.length === 0 && (
        <div className="mt-1 text-[10px] text-slate-400">
          в каталоге ничего не найдено
        </div>
      )}
    </div>
  );
}
