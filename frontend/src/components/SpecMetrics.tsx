import type { SpecificationCounts } from "../types/api";

const QUALITY_SEGMENTS = [
  { key: "high", label: "≥ 90%", sub: "высокая", color: "bg-conf-high" },
  { key: "mid", label: "50–90%", sub: "средняя", color: "bg-conf-medium" },
  { key: "low", label: "< 50%", sub: "слабый кандидат", color: "bg-conf-low" },
  { key: "none", label: "Нет кандидата", sub: "не сопоставлено", color: "bg-slate-400" },
] as const;

export type SegmentKey = (typeof QUALITY_SEGMENTS)[number]["key"];

interface Props {
  counts: SpecificationCounts;
  /** Активный бакет качества (управляется фильтром таблицы). */
  active?: SegmentKey | null;
  /** Клик по чипу/сегменту — фильтрует таблицу по бакету качества. */
  onSelect?: (key: SegmentKey) => void;
  /** Компактный режим: одна строка для липкой шапки при скролле. */
  compact?: boolean;
}

/**
 * Компактная сводка в одну строку (для свёрнутой липкой шапки): прогресс
 * верификации одной фразой + тонкая полоса + 4 мини-чипа качества. Чипы
 * по-прежнему фильтруют таблицу (та же `onSelect`/`active`, что в полном виде).
 */
function CompactMetrics({ counts, active = null, onSelect }: Props) {
  const total = counts.items_total;
  const verified = counts.items_verified;
  const pct = total > 0 ? Math.round((verified / total) * 100) : 0;
  const values: Record<SegmentKey, number> = {
    high: counts.items_matched_high,
    mid: counts.items_matched_medium,
    low: counts.items_low,
    none: counts.items_no_candidate,
  };

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2 whitespace-nowrap text-xs text-slate-600">
        <span>
          Пров.{" "}
          <b className="font-semibold tabular-nums text-slate-800">
            {verified}/{total}
          </b>{" "}
          <span className="tabular-nums text-slate-400">({pct}%)</span>
        </span>
        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full rounded-full bg-conf-high transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {QUALITY_SEGMENTS.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => onSelect?.(s.key)}
            title={
              active === s.key
                ? `Снять фильтр: ${s.label}`
                : `${s.sub} — ${s.label}: ${values[s.key]}`
            }
            className={
              "flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs transition-colors " +
              (active === s.key
                ? "border-slate-900 bg-slate-50"
                : "border-slate-200 hover:border-slate-300 hover:bg-slate-50")
            }
          >
            <span className={`h-2 w-2 flex-none rounded-sm ${s.color}`} />
            <span className="font-semibold tabular-nums">{values[s.key]}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Сводка-метрик страницы спецификации на ДВУХ осях (ревизия UI):
 *  — «Прогресс верификации» (workflow): сколько строк закрыто;
 *  — «Качество сопоставления» (derived): распределение топ-кандидатов по
 *    уверенности, включая «Нет кандидата».
 *
 * Легенда-чипы = фильтр таблицы: клик прокидывает бакет качества в серверный
 * фильтр строк (`onSelect`); `active` подсвечивает текущий выбор.
 */
export function SpecMetrics({ counts, active = null, onSelect, compact = false }: Props) {
  if (compact) {
    return <CompactMetrics counts={counts} active={active} onSelect={onSelect} />;
  }
  const total = counts.items_total;
  const verified = counts.items_verified;
  const pct = total > 0 ? Math.round((verified / total) * 100) : 0;
  const values: Record<SegmentKey, number> = {
    high: counts.items_matched_high,
    mid: counts.items_matched_medium,
    low: counts.items_low,
    none: counts.items_no_candidate,
  };

  return (
    <div className="basis-full">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(220px,260px)_1fr]">
        {/* Ось А — прогресс верификации */}
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Прогресс верификации
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold tabular-nums">{verified}</span>
            <span className="text-sm tabular-nums text-slate-400">/ {total}</span>
            <span className="ml-auto rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium tabular-nums text-green-800">
              {pct}%
            </span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-conf-high transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="mt-2 flex gap-4 text-xs text-slate-500">
            <span>
              Закрыто{" "}
              <b className="font-semibold tabular-nums text-slate-700">{verified}</b>
            </span>
            <span>
              Осталось{" "}
              <b className="font-semibold tabular-nums text-slate-700">
                {counts.items_pending}
              </b>
            </span>
          </div>
        </div>

        {/* Ось Б — качество сопоставления */}
        <div>
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Качество сопоставления
            </span>
            <span className="text-xs tabular-nums text-slate-500">
              {total} позиц.
            </span>
          </div>

          <div className="mb-3 flex h-3.5 gap-0.5 overflow-hidden rounded-md bg-slate-200">
            {QUALITY_SEGMENTS.map((s) => (
              <div
                key={s.key}
                className={`${s.color} min-w-0 transition-all ${
                  active && active !== s.key ? "opacity-30" : "opacity-100"
                }`}
                style={{ flexGrow: values[s.key], flexBasis: 0 }}
                title={`${s.label}: ${values[s.key]}`}
              />
            ))}
          </div>

          <div className="flex flex-wrap gap-2">
            {QUALITY_SEGMENTS.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => onSelect?.(s.key)}
                title={
                  active === s.key
                    ? "Снять фильтр по качеству"
                    : `Показать только: ${s.label}`
                }
                className={
                  "flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-colors " +
                  (active === s.key
                    ? "border-slate-900 bg-slate-50"
                    : "border-slate-200 hover:border-slate-300 hover:bg-slate-50")
                }
              >
                <span className={`h-2.5 w-2.5 flex-none rounded-sm ${s.color}`} />
                <span className="text-base font-semibold tabular-nums">
                  {values[s.key]}
                </span>
                <span className="text-xs leading-tight text-slate-500">
                  {s.label}
                  <span className="block text-[10px] text-slate-400">{s.sub}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
