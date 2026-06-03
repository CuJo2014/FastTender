import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { formatDateTime, statusLabel, statusTone, isInProgress } from "../lib/format";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardHeader } from "../components/ui/Card";

export function SpecificationsListPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["specifications"],
    queryFn: api.listSpecifications,
    // Если есть «в работе» — обновляем каждые 2 секунды
    refetchInterval: (query) => {
      const list = query.state.data ?? [];
      const anyInProgress = list.some((s) => isInProgress(s.status));
      return anyInProgress ? 2000 : false;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteSpecification(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["specifications"] });
    },
  });

  const handleDelete = (id: string, filename: string) => {
    if (
      window.confirm(
        `Удалить спецификацию «${filename}»? Строки, кандидаты и результаты ` +
          `верификации будут удалены безвозвратно.`,
      )
    ) {
      deleteMutation.mutate(id);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Спецификации"
        description="Загруженные клиентские спецификации и результаты обработки"
        actions={
          <Link to="/specifications/upload">
            <Button variant="primary">Загрузить</Button>
          </Link>
        }
      />

      {isLoading && (
        <div className="px-6 py-8 text-center text-slate-500">Загрузка…</div>
      )}

      {error instanceof Error && (
        <div className="px-6 py-8 text-center text-red-600">
          Ошибка: {error.message}
        </div>
      )}

      {data && data.length === 0 && (
        <div className="px-6 py-12 text-center text-slate-500">
          Пока нет загруженных спецификаций.
          <div className="mt-3">
            <Link to="/specifications/upload">
              <Button variant="secondary">Загрузить первую</Button>
            </Link>
          </div>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-6 py-3 font-medium">Файл</th>
                <th className="px-6 py-3 font-medium">Клиент</th>
                <th className="px-6 py-3 font-medium">Статус</th>
                <th className="px-6 py-3 font-medium text-right">Всего</th>
                <th className="px-6 py-3 font-medium text-right text-conf-high">
                  ≥ 90%
                </th>
                <th className="px-6 py-3 font-medium text-right text-conf-medium">
                  50–90%
                </th>
                <th className="px-6 py-3 font-medium text-right text-conf-low">
                  Не найдено
                </th>
                <th className="px-6 py-3 font-medium">Загружена</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {data.map((spec) => (
                <tr key={spec.id} className="hover:bg-slate-50">
                  <td className="px-6 py-3 font-medium">
                    <Link
                      to={`/specifications/${spec.id}`}
                      className="text-slate-900 hover:underline"
                    >
                      {spec.source_filename}
                    </Link>
                  </td>
                  <td className="px-6 py-3 text-slate-600">
                    {spec.client_name ?? "—"}
                  </td>
                  <td className="px-6 py-3">
                    <Badge tone={statusTone(spec.status)}>
                      {statusLabel(spec.status)}
                    </Badge>
                  </td>
                  <td className="px-6 py-3 text-right tabular-nums">
                    {spec.counts.items_total}
                  </td>
                  <td className="px-6 py-3 text-right tabular-nums text-conf-high">
                    {spec.counts.items_matched_high}
                  </td>
                  <td className="px-6 py-3 text-right tabular-nums text-conf-medium">
                    {spec.counts.items_matched_medium}
                  </td>
                  <td className="px-6 py-3 text-right tabular-nums text-conf-low">
                    {spec.counts.items_not_found}
                  </td>
                  <td className="px-6 py-3 text-slate-500">
                    {formatDateTime(spec.created_at)}
                  </td>
                  <td className="px-6 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Link to={`/specifications/${spec.id}`}>
                        <Button variant="ghost" size="sm">
                          Открыть →
                        </Button>
                      </Link>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-red-600 hover:bg-red-50"
                        disabled={
                          deleteMutation.isPending &&
                          deleteMutation.variables === spec.id
                        }
                        onClick={() =>
                          handleDelete(spec.id, spec.source_filename)
                        }
                      >
                        Удалить
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
