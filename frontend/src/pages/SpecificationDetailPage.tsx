import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type {
  SpecificationCounts,
  SpecificationRead,
  SpecificationStatus,
  VerificationDecision,
} from "../types/api";
import { Badge } from "../components/ui/Badge";
import { ProgressBar } from "../components/ProgressBar";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { SpecItemRow } from "../components/SpecItemRow";
import { SpecMetrics, type SegmentKey } from "../components/SpecMetrics";
import { useColumnWidths } from "../hooks/useColumnWidths";

// Колонки таблицы строк спеки. id — СТАБИЛЬНЫЙ ключ ширины (не индекс).
const SPEC_COLUMNS: { id: string; label: string; default: number }[] = [
  { id: "check", label: "", default: 40 },
  { id: "num", label: "№", default: 88 },
  { id: "source", label: "Исходная позиция", default: 360 },
  { id: "qty", label: "Кол-во", default: 92 },
  { id: "chosen", label: "Выбранная позиция", default: 360 },
  { id: "confidence", label: "Уверенность", default: 112 },
  { id: "decision", label: "Решение", default: 128 },
  { id: "actions", label: "", default: 108 },
];

function widthOf(widths: Record<string, number>, id: string): number {
  return widths[id] ?? SPEC_COLUMNS.find((c) => c.id === id)?.default ?? 120;
}

// Сегментный фильтр (ось состояния) и сортировка — значения совпадают с
// серверными (ItemStatusFilter / ItemSort на бэке). Бакеты качества
// high/mid/low/no_candidate — ось качества (по топ-1 кандидату); модель
// «один активный фильтр» (оси не комбинируются).
type StatusFilter =
  | "all"
  | "pending"
  | "confirmed"
  | "rejected"
  | "forwarded"
  | "high"
  | "mid"
  | "low"
  | "no_candidate";
type SortBy = "line_number" | "confidence_desc" | "confidence_asc";
import {
  formatDateTime,
  isInProgress,
  statusLabel,
  statusTone,
} from "../lib/format";

export function SpecificationDetailPage() {
  const { specId } = useParams<{ specId: string }>();
  if (!specId) return null;
  return <DetailContent specId={specId} />;
}

function DetailContent({ specId }: { specId: string }) {
  const queryClient = useQueryClient();
  const [autoConfirmThreshold, setAutoConfirmThreshold] = useState("0.9");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  // Сегментный фильтр и сортировка строк (серверные — пагинация серверная).
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortBy, setSortBy] = useState<SortBy>("line_number");
  // Массовый выбор строк (id'шники spec_item). Сбрасывается при смене
  // страницы/фильтра — чтобы не применять решение к невидимым строкам.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // Дебаунс порога для счётчика «Авто-подтвердить (N)» (dry-run на бэке).
  const [debouncedThreshold, setDebouncedThreshold] = useState("0.9");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedThreshold(autoConfirmThreshold), 300);
    return () => clearTimeout(t);
  }, [autoConfirmThreshold]);

  // Переход «К закладке»: id подсвеченной строки. Гаснет сам через 3 c.
  const [highlightId, setHighlightId] = useState<string | null>(null);
  useEffect(() => {
    if (!highlightId) return;
    const t = setTimeout(() => setHighlightId(null), 3000);
    return () => clearTimeout(t);
  }, [highlightId]);

  const clearSelection = useCallback(() => setSelected(new Set()), []);
  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Измеряем высоту липкой шапки спецификации чтобы шапка таблицы и
  // развёрнутая строка товара приклеивались ровно ниже неё (без перекрытия).
  // Через callback-ref — замер происходит в момент РЕАЛЬНОГО монтирования
  // шапки. Иначе при первом заходе в спеку (данные ещё грузятся, шапки нет
  // в DOM) высота оставалась 0, и sticky-строка пряталась за спец-шапкой —
  // «фиксация работала в одной спеке и не работала в другой».
  const [stickyHeaderHeight, setStickyHeaderHeight] = useState(0);
  const roRef = useRef<ResizeObserver | null>(null);
  const setStickyHeaderEl = useCallback((node: HTMLDivElement | null) => {
    roRef.current?.disconnect();
    roRef.current = null;
    if (!node) return;
    const measure = () =>
      setStickyHeaderHeight(node.getBoundingClientRect().height);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    roRef.current = ro;
  }, []);

  // Ширины колонок таблицы строк (drag-resize, сохраняются глобально).
  const { widths, setWidth, resetWidth, resetAll } = useColumnWidths();
  const colW = useCallback(
    (id: string) => widthOf(widths, id),
    [widths],
  );

  // Доступная ширина контейнера таблицы — чтобы сумма колонок её не превышала
  // (иначе правые колонки «уезжают» за границы блока).
  const [availWidth, setAvailWidth] = useState(0);
  const tableRoRef = useRef<ResizeObserver | null>(null);
  const setTableWrapEl = useCallback((node: HTMLDivElement | null) => {
    tableRoRef.current?.disconnect();
    tableRoRef.current = null;
    if (!node) return;
    const measure = () => setAvailWidth(node.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    tableRoRef.current = ro;
  }, []);

  // Свежие значения для обработчика drag без пересоздания listener'ов.
  const dragStateRef = useRef({ widths, availWidth });
  dragStateRef.current = { widths, availWidth };

  const dragRef = useRef<{ id: string; startX: number; startW: number } | null>(null);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const proposed = d.startW + (e.clientX - d.startX);
      const { widths: w, availWidth: avail } = dragStateRef.current;
      const others = SPEC_COLUMNS.reduce(
        (s, c) => s + (c.id === d.id ? 0 : widthOf(w, c.id)),
        0,
      );
      // Клампим так, чтобы суммарная ширина не превысила контейнер.
      const max = avail > 0 ? Math.max(60, avail - others) : proposed;
      setWidth(d.id, Math.min(proposed, max));
    };
    const onUp = () => {
      dragRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [setWidth]);
  const startResize = (id: string) => (e: ReactMouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = { id, startX: e.clientX, startW: colW(id) };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  // Если сохранённые ширины суммарно шире контейнера (например, из старого
  // localStorage) — масштабируем к ширине блока, чтобы колонки не уезжали.
  const rawTotalW = SPEC_COLUMNS.reduce((s, c) => s + colW(c.id), 0);
  const fitScale =
    availWidth > 0 && rawTotalW > availWidth ? availWidth / rawTotalW : 1;
  const dispW = (id: string) => Math.floor(colW(id) * fitScale);
  const tableWidth = availWidth > 0 ? Math.min(rawTotalW, availWidth) : rawTotalW;

  const specQuery = useQuery({
    queryKey: ["specifications", specId],
    queryFn: () => api.getSpecification(specId),
    refetchInterval: (query) => {
      const spec = query.state.data;
      return spec && isInProgress(spec.status) ? 2000 : false;
    },
  });

  const resultsReady =
    specQuery.data?.status === "matched" ||
    specQuery.data?.status === "verified" ||
    specQuery.data?.status === "exported" ||
    specQuery.data?.status === "reviewing";

  const itemsQuery = useQuery({
    queryKey: ["specifications", specId, "items", page, pageSize, statusFilter, sortBy],
    queryFn: () =>
      api.getSpecificationItems(specId, page, pageSize, {
        status: statusFilter,
        sort: sortBy,
      }),
    enabled: resultsReady,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || !data.items) return false;
      return false;
    },
  });

  // Счётчик «Авто-подтвердить (N)» — dry-run, ключ начинается с
  // ["specifications", specId, …], поэтому инвалидируется вместе с остальным
  // при любом решении (verify/bulk/auto-confirm).
  const thresholdNum = Number(debouncedThreshold);
  const autoConfirmPreview = useQuery({
    queryKey: ["specifications", specId, "auto-confirm-preview", debouncedThreshold],
    queryFn: () =>
      api.autoConfirm(specId, { min_confidence: thresholdNum, dry_run: true }),
    enabled: resultsReady && debouncedThreshold !== "" && !Number.isNaN(thresholdNum),
  });
  const autoConfirmN = autoConfirmPreview.data?.confirmed_count ?? null;

  const bulkMutation = useMutation({
    mutationFn: (decision: VerificationDecision) =>
      api.bulkVerifyItems(specId, [...selected], decision),
    onSuccess: (res) => {
      clearSelection();
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({
        queryKey: ["specifications", specId, "items"],
      });
      if (res.skipped_no_candidate > 0) {
        window.alert(
          `Применено: ${res.applied}. Пропущено без кандидата: ${res.skipped_no_candidate}`,
        );
      }
    },
    onError: (e) =>
      window.alert(
        e instanceof ApiError
          ? `Ошибка массового решения (${e.status})`
          : "Не удалось применить массовое решение",
      ),
  });

  const verifyMutation = useMutation({
    mutationFn: ({
      specItemId,
      decision,
      chosenItemId,
    }: {
      specItemId: string;
      decision: VerificationDecision;
      chosenItemId?: string | null;
    }) =>
      api.verifySpecItem(specId, specItemId, {
        decision,
        chosen_item_id: chosenItemId ?? null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({
        queryKey: ["specifications", specId, "items"],
      });
    },
  });

  // Закладка строки (одна на спеку): toggle через PATCH спеки.
  const bookmarkMutation = useMutation({
    mutationFn: (bookmarkedItemId: string | null) =>
      api.updateSpecification(specId, { bookmarked_item_id: bookmarkedItemId }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] }),
    onError: (e) =>
      window.alert(
        e instanceof ApiError
          ? `Ошибка закладки (${e.status})`
          : "Не удалось изменить закладку",
      ),
  });

  const unverifyMutation = useMutation({
    mutationFn: (specItemId: string) => api.unverifySpecItem(specId, specItemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({
        queryKey: ["specifications", specId, "items"],
      });
    },
  });

  const rematchMutation = useMutation({
    mutationFn: () => api.rematchSpecification(specId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({
        queryKey: ["specifications", specId, "items"],
      });
    },
    onError: (e) =>
      window.alert(
        e instanceof ApiError
          ? `Не удалось запустить матчинг (ошибка ${e.status})`
          : "Не удалось запустить повторный матчинг",
      ),
  });

  const autoConfirmMutation = useMutation({
    mutationFn: () =>
      api.autoConfirm(specId, {
        min_confidence: Number(autoConfirmThreshold),
        decided_by: "ui",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({
        queryKey: ["specifications", specId, "items"],
      });
    },
  });

  if (specQuery.isLoading) {
    return <div className="p-8 text-center text-slate-500">Загрузка…</div>;
  }
  if (specQuery.error instanceof Error) {
    return (
      <Card>
        <CardBody>
          <div className="text-red-600">
            Ошибка: {specQuery.error.message}
          </div>
          <Link to="/specifications">
            <Button variant="ghost" className="mt-3">
              ← К списку
            </Button>
          </Link>
        </CardBody>
      </Card>
    );
  }

  const spec = specQuery.data;
  if (!spec) return null;

  const isReady = !isInProgress(spec.status);
  const items = itemsQuery.data?.items ?? [];

  // Select-all действует только на видимые (текущая страница).
  const visibleIds = items.map((i) => i.id);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));
  const someVisibleSelected = visibleIds.some((id) => selected.has(id));
  const toggleSelectAllVisible = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
      else visibleIds.forEach((id) => next.add(id));
      return next;
    });
  };

  // Закладка: клик по флажку строки ставит её закладкой, повторный — снимает.
  const toggleBookmark = (id: string) =>
    bookmarkMutation.mutate(spec.bookmarked_item_id === id ? null : id);

  // Качество сопоставления как фильтр таблицы (чипы сводки). «none» бэка —
  // это no_candidate. Повторный клик по активному бакету снимает фильтр.
  const activeQuality: SegmentKey | null =
    statusFilter === "no_candidate"
      ? "none"
      : statusFilter === "high" || statusFilter === "mid" || statusFilter === "low"
        ? statusFilter
        : null;
  const selectQuality = (key: SegmentKey) => {
    const target: StatusFilter = key === "none" ? "no_candidate" : key;
    setStatusFilter((prev) => (prev === target ? "all" : target));
    setPage(1);
    clearSelection();
  };

  // Переход «К закладке»: сбрасываем фильтр/сортировку (чтобы строка точно
  // была видна и совпала с расчётом страницы по line_number), прыгаем на её
  // страницу и подсвечиваем.
  const jumpToBookmark = () => {
    const bid = spec.bookmarked_item_id;
    const pos = spec.bookmarked_position;
    if (!bid || !pos) return;
    setStatusFilter("all");
    setSortBy("line_number");
    clearSelection();
    setPage(Math.ceil(pos / pageSize));
    setHighlightId(bid);
  };

  return (
    <div className="space-y-6">
      <div ref={setStickyHeaderEl} className="sticky top-14 z-20 bg-slate-50 pb-2">
      <Card>
        <CardBody className="flex flex-wrap items-center gap-x-6 gap-y-3">
          {/* Компактная строка: навигация + малозначимые имя файла/дата + меню.
              Раньше это был высокий CardHeader — он съедал место под список. */}
          <div className="flex basis-full items-center gap-2 text-sm">
            <span
              className="truncate font-medium text-slate-700"
              title={spec.source_filename}
            >
              {spec.source_filename}
            </span>
            <span className="shrink-0 text-xs text-slate-400">
              Загружен {formatDateTime(spec.created_at)}
            </span>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <Link
                to="/specifications"
                className="text-slate-500 hover:text-slate-900"
              >
                ← К списку
              </Link>
              <SpecOverflowMenu specId={specId} status={spec.status} />
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-slate-500">Статус</div>
            <div className="mt-1">
              <Badge tone={statusTone(spec.status)}>
                {statusLabel(spec.status)}
              </Badge>
            </div>
          </div>

          <div>
            <div className="text-xs uppercase text-slate-500">Клиент</div>
            <div className="mt-1">
              <ClientPicker specId={specId} clientId={spec.client_id} />
            </div>
          </div>

          <TradingPlatformControl specId={specId} spec={spec} />

          {spec.error_message && (
            <div className="flex-1 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {spec.error_message}
            </div>
          )}

          <SpecMetrics
            counts={spec.counts}
            active={activeQuality}
            onSelect={selectQuality}
          />

          {isInProgress(spec.status) && (
            <div className="flex basis-full items-center gap-4">
              <div className="flex-1">
                <ProgressBar spec={spec} />
              </div>
              <AbortButton specId={specId} />
            </div>
          )}
        </CardBody>
      </Card>
      </div>

      <RequisitesEditor specId={specId} spec={spec} />

      {isReady && (
        <Card>
          <CardHeader
            title="Результаты"
            description={`${items.length} строк${
              spec.counts.items_total > items.length
                ? ` (показаны первые ${items.length})`
                : ""
            }`}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                {spec.bookmarked_item_id && (
                  <Button
                    variant="outline"
                    onClick={jumpToBookmark}
                    title="Перейти к строке, отмеченной закладкой"
                    className="text-amber-700 hover:bg-amber-50"
                  >
                    ⚑ К закладке
                  </Button>
                )}
                <div className="flex items-center gap-2 rounded-md border border-slate-300 bg-white px-2">
                  <label
                    htmlFor="threshold"
                    className="text-xs text-slate-500"
                  >
                    Порог
                  </label>
                  <input
                    id="threshold"
                    type="number"
                    step="0.05"
                    min="0"
                    max="1"
                    value={autoConfirmThreshold}
                    onChange={(e) => setAutoConfirmThreshold(e.target.value)}
                    className="w-16 border-none bg-transparent py-1 text-sm focus:outline-none focus:ring-0"
                  />
                </div>
                <Button
                  variant="outline"
                  onClick={() => {
                    if (
                      window.confirm(
                        "Повторно подобрать кандидатов для всех строк, кроме " +
                          "подтверждённых?\n\nПодтверждённые строки останутся " +
                          "без изменений. У остальных кандидаты пересоберутся " +
                          "заново, а прежнее решение «Отклонено» / «Не найдено» " +
                          "/ «Новая позиция» будет сброшено.",
                      )
                    ) {
                      rematchMutation.mutate();
                    }
                  }}
                  disabled={rematchMutation.isPending}
                  title="Перезапустить матчинг для строк, которые ещё не подтверждены"
                >
                  {rematchMutation.isPending
                    ? "Запуск…"
                    : "↻ Повторный матчинг"}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => autoConfirmMutation.mutate()}
                  disabled={autoConfirmMutation.isPending || autoConfirmN === 0}
                  title={
                    autoConfirmN === 0
                      ? "Нет строк с уверенностью ≥ порога"
                      : "Подтвердить топ-кандидата для строк с уверенностью ≥ порога"
                  }
                >
                  {autoConfirmMutation.isPending
                    ? "Подтверждение…"
                    : `Авто-подтвердить${autoConfirmN != null ? ` (${autoConfirmN})` : ""}`}
                </Button>
                <a
                  href={api.exportUrl(specId, "xlsx")}
                  download
                  className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-800"
                >
                  Экспорт XLSX
                </a>
                <a
                  href={api.exportUrl(specId, "csv")}
                  download
                  className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium text-slate-900 transition-colors hover:bg-slate-50"
                >
                  CSV
                </a>
              </div>
            }
          />

          {autoConfirmMutation.data && (
            <div className="border-b border-slate-200 bg-green-50 px-6 py-2 text-sm text-green-900">
              Подтверждено: <strong>{autoConfirmMutation.data.confirmed_count}</strong>,
              пропущено уже верифицированных:{" "}
              <strong>{autoConfirmMutation.data.skipped_already_verified}</strong>,
              ниже порога: <strong>{autoConfirmMutation.data.skipped_below_threshold}</strong>
            </div>
          )}
          {verifyMutation.isError && (
            <div className="border-b border-slate-200 bg-red-50 px-6 py-2 text-sm text-red-800">
              Ошибка верификации:{" "}
              {verifyMutation.error instanceof ApiError
                ? `${verifyMutation.error.status}`
                : (verifyMutation.error as Error)?.message}
            </div>
          )}

          <SpecItemsToolbar
            counts={spec.counts}
            status={statusFilter}
            sort={sortBy}
            onStatus={(s) => {
              setStatusFilter(s);
              setPage(1);
              clearSelection();
            }}
            onSort={(s) => {
              setSortBy(s);
              setPage(1);
              clearSelection();
            }}
          />

          {itemsQuery.isLoading ? (
            <div className="px-6 py-8 text-center text-slate-500">
              Загрузка строк…
            </div>
          ) : (
            <div ref={setTableWrapEl}>
              <div className="flex justify-end px-4 py-1">
                <button
                  type="button"
                  onClick={resetAll}
                  className="text-xs text-slate-400 hover:text-slate-600 hover:underline"
                  title="Сбросить ширины всех колонок к значениям по умолчанию"
                >
                  ↔ сбросить ширины
                </button>
              </div>
              <table
                className="text-sm"
                style={{ tableLayout: "fixed", width: tableWidth }}
              >
                <colgroup>
                  {SPEC_COLUMNS.map((c) => (
                    <col key={c.id} style={{ width: dispW(c.id) }} />
                  ))}
                </colgroup>
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  {/* sticky на <th>, а не на <thead> — для кросс-браузерной
                      совместимости (Safari/старый Firefox требуют именно так).
                      top = высота шапки спеки + 56px (header h-14). */}
                  <tr>
                    {SPEC_COLUMNS.map((col) =>
                      col.id === "check" ? (
                        <th
                          key={col.id}
                          className="sticky z-10 bg-slate-50 px-4 py-3 text-center shadow-sm"
                          style={{ top: stickyHeaderHeight + 56 }}
                        >
                          <input
                            type="checkbox"
                            aria-label="Выбрать все видимые строки"
                            checked={allVisibleSelected}
                            ref={(el) => {
                              if (el)
                                el.indeterminate =
                                  someVisibleSelected && !allVisibleSelected;
                            }}
                            onChange={toggleSelectAllVisible}
                            className="cursor-pointer"
                          />
                        </th>
                      ) : (
                        <th
                          key={col.id}
                          className="sticky z-10 bg-slate-50 px-4 py-3 font-medium shadow-sm relative select-none overflow-hidden text-ellipsis"
                          style={{ top: stickyHeaderHeight + 56 }}
                        >
                          {col.label}
                          {/* Ручка ресайза на правом крае: тянуть — менять
                              ширину, двойной клик — сбросить эту колонку. */}
                          <span
                            onMouseDown={startResize(col.id)}
                            onDoubleClick={() => resetWidth(col.id)}
                            className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize hover:bg-blue-300"
                            title="Тянуть — ширина; двойной клик — сбросить"
                          />
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <SpecItemRow
                      key={item.id}
                      item={item}
                      pending={verifyMutation.isPending || unverifyMutation.isPending}
                      selected={selected.has(item.id)}
                      onToggleSelect={toggleSelect}
                      bookmarked={spec.bookmarked_item_id === item.id}
                      onToggleBookmark={toggleBookmark}
                      highlight={highlightId === item.id}
                      // Строка «прилипает» под шапкой таблицы (nav 56 + шапка
                      // спеки + высота thead ~41) при разворачивании.
                      stickyTop={stickyHeaderHeight + 56 + 41}
                      onVerify={(specItemId, decision, chosenItemId) =>
                        verifyMutation.mutate({
                          specItemId,
                          decision,
                          chosenItemId,
                        })
                      }
                      onUnverify={(specItemId) =>
                        unverifyMutation.mutate(specItemId)
                      }
                    />
                  ))}
                </tbody>
              </table>
              <Pagination
                page={page}
                pageSize={pageSize}
                total={itemsQuery.data?.total ?? 0}
                onPageChange={(p) => {
                  setPage(p);
                  clearSelection();
                }}
                onPageSizeChange={(s) => {
                  setPageSize(s);
                  setPage(1);
                  clearSelection();
                }}
              />
            </div>
          )}
        </Card>
      )}

      {/* Плавающая панель массовых действий: закреплена у нижнего края экрана,
          видна только при выделении — действия (Подтвердить/Отклонить/Передать)
          доступны при любом скролле и НЕ отнимают постоянной высоты у списка. */}
      {selected.size > 0 && (
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex justify-center px-4">
          <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-full border border-blue-200 bg-white px-4 py-2 text-sm shadow-lg">
            <span className="font-medium text-blue-800">
              {selected.size} выбрано
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => bulkMutation.mutate("confirmed")}
              disabled={bulkMutation.isPending}
            >
              ✓ Подтвердить
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => bulkMutation.mutate("rejected")}
              disabled={bulkMutation.isPending}
            >
              ✕ Отклонить
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => bulkMutation.mutate("forwarded")}
              disabled={bulkMutation.isPending}
              title="Передать выбранные строки в группу МОС"
            >
              ↗ Передать
            </Button>
            <button
              type="button"
              onClick={clearSelection}
              className="ml-1 text-slate-500 hover:underline"
            >
              Снять выбор
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const STATUS_SEGMENTS: {
  key: StatusFilter;
  label: string;
  count: (c: SpecificationCounts) => number;
}[] = [
  { key: "all", label: "Все", count: (c) => c.items_total },
  { key: "pending", label: "Не проверено", count: (c) => c.items_pending },
  { key: "confirmed", label: "Подтверждено", count: (c) => c.items_confirmed },
  { key: "rejected", label: "Отклонено", count: (c) => c.items_rejected },
  { key: "forwarded", label: "Передано", count: (c) => c.items_forwarded },
  { key: "no_candidate", label: "Нет кандидата", count: (c) => c.items_no_candidate },
];

function SpecItemsToolbar({
  counts,
  status,
  sort,
  onStatus,
  onSort,
}: {
  counts: SpecificationCounts;
  status: StatusFilter;
  sort: SortBy;
  onStatus: (s: StatusFilter) => void;
  onSort: (s: SortBy) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-slate-50/60 px-4 py-2">
      <div className="inline-flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
        {STATUS_SEGMENTS.map((seg) => {
          const on = seg.key === status;
          return (
            <button
              key={seg.key}
              type="button"
              onClick={() => onStatus(seg.key)}
              className={
                "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium transition-colors " +
                (on
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-900")
              }
            >
              {seg.label}
              <span
                className={
                  "tabular-nums text-xs " +
                  (on ? "text-slate-500" : "text-slate-400")
                }
              >
                {seg.count(counts)}
              </span>
            </button>
          );
        })}
      </div>
      <div className="ml-auto inline-flex items-center gap-2">
        <span className="text-xs text-slate-500">Сортировка</span>
        <select
          value={sort}
          onChange={(e) => onSort(e.target.value as SortBy)}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
        >
          <option value="line_number">по №</option>
          <option value="confidence_desc">уверенность ↓</option>
          <option value="confidence_asc">уверенность ↑</option>
        </select>
      </div>
    </div>
  );
}

function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (p: number) => void;
  onPageSizeChange: (s: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-2 text-sm">
      <div className="text-slate-600">
        {total === 0 ? "Нет строк" : <>Строки <strong>{from}–{to}</strong> из <strong>{total}</strong></>}
      </div>
      <div className="flex items-center gap-2">
        <label className="text-xs text-slate-500">На странице:</label>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
        >
          <option value={50}>50</option>
          <option value={100}>100</option>
          <option value={200}>200</option>
        </select>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
        >
          ←
        </Button>
        <span className="tabular-nums text-slate-600">
          {page} / {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
        >
          →
        </Button>
      </div>
    </div>
  );
}

function ClientPicker({
  specId,
  clientId,
}: {
  specId: string;
  clientId: string | null;
}) {
  const qc = useQueryClient();
  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => api.listClients(),
  });

  const assign = useMutation({
    mutationFn: (cid: string | null) =>
      api.updateSpecification(specId, { client_id: cid }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["specifications", specId] }),
  });
  const createAndAssign = useMutation({
    mutationFn: (name: string) => api.createClient({ name }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      assign.mutate(c.id);
    },
  });

  const onChange = (value: string) => {
    if (value === "__new__") {
      const name = window.prompt("Название нового клиента:")?.trim();
      if (name) createAndAssign.mutate(name);
      return;
    }
    assign.mutate(value || null);
  };

  const busy = assign.isPending || createAndAssign.isPending;

  return (
    <select
      value={clientId ?? ""}
      disabled={busy}
      onChange={(e) => onChange(e.target.value)}
      className="rounded border border-slate-300 px-2 py-1 text-sm disabled:opacity-50"
    >
      <option value="">— не выбран —</option>
      {(clients ?? []).map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
      <option value="__new__">+ Создать нового…</option>
    </select>
  );
}

function TradingPlatformControl({
  specId,
  spec,
}: {
  specId: string;
  spec: SpecificationRead;
}) {
  const qc = useQueryClient();
  const { data: platforms } = useQuery({
    queryKey: ["trading-platforms"],
    queryFn: () => api.listPlatforms(),
  });
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["specifications", specId] });

  const setFlag = useMutation({
    mutationFn: (checked: boolean) =>
      api.updateSpecification(specId, { is_tp: checked }),
    onSuccess: invalidate,
  });
  const assign = useMutation({
    mutationFn: (pid: string | null) =>
      api.updateSpecification(specId, { trading_platform_id: pid }),
    onSuccess: invalidate,
  });
  const createAndAssign = useMutation({
    mutationFn: (name: string) => api.createPlatform({ name }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["trading-platforms"] });
      assign.mutate(p.id);
    },
  });

  const onSelect = (v: string) => {
    if (v === "__new__") {
      const name = window.prompt("Название новой площадки:")?.trim();
      if (name) createAndAssign.mutate(name);
      return;
    }
    assign.mutate(v || null);
  };

  const busy =
    setFlag.isPending || assign.isPending || createAndAssign.isPending;

  return (
    <div>
      <label className="flex items-center gap-2 text-xs uppercase text-slate-500">
        <input
          type="checkbox"
          checked={spec.is_tp}
          disabled={busy}
          onChange={(e) => setFlag.mutate(e.target.checked)}
        />
        Спецификация ТП
      </label>
      {spec.is_tp && (
        <div className="mt-1">
          <select
            value={spec.trading_platform_id ?? ""}
            disabled={busy}
            onChange={(e) => onSelect(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm disabled:opacity-50"
          >
            <option value="">— площадка не выбрана —</option>
            {(platforms ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
            <option value="__new__">+ Создать новую…</option>
          </select>
        </div>
      )}
    </div>
  );
}

function RequisitesEditor({
  specId,
  spec,
}: {
  specId: string;
  spec: SpecificationRead;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    spec_number: spec.spec_number ?? "",
    spec_date: spec.spec_date ?? "",
    delivery_date: spec.delivery_date ?? "",
  });

  const save = useMutation({
    mutationFn: () =>
      api.updateSpecification(specId, {
        spec_number: form.spec_number.trim() || null,
        spec_date: form.spec_date || null,
        delivery_date: form.delivery_date || null,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["specifications", specId] }),
  });

  const set = (k: keyof typeof form) => (v: string) =>
    setForm((f) => ({ ...f, [k]: v }));

  return (
    <Card>
      <CardHeader
        title="Реквизиты"
        description="Номер и даты тендера"
      />
      <CardBody className="flex flex-wrap items-end gap-4">
        <Req label="Номер" value={form.spec_number} onChange={set("spec_number")} />
        <Req
          label="Дата"
          type="date"
          value={form.spec_date}
          onChange={set("spec_date")}
        />
        <Req
          label="Дата поставки"
          type="date"
          value={form.delivery_date}
          onChange={set("delivery_date")}
        />
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? "Сохранение…" : "Сохранить"}
        </Button>
        {save.isSuccess && (
          <span className="text-sm text-green-700">✓ Сохранено</span>
        )}
      </CardBody>
    </Card>
  );
}

function Req({
  label,
  value,
  onChange,
  type = "text",
  wide,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: "text" | "date";
  wide?: boolean;
}) {
  return (
    <label className={"flex flex-col gap-1 " + (wide ? "min-w-64 flex-1" : "")}>
      <span className="text-xs uppercase text-slate-500">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      />
    </label>
  );
}

function AbortButton({ specId }: { specId: string }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.abortSpecification(specId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({ queryKey: ["specifications"] });
    },
    onError: (e) =>
      window.alert(
        e instanceof ApiError ? `Ошибка ${e.status}` : "Не удалось прервать",
      ),
  });
  return (
    <Button
      variant="outline"
      size="sm"
      className="shrink-0 text-red-600 hover:bg-red-50"
      onClick={() => {
        if (window.confirm("Прервать обработку этой спецификации?")) {
          mutation.mutate();
        }
      }}
      disabled={mutation.isPending}
      title="Остановить парсинг/матчинг"
    >
      {mutation.isPending ? "Прерываю…" : "⊗ Прервать"}
    </Button>
  );
}

function SpecOverflowMenu({
  specId,
  status,
}: {
  specId: string;
  status: SpecificationStatus;
}) {
  const queryClient = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [reason, setReason] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const mutation = useMutation({
    mutationFn: () => api.cancelSpecification(specId, reason.trim() || undefined),
    onSuccess: () => {
      setFormOpen(false);
      setReason("");
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({ queryKey: ["specifications"] });
    },
  });

  // Закрытие выпадающего меню по клику вне (форму отказа закрывает только
  // явное «Передумал» — чтобы случайный клик не сбрасывал введённую причину).
  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  // Единственный пункт меню — деструктивный отказ; для уже отменённых /
  // выгруженных он недоступен, поэтому и «⋯» прятать целиком.
  if (status === "cancelled" || status === "exported") return null;

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        size="sm"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((v) => !v)}
        title="Ещё"
      >
        ⋯
      </Button>

      {menuOpen && (
        <div
          role="menu"
          className="absolute right-0 top-full z-30 mt-1 w-64 rounded-md border border-slate-200 bg-white p-1 shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              setFormOpen(true);
            }}
            className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
          >
            Отказаться от спецификации
          </button>
        </div>
      )}

      {formOpen && (
        <div className="absolute right-0 top-full z-30 mt-1 flex w-80 flex-col gap-2 rounded-md border border-red-200 bg-red-50 p-3 shadow-lg">
          <div className="text-sm font-medium text-red-900">
            Отказаться от поставки?
          </div>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Причина (опционально)"
            rows={2}
            maxLength={1024}
            className="block w-full rounded border border-red-300 bg-white px-2 py-1 text-sm"
          />
          <div className="flex items-center gap-2">
            <Button
              variant="danger"
              size="sm"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Отказ…" : "Подтвердить отказ"}
            </Button>
            <button
              type="button"
              onClick={() => {
                setFormOpen(false);
                setReason("");
              }}
              className="text-xs text-slate-500 hover:underline"
            >
              Передумал
            </button>
          </div>
          {mutation.isError && (
            <div className="text-xs text-red-700">
              {mutation.error instanceof ApiError
                ? `Ошибка ${mutation.error.status}`
                : "Не удалось отменить"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
