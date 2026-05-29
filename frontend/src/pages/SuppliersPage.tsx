import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { SupplierRead } from "../types/api";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { ImportPanel } from "../components/ImportPanel";
import { formatDateTime } from "../lib/format";

export function SuppliersPage() {
  return (
    <div className="space-y-6">
      <SupplierList />
      <NewSupplierForm />
    </div>
  );
}

function SupplierList() {
  const { data, isLoading } = useQuery({
    queryKey: ["suppliers"],
    queryFn: api.listSuppliers,
  });

  return (
    <Card>
      <CardHeader
        title="Поставщики"
        description="Управление прайс-листами"
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
  return (
    <li className="rounded-lg border border-slate-200 p-4">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <div className="font-medium">{supplier.name}</div>
          {supplier.contact_email && (
            <div className="text-xs text-slate-500">{supplier.contact_email}</div>
          )}
          <div className="text-xs text-slate-400">
            Создан: {formatDateTime(supplier.created_at)}
          </div>
        </div>
      </div>

      <ImportPanel
        title="Импорт прайса этого поставщика"
        description="Шаблон колонок выучится автоматически при первой загрузке"
        uploadFn={(file, mode) =>
          api.importSupplierPricelist(supplier.id, file, mode)
        }
      />
    </li>
  );
}

function NewSupplierForm() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      api.createSupplier({
        name: name.trim(),
        contact_email: email.trim() || null,
      }),
    onSuccess: () => {
      setName("");
      setEmail("");
      queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
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

          <Button type="submit" disabled={!name.trim() || mutation.isPending}>
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
