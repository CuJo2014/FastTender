import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { SpecificationStatus, VerificationDecision } from "../types/api";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { SpecItemRow } from "../components/SpecItemRow";
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
  const [pageSize, setPageSize] = useState(50);

  // Измеряем высоту липкой шапки спецификации чтобы шапка таблицы
  // могла приклеиться ровно ниже неё (без перекрытия).
  // getBoundingClientRect().height включает padding/border — это и есть
  // визуальная высота которую thead должен «обойти».
  const stickyHeaderRef = useRef<HTMLDivElement>(null);
  const [stickyHeaderHeight, setStickyHeaderHeight] = useState(0);
  useEffect(() => {
    if (!stickyHeaderRef.current) return;
    const el = stickyHeaderRef.current;
    const measure = () => setStickyHeaderHeight(el.getBoundingClientRect().height);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const specQuery = useQuery({
    queryKey: ["specifications", specId],
    queryFn: () => api.getSpecification(specId),
    refetchInterval: (query) => {
      const spec = query.state.data;
      return spec && isInProgress(spec.status) ? 2000 : false;
    },
  });

  const itemsQuery = useQuery({
    queryKey: ["specifications", specId, "items", page, pageSize],
    queryFn: () => api.getSpecificationItems(specId, page, pageSize),
    enabled: specQuery.data?.status === "matched"
      || specQuery.data?.status === "verified"
      || specQuery.data?.status === "exported"
      || specQuery.data?.status === "reviewing",
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || !data.items) return false;
      return false;
    },
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

  return (
    <div className="space-y-6">
      <div ref={stickyHeaderRef} className="sticky top-0 z-20 bg-slate-50 pb-2">
      <Card>
        <CardHeader
          title={spec.source_filename}
          description={
            <>
              {spec.client_name && (
                <span className="mr-3">Клиент: {spec.client_name}</span>
              )}
              <span>Загружен: {formatDateTime(spec.created_at)}</span>
            </>
          }
          actions={
            <Link to="/specifications">
              <Button variant="ghost">← К списку</Button>
            </Link>
          }
        />
        <CardBody className="flex flex-wrap items-center gap-6">
          <div>
            <div className="text-xs uppercase text-slate-500">Статус</div>
            <div className="mt-1">
              <Badge tone={statusTone(spec.status)}>
                {statusLabel(spec.status)}
              </Badge>
            </div>
          </div>

          {spec.error_message && (
            <div className="flex-1 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {spec.error_message}
            </div>
          )}

          <div className="grid flex-1 grid-cols-5 gap-4 text-center text-sm">
            <Counter label="Всего" value={spec.counts.items_total} />
            <Counter
              label="≥ 90%"
              value={spec.counts.items_matched_high}
              valueClass="text-conf-high"
            />
            <Counter
              label="50–90%"
              value={spec.counts.items_matched_medium}
              valueClass="text-conf-medium"
            />
            <Counter
              label="Не найдено"
              value={spec.counts.items_not_found}
              valueClass="text-conf-low"
            />
            <Counter
              label="Закрыто"
              value={`${spec.counts.items_verified} / ${spec.counts.items_total}`}
              valueClass={
                spec.counts.items_verified === spec.counts.items_total
                  ? "text-conf-high"
                  : spec.counts.items_verified > 0
                  ? "text-conf-medium"
                  : "text-slate-400"
              }
            />
          </div>

          <CancelButton specId={specId} status={spec.status} />
        </CardBody>
      </Card>
      </div>

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
                  variant="secondary"
                  onClick={() => autoConfirmMutation.mutate()}
                  disabled={autoConfirmMutation.isPending}
                >
                  {autoConfirmMutation.isPending
                    ? "Подтверждение…"
                    : "Авто-подтвердить"}
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

          {itemsQuery.isLoading ? (
            <div className="px-6 py-8 text-center text-slate-500">
              Загрузка строк…
            </div>
          ) : (
            <div>
              <table className="min-w-full text-sm">
                <thead
                  className="sticky z-10 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 shadow-sm"
                  style={{ top: stickyHeaderHeight }}
                >
                  <tr>
                    <th className="bg-slate-50 px-4 py-3 font-medium w-12">№</th>
                    <th className="bg-slate-50 px-4 py-3 font-medium">Исходная позиция</th>
                    <th className="bg-slate-50 px-4 py-3 font-medium w-28">Кол-во</th>
                    <th className="bg-slate-50 px-4 py-3 font-medium">Топ кандидат каталога</th>
                    <th className="bg-slate-50 px-4 py-3 font-medium w-40">Решение</th>
                    <th className="bg-slate-50 px-4 py-3 font-medium w-32" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <SpecItemRow
                      key={item.id}
                      item={item}
                      pending={verifyMutation.isPending}
                      onVerify={(specItemId, decision, chosenItemId) =>
                        verifyMutation.mutate({
                          specItemId,
                          decision,
                          chosenItemId,
                        })
                      }
                    />
                  ))}
                </tbody>
              </table>
              <Pagination
                page={page}
                pageSize={pageSize}
                total={itemsQuery.data?.total ?? 0}
                onPageChange={setPage}
                onPageSizeChange={(s) => {
                  setPageSize(s);
                  setPage(1);
                }}
              />
            </div>
          )}
        </Card>
      )}
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

function Counter({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: number | string;
  valueClass?: string;
}) {
  return (
    <div>
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div
        className={"mt-1 text-2xl font-semibold tabular-nums " + (valueClass ?? "")}
      >
        {value}
      </div>
    </div>
  );
}

function CancelButton({
  specId,
  status,
}: {
  specId: string;
  status: SpecificationStatus;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: () => api.cancelSpecification(specId, reason.trim() || undefined),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({ queryKey: ["specifications"] });
    },
  });

  // Кнопка не нужна для уже отменённых / выгруженных
  if (status === "cancelled" || status === "exported") return null;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs text-red-600 hover:underline"
        title="Отказаться от обеспечения поставки"
      >
        Отказаться от спецификации
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-red-200 bg-red-50 p-3">
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
            setOpen(false);
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
  );
}
