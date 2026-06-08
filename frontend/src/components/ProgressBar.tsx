import type { SpecificationRead } from "../types/api";

/**
 * Полоса прогресса обработки спецификации.
 *
 * - parsing/uploaded/parsed → индетерминантная (пульсирующая) полоса: фаза
 *   короткая, точного % нет.
 * - matching → определённая полоса matched_count / items_total + «N/T · P%».
 * - остальные статусы (готов/ошибка/отменён) → ничего не рисуем.
 */
export function ProgressBar({ spec }: { spec: SpecificationRead }) {
  const { status } = spec;

  if (status === "matching") {
    const total = spec.counts.items_total;
    const done = spec.matched_count;
    if (total > 0) {
      const pct = Math.min(100, Math.round((done / total) * 100));
      return (
        <div className="w-full">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-blue-500 transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="mt-1 text-xs tabular-nums text-slate-500">
            Матчинг {done}/{total} · {pct}%
          </div>
        </div>
      );
    }
  }

  if (status === "matching" || status === "parsing" || status === "uploaded" || status === "parsed") {
    const label = status === "matching" ? "Матчинг…" : "Парсинг…";
    return (
      <div className="w-full">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-blue-400" />
        </div>
        <div className="mt-1 text-xs text-slate-500">{label}</div>
      </div>
    );
  }

  return null;
}
