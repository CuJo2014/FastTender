import { useState, type FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";

const ACCEPT = ".xlsx,.xlsm,.xls,.csv,.tsv";

export function SpecificationUploadPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [clientName, setClientName] = useState("");
  const [dragOver, setDragOver] = useState(false);

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Файл не выбран");
      return api.uploadSpecification(file, clientName.trim() || undefined);
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
              Имя клиента <span className="text-slate-400">(опционально)</span>
            </label>
            <input
              type="text"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              placeholder="ООО Ромашка"
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
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
