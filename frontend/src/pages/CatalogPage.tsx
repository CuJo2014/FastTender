import { api } from "../lib/api";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { ImportPanel } from "../components/ImportPanel";

export function CatalogPage() {
  return (
    <Card>
      <CardHeader
        title="Каталог компании"
        description="Загрузка и обновление справочника товаров (раздел 4.3, Приложение C.1)"
      />
      <CardBody className="space-y-4">
        <ImportPanel
          title="Импорт каталога"
          description="XLSX или CSV. Шапка: Артикул, Наименование, Производитель, Ед. изм., Цена. Технические характеристики Phase 2."
          uploadFn={(file, mode) => api.importCatalog(file, mode)}
        />

        <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">
          <strong>Replace</strong>: предыдущие позиции каталога помечаются
          неактивными (история матчингов сохраняется). <strong>Merge</strong>:
          совпадающие по артикулу обновляются, остальные сохраняются.
        </div>
      </CardBody>
    </Card>
  );
}
