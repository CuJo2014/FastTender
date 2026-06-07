import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { CatalogSearchResult } from "../types/api";
import { Button } from "./ui/Button";

interface Props {
  onPick: (itemId: string) => void;
  /** Дополнительно отдаёт всю карточку результата (для отображения выбора). */
  onPickResult?: (result: CatalogSearchResult) => void;
  disabled?: boolean;
  initialQuery?: string;
}

export function CatalogSearchBox({
  onPick,
  onPickResult,
  disabled,
  initialQuery,
}: Props) {
  // Предзаполняем именем позиции — видно, что ищем, и поиск в один клик.
  const [query, setQuery] = useState(initialQuery ?? "");
  const [results, setResults] = useState<CatalogSearchResult[]>([]);

  const mutation = useMutation({
    mutationFn: (q: string) => api.searchCatalog(q, 20),
    onSuccess: (data) => setResults(data),
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) mutation.mutate(query.trim());
  };

  return (
    <div className="rounded-md border border-slate-200 bg-white">
      <div className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium uppercase text-slate-500">
        Найти в каталоге и прайсах по Коду 1С / SKU / Артикулу / Наименованию
      </div>
      <form onSubmit={handleSearch} className="flex items-center gap-2 px-3 py-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ц0000001234 или DIN933 или часть имени"
          className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <Button
          type="submit"
          size="sm"
          disabled={!query.trim() || mutation.isPending}
        >
          {mutation.isPending ? "Поиск…" : "Искать"}
        </Button>
        {results.length > 0 && (
          <button
            type="button"
            onClick={() => {
              setResults([]);
              setQuery("");
            }}
            className="text-xs text-slate-500 hover:underline"
          >
            очистить
          </button>
        )}
      </form>

      {mutation.isError && (
        <div className="border-t border-slate-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          {mutation.error instanceof ApiError
            ? `Ошибка ${mutation.error.status}`
            : "Не удалось найти"}
        </div>
      )}

      {results.length > 0 && (
        <table className="min-w-full border-t border-slate-200 text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-1">Источник</th>
              <th className="px-3 py-1">Идентификатор</th>
              <th className="px-3 py-1">Артикул</th>
              <th className="px-3 py-1">Наименование</th>
              <th className="px-3 py-1">Бренд</th>
              <th className="px-3 py-1 text-right">Цена</th>
              <th className="px-3 py-1 w-24" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {results.map((r) => (
              <tr key={r.item_id} className="hover:bg-slate-50">
                <td className="px-3 py-1">
                  <span
                    className={
                      "inline-block rounded px-1.5 py-0.5 text-[10px] " +
                      (r.source_type === "company_catalog"
                        ? "bg-blue-50 text-blue-700"
                        : "bg-amber-50 text-amber-700")
                    }
                  >
                    {r.source_label}
                  </span>
                </td>
                <td className="px-3 py-1 font-mono text-xs">
                  {r.code_1c ?? r.supplier_sku ?? "—"}
                </td>
                <td className="px-3 py-1 font-mono text-xs">
                  {r.article ?? "—"}
                </td>
                <td className="px-3 py-1">{r.name}</td>
                <td className="px-3 py-1 text-slate-600">
                  {r.manufacturer ?? "—"}
                </td>
                <td className="px-3 py-1 text-right tabular-nums">
                  {r.price ?? "—"}
                  {r.currency && (
                    <span className="ml-1 text-xs text-slate-400">
                      {r.currency}
                    </span>
                  )}
                </td>
                <td className="px-3 py-1 text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      onPick(r.item_id);
                      onPickResult?.(r);
                    }}
                    disabled={disabled}
                  >
                    Выбрать
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {mutation.isSuccess && results.length === 0 && (
        <div className="border-t border-slate-200 px-3 py-2 text-xs text-slate-500">
          Не найдено
        </div>
      )}
    </div>
  );
}
