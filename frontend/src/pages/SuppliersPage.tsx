import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { SupplierRead, SupplierTransformations } from "../types/api";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { ImportPanel } from "../components/ImportPanel";
import { formatDateTime } from "../lib/format";

export function SuppliersPage() {
  return (
    <div className="space-y-6">
      <NewSupplierForm />
      <SupplierList />
    </div>
  );
}

function SupplierList() {
  const { data, isLoading } = useQuery({
    queryKey: ["suppliers"],
    queryFn: api.listSuppliers,
  });

  return (
    <Card className="overflow-visible">
      <CardHeader
        title={`Поставщики${data && data.length > 0 ? ` (${data.length})` : ""}`}
        description="Управление прайс-листами"
        className="sticky top-14 z-10 rounded-t-lg shadow-sm"
      />
      <CardBody>
        {isLoading && (
          <div className="text-slate-500">Загрузка…</div>
        )}
        {data && data.length === 0 && (
          <div className="text-slate-500">
            Пока нет поставщиков. Добавьте первого ниже.
          </div>
        )}
        {data && data.length > 0 && (
          <ul className="space-y-4">
            {data.map((supplier) => (
              <SupplierRow key={supplier.id} supplier={supplier} />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function SupplierRow({ supplier }: { supplier: SupplierRead }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <li className="rounded-lg border border-slate-200">
      <div className="flex items-start justify-between gap-4 p-4">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex grow items-start gap-2 text-left"
          title={expanded ? "Свернуть" : "Развернуть"}
        >
          <span className="mt-0.5 text-slate-400">{expanded ? "▾" : "▸"}</span>
          <div className="grow">
            <div className="flex items-center gap-2">
              <span className="font-medium">{supplier.name}</span>
              {supplier.prefix && (
                <span
                  title="Префикс внутреннего SKU"
                  className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700"
                >
                  {supplier.prefix}
                </span>
              )}
              <span className="text-xs text-slate-500">
                · {supplier.pricelist_items_count.toLocaleString("ru")} позиций
              </span>
            </div>
            {supplier.contact_email && (
              <div className="text-xs text-slate-500">{supplier.contact_email}</div>
            )}
            <div className="text-xs text-slate-400">
              {supplier.pricelist_last_synced_at && (
                <>Обновлён: {formatDateTime(supplier.pricelist_last_synced_at)} · </>
              )}
              Создан: {formatDateTime(supplier.created_at)}
            </div>
          </div>
        </button>
        <PrefixEditor supplier={supplier} />
      </div>

      {expanded && (
        <div className="border-t border-slate-200 p-4 pt-3">
          <TransformationsBlock supplier={supplier} />

          <ImportPanel
            title="Импорт прайса этого поставщика"
            description={
              supplier.prefix
                ? `Каждой позиции присвоится внутренний SKU ${supplier.prefix}-NNNNNN (стабильно при пере-загрузке)`
                : "Совет: укажите префикс справа — тогда каждая позиция получит внутренний SKU для ссылок в КП"
            }
            uploadFn={(file, mode) =>
              api.importSupplierPricelist(supplier.id, file, mode)
            }
          />
        </div>
      )}
    </li>
  );
}

function TransformationsBlock({ supplier }: { supplier: SupplierRead }) {
  const queryClient = useQueryClient();
  const t = supplier.transformations ?? {};
  const [open, setOpen] = useState(false);
  const [brandRegex, setBrandRegex] = useState(t.brand_regex ?? "");
  const [vatIncluded, setVatIncluded] = useState(t.vat_included ?? false);
  const [vatRate, setVatRate] = useState(t.vat_rate ?? 20);
  const [defaultUnit, setDefaultUnit] = useState(t.default_unit ?? "");
  const [defaultCurrency, setDefaultCurrency] = useState(t.default_currency ?? "");
  const [manufacturer, setManufacturer] = useState(t.manufacturer ?? "");

  const mutation = useMutation({
    mutationFn: () =>
      api.updateSupplier(supplier.id, {
        transformations: {
          brand_regex: brandRegex.trim() === "" ? null : brandRegex.trim(),
          vat_included: vatIncluded,
          vat_rate: vatRate,
          default_unit: defaultUnit.trim() === "" ? null : defaultUnit.trim(),
          default_currency:
            defaultCurrency.trim() === "" ? null : defaultCurrency.trim(),
          manufacturer: manufacturer.trim() === "" ? null : manufacturer.trim(),
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  const summary = describeTransformations(t);

  return (
    <div className="mb-3 rounded-md border border-slate-200 bg-slate-50/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-medium text-slate-700 hover:bg-slate-100"
      >
        <span>
          {open ? "▾" : "▸"} Особенности прайса{" "}
          <span className="ml-2 text-slate-500">{summary}</span>
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-200 px-3 py-3 text-sm">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">
              Бренд внутри Наименования (regex с 2 группами)
            </label>
            <input
              type="text"
              value={brandRegex}
              onChange={(e) => setBrandRegex(e.target.value)}
              placeholder="^(.+?)\s*//\s*(.+?)\s*$"
              className="block w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
            />
            <div className="mt-0.5 text-[10px] text-slate-500">
              Применяется если поле manufacturer пустое. group(1) = очищенное
              имя, group(2) = бренд. Пример: «Болт // Sparta» → name=«Болт»,
              brand=«Sparta».
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={vatIncluded}
                onChange={(e) => setVatIncluded(e.target.checked)}
              />
              Цена с НДС → вычесть
            </label>
            {vatIncluded && (
              <label className="flex items-center gap-1 text-xs">
                Ставка:
                <input
                  type="number"
                  value={vatRate}
                  onChange={(e) => setVatRate(Number(e.target.value))}
                  min={0}
                  max={100}
                  className="w-14 rounded border border-slate-300 px-1.5 py-0.5"
                />
                %
              </label>
            )}
          </div>

          <div className="flex flex-wrap gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Ед.изм. по умолчанию (если пусто в файле)
              </label>
              <input
                type="text"
                value={defaultUnit}
                onChange={(e) => setDefaultUnit(e.target.value)}
                placeholder="шт"
                maxLength={32}
                className="w-24 rounded border border-slate-300 px-2 py-1 text-xs"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Валюта по умолчанию
              </label>
              <input
                type="text"
                value={defaultCurrency}
                onChange={(e) => setDefaultCurrency(e.target.value.toUpperCase())}
                placeholder="RUB"
                maxLength={8}
                className="w-20 rounded border border-slate-300 px-2 py-1 text-xs uppercase"
              />
            </div>
            <div className="grow">
              <label className="mb-1 block text-xs font-medium text-slate-700">
                Производитель <span className="text-slate-400">(перетирает значение из файла)</span>
              </label>
              <input
                type="text"
                value={manufacturer}
                onChange={(e) => setManufacturer(e.target.value)}
                placeholder="Milwaukee"
                maxLength={255}
                className="block w-full rounded border border-slate-300 px-2 py-1 text-xs"
              />
              <div className="mt-0.5 text-[10px] text-slate-500">
                Применяется ко всем позициям прайса. После сохранения существующие позиции обновятся, ссылки в каталог пересчитаются автоматически.
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Сохранение…" : "Сохранить"}
            </Button>
            <span className="text-[10px] text-slate-500">
              Применятся к следующему импорту прайса
            </span>
            {mutation.isError && (
              <span className="text-xs text-red-700">
                {mutation.error instanceof ApiError
                  ? `Ошибка ${mutation.error.status}`
                  : "Ошибка"}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function describeTransformations(t: SupplierTransformations): string {
  const parts: string[] = [];
  if (t.manufacturer) parts.push(`бренд=${t.manufacturer}`);
  if (t.brand_regex) parts.push("бренд из имени");
  if (t.vat_included) parts.push(`НДС ${t.vat_rate ?? 20}%`);
  if (t.default_unit) parts.push(`ед=${t.default_unit}`);
  if (t.default_currency) parts.push(`вал=${t.default_currency}`);
  return parts.length === 0 ? "(не настроены)" : parts.join(", ");
}

function PrefixEditor({ supplier }: { supplier: SupplierRead }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(supplier.prefix ?? "");

  const mutation = useMutation({
    mutationFn: () =>
      api.updateSupplier(supplier.id, {
        prefix: value.trim() === "" ? null : value.trim().toUpperCase(),
      }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="text-xs text-blue-600 hover:underline"
      >
        {supplier.prefix ? "изменить префикс" : "+ добавить префикс"}
      </button>
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) =>
            setValue(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 3))
          }
          placeholder="SIB"
          maxLength={3}
          className="w-16 rounded border border-slate-300 px-2 py-1 text-center font-mono text-sm uppercase"
        />
        <Button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || (value !== "" && value.length !== 3)}
        >
          {mutation.isPending ? "…" : "OK"}
        </Button>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setValue(supplier.prefix ?? "");
          }}
          className="text-xs text-slate-500 hover:underline"
        >
          отмена
        </button>
      </div>
      {mutation.isError && (
        <div className="text-xs text-red-700">
          {mutation.error instanceof ApiError
            ? mutation.error.status === 409
              ? "Префикс занят"
              : `Ошибка ${mutation.error.status}`
            : "Ошибка"}
        </div>
      )}
      <div className="text-[10px] text-slate-400">3 символа A-Z 0-9</div>
    </div>
  );
}

function NewSupplierForm() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [prefix, setPrefix] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      api.createSupplier({
        name: name.trim(),
        contact_email: email.trim() || null,
        prefix: prefix.trim() === "" ? null : prefix.trim().toUpperCase(),
      }),
    onSuccess: () => {
      setName("");
      setEmail("");
      setPrefix("");
      queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  const prefixValid = prefix === "" || prefix.length === 3;
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !prefixValid) return;
    mutation.mutate();
  };

  return (
    <Card>
      <CardHeader title="Добавить поставщика" />
      <CardBody>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          <div className="grow">
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Название
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ООО Поставщик"
              required
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="grow">
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Email <span className="text-slate-400">(опционально)</span>
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="info@supplier.ru"
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Префикс <span className="text-slate-400">(3 симв.)</span>
            </label>
            <input
              type="text"
              value={prefix}
              onChange={(e) =>
                setPrefix(
                  e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 3),
                )
              }
              placeholder="SIB"
              maxLength={3}
              className="w-20 rounded-md border border-slate-300 px-3 py-2 text-center font-mono text-sm uppercase focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <Button
            type="submit"
            disabled={!name.trim() || !prefixValid || mutation.isPending}
          >
            {mutation.isPending ? "Создание…" : "Создать"}
          </Button>

          {mutation.isError && (
            <div className="w-full rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {mutation.error instanceof ApiError
                ? `Ошибка ${mutation.error.status}: ${JSON.stringify(mutation.error.detail)}`
                : (mutation.error as Error).message}
            </div>
          )}
        </form>
      </CardBody>
    </Card>
  );
}
