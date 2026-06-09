import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type {
  CatalogSearchResult,
  GoldLabelStatus,
  GoldRowRead,
} from "../types/api";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardHeader } from "../components/ui/Card";
import { CatalogSearchBox } from "../components/CatalogSearchBox";

const STATUSES: GoldLabelStatus[] = [
  "найдено",
  "аналог",
  "не найдено",
  "сомнительно",
];

const STATUS_TONE: Record<
  GoldLabelStatus,
  "success" | "info" | "warning" | "neutral"
> = {
  найдено: "success",
  аналог: "info",
  "не найдено": "warning",
  сомнительно: "neutral",
};

export function GoldDatasetPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<GoldLabelStatus | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["gold-rows", filter],
    queryFn: () => api.listGoldRows(filter ?? undefined),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["gold-rows"] });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteGoldRow(id),
    onSuccess: invalidate,
  });

  const handleDelete = (row: GoldRowRead) => {
    if (window.confirm(`Удалить строку эталона «${row.name}»?`)) {
      deleteMut.mutate(row.id);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Золотой датасет"
        description="Эталонные строки «спецификация → правильная позиция каталога» для оценки матчера (Recall@5 / Precision@1 / MRR)"
        actions={
          <a href={api.goldExportUrl()} download>
            <Button variant="outline" size="sm">
              ↓ Экспорт в Excel
            </Button>
          </a>
        }
      />

      {/* Форма добавления */}
      <AddGoldRowForm onCreated={invalidate} />

      {/* Фильтр по статусу */}
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 px-6 py-3">
        <span className="mr-2 text-xs font-medium uppercase text-slate-400">
          Статус:
        </span>
        <FilterChip
          label="Все"
          active={filter === null}
          onClick={() => setFilter(null)}
        />
        {STATUSES.map((s) => (
          <FilterChip
            key={s}
            label={s}
            active={filter === s}
            onClick={() => setFilter(s)}
          />
        ))}
        <span className="ml-auto text-xs text-slate-400">
          {data ? `${data.length} строк` : ""}
        </span>
      </div>

      {isLoading && (
        <div className="px-6 py-8 text-center text-slate-500">Загрузка…</div>
      )}
      {error instanceof Error && (
        <div className="px-6 py-8 text-center text-red-600">{error.message}</div>
      )}

      {data && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Наименование (клиент)</th>
                <th className="px-4 py-3 font-medium">Кол-во</th>
                <th className="px-4 py-3 font-medium">Эталон (каталог)</th>
                <th className="px-4 py-3 font-medium">Статус</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {data.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-500">
                    Пока нет строк. Добавьте вручную или из строки спецификации.
                  </td>
                </tr>
              )}
              {data.map((row) => (
                <GoldRowItem
                  key={row.id}
                  row={row}
                  expanded={editingId === row.id}
                  onToggle={() =>
                    setEditingId((id) => (id === row.id ? null : row.id))
                  }
                  onSaved={() => {
                    setEditingId(null);
                    invalidate();
                  }}
                  onDelete={() => handleDelete(row)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// --- Строка таблицы + раскрывающийся редактор ---

function GoldRowItem({
  row,
  expanded,
  onToggle,
  onSaved,
  onDelete,
}: {
  row: GoldRowRead;
  expanded: boolean;
  onToggle: () => void;
  onSaved: () => void;
  onDelete: () => void;
}) {
  return (
    <>
      <tr className="hover:bg-slate-50">
        <td className="px-4 py-3">
          <div className="font-medium">{row.name}</div>
          <div className="mt-0.5 text-xs text-slate-500">
            {row.article && <span className="font-mono">{row.article}</span>}
            {row.manufacturer && <span className="ml-2">{row.manufacturer}</span>}
            {row.source_file && (
              <span className="ml-2 text-slate-400">· {row.source_file}</span>
            )}
          </div>
        </td>
        <td className="px-4 py-3 tabular-nums text-slate-600">
          {row.quantity ?? "—"} {row.unit ?? ""}
        </td>
        <td className="px-4 py-3">
          {row.expected_article || row.expected_code_1c || row.expected_name ? (
            <div className="text-sm">
              <div className="line-clamp-2 text-emerald-700" title={row.expected_name ?? ""}>
                {row.expected_name ?? "—"}
              </div>
              <div className="font-mono text-xs text-slate-500">
                {row.expected_article ?? row.expected_code_1c ?? ""}
              </div>
            </div>
          ) : (
            <span className="text-sm text-slate-400">—</span>
          )}
        </td>
        <td className="px-4 py-3">
          <Badge tone={STATUS_TONE[row.label_status]}>{row.label_status}</Badge>
        </td>
        <td className="px-4 py-3 text-right">
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="ghost" onClick={onToggle}>
              {expanded ? "Свернуть" : "Изменить"}
            </Button>
            <Button
              size="sm"
              variant="danger-ghost"
              onClick={onDelete}
            >
              Удалить
            </Button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={5} className="bg-slate-50 px-4 py-4">
            <EditGoldRowPanel row={row} onSaved={onSaved} />
          </td>
        </tr>
      )}
    </>
  );
}

function EditGoldRowPanel({
  row,
  onSaved,
}: {
  row: GoldRowRead;
  onSaved: () => void;
}) {
  const [name, setName] = useState(row.name);
  const [article, setArticle] = useState(row.article ?? "");
  const [manufacturer, setManufacturer] = useState(row.manufacturer ?? "");
  const [quantity, setQuantity] = useState(
    row.quantity != null ? String(row.quantity) : "",
  );
  const [unit, setUnit] = useState(row.unit ?? "");
  const [labelStatus, setLabelStatus] = useState<GoldLabelStatus>(
    row.label_status,
  );
  const [notes, setNotes] = useState(row.labeler_notes ?? "");
  const [expected, setExpected] = useState<{
    id: string | null;
    name: string | null;
    article: string | null;
    code: string | null;
  }>({
    id: row.expected_item_id,
    name: row.expected_name,
    article: row.expected_article,
    code: row.expected_code_1c,
  });

  const saveMut = useMutation({
    mutationFn: () =>
      api.updateGoldRow(row.id, {
        name: name.trim(),
        article: article.trim() || null,
        manufacturer: manufacturer.trim() || null,
        quantity: quantity.trim() ? Number(quantity) : null,
        unit: unit.trim() || null,
        label_status: labelStatus,
        labeler_notes: notes.trim() || null,
        expected_item_id: expected.id,
      }),
    onSuccess: onSaved,
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <LabeledInput label="Наименование (клиент)*" value={name} onChange={setName} wide />
        <LabeledInput label="Артикул" value={article} onChange={setArticle} />
        <LabeledInput label="Производитель" value={manufacturer} onChange={setManufacturer} />
        <LabeledInput label="Кол-во" value={quantity} onChange={setQuantity} narrow />
        <LabeledInput label="Ед." value={unit} onChange={setUnit} narrow />
        <StatusSelect value={labelStatus} onChange={setLabelStatus} />
      </div>

      <div>
        <div className="mb-1 text-xs font-medium text-slate-500">
          Эталонная позиция каталога
        </div>
        {expected.id ? (
          <div className="mb-2 flex items-center gap-2 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm">
            <span className="text-emerald-800">
              {expected.name ?? expected.article ?? expected.code}
            </span>
            <span className="font-mono text-xs text-slate-500">
              {expected.article ?? expected.code ?? ""}
            </span>
            <button
              type="button"
              className="ml-auto text-xs text-slate-500 hover:underline"
              onClick={() =>
                setExpected({ id: null, name: null, article: null, code: null })
              }
            >
              убрать
            </button>
          </div>
        ) : null}
        <CatalogSearchBox
          initialQuery={name}
          onPick={() => {}}
          onPickResult={(r: CatalogSearchResult) =>
            setExpected({
              id: r.item_id,
              name: r.name,
              article: r.article,
              code: r.code_1c,
            })
          }
          disabled={saveMut.isPending}
        />
      </div>

      <LabeledInput label="Примечание разметчика" value={notes} onChange={setNotes} wide />

      {saveMut.isError && (
        <div className="text-sm text-red-600">
          {saveMut.error instanceof ApiError
            ? ((saveMut.error.detail as { message?: string })?.message ??
              `Ошибка ${saveMut.error.status}`)
            : "Ошибка сохранения"}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button
          size="sm"
          onClick={() => saveMut.mutate()}
          disabled={!name.trim() || saveMut.isPending}
        >
          {saveMut.isPending ? "Сохранение…" : "Сохранить"}
        </Button>
      </div>
    </div>
  );
}

// --- Форма добавления новой строки ---

function AddGoldRowForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [article, setArticle] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [quantity, setQuantity] = useState("");
  const [unit, setUnit] = useState("");
  const [labelStatus, setLabelStatus] = useState<GoldLabelStatus>("найдено");
  const [notes, setNotes] = useState("");
  const [expected, setExpected] = useState<{
    id: string | null;
    name: string | null;
    article: string | null;
    code: string | null;
  }>({ id: null, name: null, article: null, code: null });

  const reset = () => {
    setName("");
    setArticle("");
    setManufacturer("");
    setQuantity("");
    setUnit("");
    setLabelStatus("найдено");
    setNotes("");
    setExpected({ id: null, name: null, article: null, code: null });
  };

  const createMut = useMutation({
    mutationFn: () =>
      api.createGoldRow({
        name: name.trim(),
        article: article.trim() || null,
        manufacturer: manufacturer.trim() || null,
        quantity: quantity.trim() ? Number(quantity) : null,
        unit: unit.trim() || null,
        label_status: labelStatus,
        labeler_notes: notes.trim() || null,
        expected_item_id: expected.id,
      }),
    onSuccess: () => {
      reset();
      onCreated();
    },
  });

  if (!open) {
    return (
      <div className="border-b border-slate-200 bg-slate-50 px-6 py-3">
        <Button size="sm" onClick={() => setOpen(true)}>
          + Добавить строку
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3 border-b border-slate-200 bg-slate-50 px-6 py-4">
      <div className="flex flex-wrap gap-2">
        <LabeledInput label="Наименование (клиент)*" value={name} onChange={setName} wide />
        <LabeledInput label="Артикул" value={article} onChange={setArticle} />
        <LabeledInput label="Производитель" value={manufacturer} onChange={setManufacturer} />
        <LabeledInput label="Кол-во" value={quantity} onChange={setQuantity} narrow />
        <LabeledInput label="Ед." value={unit} onChange={setUnit} narrow />
        <StatusSelect value={labelStatus} onChange={setLabelStatus} />
      </div>

      <div>
        <div className="mb-1 text-xs font-medium text-slate-500">
          Эталонная позиция каталога
        </div>
        {expected.id ? (
          <div className="mb-2 flex items-center gap-2 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm">
            <span className="text-emerald-800">
              {expected.name ?? expected.article ?? expected.code}
            </span>
            <span className="font-mono text-xs text-slate-500">
              {expected.article ?? expected.code ?? ""}
            </span>
            <button
              type="button"
              className="ml-auto text-xs text-slate-500 hover:underline"
              onClick={() =>
                setExpected({ id: null, name: null, article: null, code: null })
              }
            >
              убрать
            </button>
          </div>
        ) : null}
        <CatalogSearchBox
          initialQuery={name}
          onPick={() => {}}
          onPickResult={(r: CatalogSearchResult) =>
            setExpected({
              id: r.item_id,
              name: r.name,
              article: r.article,
              code: r.code_1c,
            })
          }
          disabled={createMut.isPending}
        />
      </div>

      <LabeledInput label="Примечание разметчика" value={notes} onChange={setNotes} wide />

      {createMut.isError && (
        <div className="text-sm text-red-600">
          {createMut.error instanceof ApiError
            ? ((createMut.error.detail as { message?: string })?.message ??
              `Ошибка ${createMut.error.status}`)
            : "Ошибка создания"}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            reset();
            setOpen(false);
          }}
        >
          Отмена
        </Button>
        <Button
          size="sm"
          onClick={() => createMut.mutate()}
          disabled={!name.trim() || createMut.isPending}
        >
          {createMut.isPending ? "Добавление…" : "Добавить"}
        </Button>
      </div>
    </div>
  );
}

// --- Мелкие UI-хелперы ---

const inputCls = "w-full rounded border border-slate-300 px-2 py-1 text-sm";

function LabeledInput({
  label,
  value,
  onChange,
  wide,
  narrow,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  wide?: boolean;
  narrow?: boolean;
}) {
  return (
    <label
      className={
        "flex flex-col gap-1 " +
        (wide ? "min-w-64 flex-1 " : "") +
        (narrow ? "w-20" : "")
      }
    >
      <span className="text-xs font-medium text-slate-500">{label}</span>
      <input className={inputCls} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function StatusSelect({
  value,
  onChange,
}: {
  value: GoldLabelStatus;
  onChange: (v: GoldLabelStatus) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-slate-500">Статус</span>
      <select
        className={inputCls}
        value={value}
        onChange={(e) => onChange(e.target.value as GoldLabelStatus)}
      >
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </label>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "rounded-md px-2.5 py-1 text-xs font-medium " +
        (active
          ? "bg-slate-900 text-white"
          : "text-slate-600 hover:bg-slate-100")
      }
    >
      {label}
    </button>
  );
}
