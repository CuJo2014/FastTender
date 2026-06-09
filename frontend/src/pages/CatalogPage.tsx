import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { ImportPanel } from "../components/ImportPanel";
import { formatDateTime, formatPrice } from "../lib/format";

export function CatalogPage() {
  const queryClient = useQueryClient();
  const { data: info, isLoading } = useQuery({
    queryKey: ["catalog-info"],
    queryFn: api.getCatalogInfo,
  });

  return (
    <div className="space-y-6">
    <Card>
      <CardHeader
        title="Каталог компании"
        description="Загрузка и обновление справочника товаров (раздел 4.3, Приложение C.1)"
      />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
          {isLoading ? (
            <span className="text-slate-500">Загрузка…</span>
          ) : info && info.items_count > 0 ? (
            <>
              <span className="font-medium">
                {info.items_count.toLocaleString("ru")} активных позиций
              </span>
              {info.last_synced_at && (
                <span className="text-xs text-slate-500">
                  Обновлён: {formatDateTime(info.last_synced_at)}
                </span>
              )}
              {info.created_at && (
                <span className="text-xs text-slate-400">
                  Создан: {formatDateTime(info.created_at)}
                </span>
              )}
            </>
          ) : (
            <span className="text-slate-500">Каталог пуст — загрузите файл ниже</span>
          )}
        </div>

        <ImportPanel
          title="Импорт каталога"
          description="XLSX или CSV. Шапка: Артикул, Наименование, Производитель, Ед. изм., Цена. Технические характеристики Phase 2."
          uploadFn={(file, mode) => api.importCatalog(file, mode)}
          invalidateKey={["catalog-info"]}
        />

        <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">
          <strong>Replace</strong>: предыдущие позиции каталога помечаются
          неактивными (история матчингов сохраняется). <strong>Merge</strong>:
          совпадающие по артикулу обновляются, остальные сохраняются.
        </div>

        <RefetchButton onClick={() => queryClient.invalidateQueries({ queryKey: ["catalog-info"] })} />
      </CardBody>
    </Card>

    <CatalogSearch />
    </div>
  );
}

type SourceFilter = "all" | "company_catalog" | "supplier_pricelist";

function CatalogSearch() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [source, setSource] = useState<SourceFilter>("all");

  const { data, isFetching, error } = useQuery({
    queryKey: ["catalog-search", submitted],
    queryFn: () => api.searchCatalog(submitted, 50),
    enabled: submitted.trim().length > 0,
  });

  const all = data ?? [];
  const results = all.filter(
    (r) => source === "all" || r.source_type === source,
  );

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(query.trim());
  };

  const counts = {
    all: all.length,
    company_catalog: all.filter((r) => r.source_type === "company_catalog").length,
    supplier_pricelist: all.filter((r) => r.source_type === "supplier_pricelist").length,
  };

  return (
    <Card>
      <CardHeader
        title="Поиск по каталогу и прайсам"
        description="По Коду 1С / SKU / Артикулу / Наименованию. Ищет и в каталоге компании, и в прайсах поставщиков."
      />
      <CardBody className="space-y-3">
        <form onSubmit={onSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ц0000001234, DIN933, домкрат бутылочный…"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <Button type="submit" disabled={!query.trim() || isFetching}>
            {isFetching ? "Поиск…" : "Искать"}
          </Button>
        </form>

        {submitted && (
          <div className="flex flex-wrap items-center gap-1 text-xs">
            <span className="mr-1 uppercase text-slate-400">Источник:</span>
            <FilterChip label={`Все · ${counts.all}`} active={source === "all"} onClick={() => setSource("all")} />
            <FilterChip
              label={`Каталог · ${counts.company_catalog}`}
              active={source === "company_catalog"}
              onClick={() => setSource("company_catalog")}
            />
            <FilterChip
              label={`Прайсы · ${counts.supplier_pricelist}`}
              active={source === "supplier_pricelist"}
              onClick={() => setSource("supplier_pricelist")}
            />
          </div>
        )}

        {error instanceof ApiError && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            Ошибка {error.status}
          </div>
        )}

        {submitted && !isFetching && results.length === 0 && (
          <div className="px-2 py-6 text-center text-sm text-slate-500">
            Ничего не найдено по «{submitted}».
          </div>
        )}

        {results.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Источник</th>
                  <th className="px-3 py-2 font-medium">Идентификатор</th>
                  <th className="px-3 py-2 font-medium">Артикул</th>
                  <th className="px-3 py-2 font-medium">Наименование</th>
                  <th className="px-3 py-2 font-medium">Бренд</th>
                  <th className="px-3 py-2 font-medium">Категория</th>
                  <th className="px-3 py-2 font-medium text-right">Цена</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {results.map((r) => (
                  <tr key={r.item_id} className="hover:bg-slate-50">
                    <td className="px-3 py-2">
                      <Badge
                        tone={r.source_type === "company_catalog" ? "info" : "warning"}
                      >
                        {r.source_label}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {r.code_1c ?? r.supplier_sku ?? "—"}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{r.article ?? "—"}</td>
                    <td className="px-3 py-2">{r.name}</td>
                    <td className="px-3 py-2 text-slate-600">{r.manufacturer ?? "—"}</td>
                    <td
                      className="max-w-xs truncate px-3 py-2 text-xs text-slate-500"
                      title={r.category_path ?? undefined}
                    >
                      {r.category_path ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {r.price != null ? formatPrice(String(r.price)) : "—"}
                      {r.currency && (
                        <span className="ml-1 text-xs text-slate-400">{r.currency}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-2 pt-2 text-xs text-slate-400">
              Показано {results.length}{all.length >= 50 ? " (первые 50 — уточните запрос)" : ""}
            </div>
          </div>
        )}
      </CardBody>
    </Card>
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
        "rounded-md px-2.5 py-1 font-medium " +
        (active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100")
      }
    >
      {label}
    </button>
  );
}

function RefetchButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-xs text-blue-600 hover:underline"
    >
      Обновить статистику
    </button>
  );
}
