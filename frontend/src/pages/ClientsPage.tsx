import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { ClientRead } from "../types/api";
import { Button } from "../components/ui/Button";
import { Card, CardHeader } from "../components/ui/Card";

export function ClientsPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["clients"],
    queryFn: () => api.listClients(),
  });

  const [name, setName] = useState("");
  const [inn, setInn] = useState("");
  const [contact, setContact] = useState("");
  const [editing, setEditing] = useState<ClientRead | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["clients"] });

  const createMut = useMutation({
    mutationFn: () =>
      api.createClient({
        name: name.trim(),
        inn: inn.trim() || null,
        contact: contact.trim() || null,
      }),
    onSuccess: () => {
      setName("");
      setInn("");
      setContact("");
      invalidate();
    },
  });

  const updateMut = useMutation({
    mutationFn: (c: ClientRead) =>
      api.updateClient(c.id, {
        name: c.name.trim(),
        inn: c.inn?.trim() || null,
        contact: c.contact?.trim() || null,
      }),
    onSuccess: () => {
      setEditing(null);
      invalidate();
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteClient(id),
    onSuccess: invalidate,
  });

  const handleDelete = (c: ClientRead) => {
    const warn =
      c.specifications_count > 0
        ? ` У клиента ${c.specifications_count} спец.; они будут отвязаны.`
        : "";
    if (window.confirm(`Удалить клиента «${c.name}»?${warn}`)) {
      deleteMut.mutate(c.id);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Клиенты"
        description="Справочник клиентов-заказчиков спецификаций"
      />

      <div className="border-b border-slate-200 bg-slate-50 px-6 py-4">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) createMut.mutate();
          }}
        >
          <Field label="Наименование*" value={name} onChange={setName} required />
          <Field label="ИНН" value={inn} onChange={setInn} />
          <Field label="Контакт" value={contact} onChange={setContact} wide />
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
                <th className="px-6 py-3 font-medium">Наименование</th>
                <th className="px-6 py-3 font-medium">ИНН</th>
                <th className="px-6 py-3 font-medium">Контакт</th>
                <th className="px-6 py-3 font-medium text-right">Спец.</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {data.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-500">
                    Пока нет клиентов.
                  </td>
                </tr>
              )}
              {data.map((c) =>
                editing?.id === c.id ? (
                  <tr key={c.id} className="bg-amber-50">
                    <td className="px-6 py-2">
                      <input
                        className={inputCls}
                        value={editing.name}
                        onChange={(e) =>
                          setEditing({ ...editing, name: e.target.value })
                        }
                      />
                    </td>
                    <td className="px-6 py-2">
                      <input
                        className={inputCls}
                        value={editing.inn ?? ""}
                        onChange={(e) =>
                          setEditing({ ...editing, inn: e.target.value })
                        }
                      />
                    </td>
                    <td className="px-6 py-2">
                      <input
                        className={inputCls}
                        value={editing.contact ?? ""}
                        onChange={(e) =>
                          setEditing({ ...editing, contact: e.target.value })
                        }
                      />
                    </td>
                    <td className="px-6 py-2 text-right tabular-nums text-slate-500">
                      {c.specifications_count}
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
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditing(null)}
                        >
                          Отмена
                        </Button>
                      </div>
                    </td>
                  </tr>
                ) : (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <td className="px-6 py-3 font-medium">{c.name}</td>
                    <td className="px-6 py-3 text-slate-600">{c.inn ?? "—"}</td>
                    <td className="px-6 py-3 text-slate-600">{c.contact ?? "—"}</td>
                    <td className="px-6 py-3 text-right tabular-nums text-slate-500">
                      {c.specifications_count}
                    </td>
                    <td className="px-6 py-3 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditing(c)}
                        >
                          Изменить
                        </Button>
                        <Button
                          size="sm"
                          variant="danger-ghost"
                          onClick={() => handleDelete(c)}
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

const inputCls =
  "w-full rounded border border-slate-300 px-2 py-1 text-sm";

function Field({
  label,
  value,
  onChange,
  required,
  wide,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  wide?: boolean;
}) {
  return (
    <label className={"flex flex-col gap-1 " + (wide ? "min-w-64 flex-1" : "")}>
      <span className="text-xs font-medium text-slate-500">{label}</span>
      <input
        className={inputCls}
        value={value}
        required={required}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
