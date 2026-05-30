import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { ImportPanel } from "../components/ImportPanel";
import { formatDateTime } from "../lib/format";

export function CatalogPage() {
  const queryClient = useQueryClient();
  const { data: info, isLoading } = useQuery({
    queryKey: ["catalog-info"],
    queryFn: api.getCatalogInfo,
  });

  return (
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
