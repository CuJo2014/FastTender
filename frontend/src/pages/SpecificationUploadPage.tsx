import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";

const ACCEPT = ".xlsx,.xlsm,.xls,.csv,.tsv";

export function SpecificationUploadPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [clientId, setClientId] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Файл не выбран");
      return api.uploadSpecification(file, { clientId });
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["specifications"] });
      navigate(`/specifications/${data.spec_id}`);
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    upload.mutate();
  };

  return (
    <Card>
      <CardHeader
        title="Загрузка спецификации"
        description="XLSX, XLSM, XLS, CSV или TSV. После загрузки запустится автоматическая обработка."
        actions={
          <Link to="/specifications">
            <Button variant="ghost">← К списку</Button>
          </Link>
        }
      />
      <CardBody>
        <form onSubmit={handleSubmit} className="space-y-4">
          <label
            className={
              "flex h-48 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed " +
              (dragOver
                ? "border-blue-500 bg-blue-50"
                : "border-slate-300 hover:border-slate-400")
            }
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const dropped = e.dataTransfer.files[0];
              if (dropped) setFile(dropped);
            }}
          >
            <input
              type="file"
              className="hidden"
              accept={ACCEPT}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            {file ? (
              <>
                <div className="text-base font-medium text-slate-900">
                  {file.name}
                </div>
                <div className="text-sm text-slate-500">
                  {(file.size / 1024).toFixed(1)} КБ — кликните, чтобы заменить
                </div>
              </>
            ) : (
              <>
                <div className="text-base font-medium text-slate-700">
                  Перетащите файл сюда или кликните для выбора
                </div>
                <div className="text-sm text-slate-500">
                  Допустимые форматы: {ACCEPT.replace(/\./g, "").replace(/,/g, ", ")}
                </div>
              </>
            )}
          </label>

          <div>
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Клиент <span className="text-slate-400">(опционально)</span>
            </label>
            <ClientSelect value={clientId} onChange={setClientId} />
          </div>

          {upload.isError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {upload.error instanceof ApiError
                ? `Ошибка ${upload.error.status}: ${
                    typeof upload.error.detail === "object" &&
                    upload.error.detail &&
                    "message" in upload.error.detail
                      ? String((upload.error.detail as { message: unknown }).message)
                      : JSON.stringify(upload.error.detail)
                  }`
                : (upload.error as Error)?.message}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Link to="/specifications">
              <Button type="button" variant="outline">
                Отмена
              </Button>
            </Link>
            <Button type="submit" disabled={!file || upload.isPending}>
              {upload.isPending ? "Загрузка…" : "Загрузить и запустить"}
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

/**
 * Контролируемый выбор клиента: из справочника или «создать нового».
 * Аналог ClientPicker из формы спеки, но хранит выбор в локальном состоянии
 * (спеки ещё нет — id уйдёт в запрос загрузки).
 */
function ClientSelect({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (clientId: string | null) => void;
}) {
  const qc = useQueryClient();
  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => api.listClients(),
  });

  const createMut = useMutation({
    mutationFn: (name: string) => api.createClient({ name }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["clients"] });
      onChange(c.id);
    },
  });

  const handleChange = (v: string) => {
    if (v === "__new__") {
      const name = window.prompt("Название нового клиента:")?.trim();
      if (name) createMut.mutate(name);
      return;
    }
    onChange(v || null);
  };

  return (
    <select
      value={value ?? ""}
      disabled={createMut.isPending}
      onChange={(e) => handleChange(e.target.value)}
      className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
    >
      <option value="">— не выбран —</option>
      {(clients ?? []).map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
      <option value="__new__">+ Создать нового…</option>
    </select>
  );
}
