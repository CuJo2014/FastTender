import { useCallback, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type {
  SpecificationRead,
  SpecificationStatus,
  VerificationDecision,
} from "../types/api";
import { Badge } from "../components/ui/Badge";
import { ProgressBar } from "../components/ProgressBar";
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

  const unverifyMutation = useMutation({
    mutationFn: (specItemId: string) => api.unverifySpecItem(specId, specItemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["specifications", specId] });
      queryClient.invalidateQueries({
        queryKey: ["specifications", specId, "items"],
      });
    },
  });

  const addToGoldMutation = useMutation({
    mutationFn: (specItemId: string) =>
      api.createGoldRowFromSpecItem({ spec_item_id: specItemId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["gold-rows"] });
      window.alert("Строка добавлена в золотой датасет");
    },
    onError: (e) =>
      window.alert(
        e instanceof ApiError
          ? `Ошибка ${e.status}`
          : "Не удалось добавить в gold dataset",
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

  return (
    <div className="space-y-6">
      <div ref={setStickyHeaderEl} className="sticky top-14 z-20 bg-slate-50 pb-2">
      <Card>
        <CardHeader
          title={spec.source_filename}
          description={<span>Загружен: {formatDateTime(spec.created_at)}</span>}
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

          {isInProgress(spec.status) && (
            <div className="basis-full sm:max-w-md">
              <ProgressBar spec={spec} />
            </div>
          )}

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
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  {/* sticky на <th>, а не на <thead> — для кросс-браузерной
                      совместимости (Safari/старый Firefox требуют именно так).
                      top = высота шапки спеки + 56px (header h-14). */}
                  <tr>
                    {[
                      { label: "№", width: "w-12" },
                      { label: "Исходная позиция" },
                      { label: "Кол-во", width: "w-28" },
                      { label: "Выбранная позиция" },
                      { label: "Решение", width: "w-40" },
                      { label: "", width: "w-32" },
                    ].map((col, i) => (
                      <th
                        key={i}
                        className={`sticky z-10 bg-slate-50 px-4 py-3 font-medium shadow-sm ${col.width ?? ""}`}
                        style={{ top: stickyHeaderHeight + 56 }}
                      >
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <SpecItemRow
                      key={item.id}
                      item={item}
                      pending={verifyMutation.isPending || unverifyMutation.isPending}
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
                      onAddToGold={(specItemId) =>
                        addToGoldMutation.mutate(specItemId)
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
