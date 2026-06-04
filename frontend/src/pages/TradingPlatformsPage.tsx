import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { TradingPlatformRead } from "../types/api";
import { Button } from "../components/ui/Button";
import { Card, CardHeader } from "../components/ui/Card";

const inputCls = "w-full rounded border border-slate-300 px-2 py-1 text-sm";

export function TradingPlatformsPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["trading-platforms"],
    queryFn: () => api.listPlatforms(),
  });

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [editing, setEditing] = useState<TradingPlatformRead | null>(null);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["trading-platforms"] });

  const createMut = useMutation({
    mutationFn: () =>
      api.createPlatform({ name: name.trim(), url: url.trim() || null }),
    onSuccess: () => {
      setName("");
      setUrl("");
      invalidate();
    },
  });

  const updateMut = useMutation({
    mutationFn: (p: TradingPlatformRead) =>
      api.updatePlatform(p.id, { name: p.name.trim(), url: p.url?.trim() || null }),
    onSuccess: () => {
      setEditing(null);
      invalidate();
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deletePlatform(id),
    onSuccess: invalidate,
  });

  const handleDelete = (p: TradingPlatformRead) => {
    const warn =
      p.specifications_count > 0
        ? ` У площадки ${p.specifications_count} спец.; они будут отвязаны.`
        : "";
    if (window.confirm(`Удалить площадку «${p.name}»?${warn}`)) {
      deleteMut.mutate(p.id);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Торговые площадки"
        description="Справочник ЭТП для спецификаций тендеров"
      />

      <div className="border-b border-slate-200 bg-slate-50 px-6 py-4">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) createMut.mutate();
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-slate-500">Наименование*</span>
            <input className={inputCls} value={name} required onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="flex min-w-64 flex-1 flex-col gap-1">
            <span className="text-xs font-medium text-slate-500">URL</span>
            <input className={inputCls} value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <Button type="submit" disabled={!name.trim() || createMut.isPending}>
            {createMut.isPending ? "Добавление…" : "Добавить"}
          </Button>
        </form>
        {createMut.isError && (
          <div className="mt-2 text-sm text-red-600">
            {createMut.error instanceof ApiError
              ? (createMut.error.detail as { message?: string })?.message ??
                `Ошибка ${createMut.error.status}`
              : "Ошибка создания"}
          </div>
        )}
      </div>

      {isLoading && <div className="px-6 py-8 text-center text-slate-500">Загрузка…</div>}
      {error instanceof Error && (
        <div className="px-6 py-8 text-center text-red-600">{error.message}</div>
      )}

      {data && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-6 py-3 font-medium">Наименование</th>
                <th className="px-6 py-3 font-medium">URL</th>
                <th className="px-6 py-3 font-medium text-right">Спец.</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {data.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-slate-500">
                    Пока нет площадок.
                  </td>
                </tr>
              )}
              {data.map((p) =>
                editing?.id === p.id ? (
                  <tr key={p.id} className="bg-amber-50">
                    <td className="px-6 py-2">
                      <input
                        className={inputCls}
                        value={editing.name}
                        onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                      />
                    </td>
                    <td className="px-6 py-2">
                      <input
                        className={inputCls}
                        value={editing.url ?? ""}
                        onChange={(e) => setEditing({ ...editing, url: e.target.value })}
                      />
                    </td>
                    <td className="px-6 py-2 text-right tabular-nums text-slate-500">
                      {p.specifications_count}
                    </td>
                    <td className="px-6 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          onClick={() => updateMut.mutate(editing)}
                          disabled={!editing.name.trim() || updateMut.isPending}
                        >
                          Сохранить
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                          Отмена
                        </Button>
                      </div>
                    </td>
                  </tr>
                ) : (
                  <tr key={p.id} className="hover:bg-slate-50">
                    <td className="px-6 py-3 font-medium">{p.name}</td>
                    <td className="px-6 py-3 text-slate-600">
                      {p.url ? (
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-blue-600 hover:underline"
                        >
                          {p.url}
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-6 py-3 text-right tabular-nums text-slate-500">
                      {p.specifications_count}
                    </td>
                    <td className="px-6 py-3 text-right">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>
                          Изменить
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-red-600 hover:bg-red-50"
                          onClick={() => handleDelete(p)}
                        >
                          Удалить
                        </Button>
                      </div>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
