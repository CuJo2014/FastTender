import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../lib/api";
import type { ImportMode, ImportReport } from "../types/api";
import { Button } from "./ui/Button";

interface Props {
  title: string;
  description?: string;
  uploadFn: (file: File, mode: ImportMode) => Promise<ImportReport>;
  invalidateKey?: unknown[];
  accept?: string;
}

const DEFAULT_ACCEPT = ".xlsx,.xlsm,.xls,.csv,.tsv";

export function ImportPanel({
  title,
  description,
  uploadFn,
  invalidateKey,
  accept = DEFAULT_ACCEPT,
}: Props) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<ImportMode>("replace");

  const mutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Файл не выбран");
      return uploadFn(file, mode);
    },
    onSuccess: () => {
      setFile(null);
      if (invalidateKey) {
        queryClient.invalidateQueries({ queryKey: invalidateKey });
      }
    },
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3">
        <div className="text-sm font-medium">{title}</div>
        {description && (
          <div className="text-xs text-slate-500">{description}</div>
        )}
      </div>

      <div className="space-y-3">
        <input
          type="file"
          accept={accept}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-slate-800"
        />

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1 text-sm">
            <input
              type="radio"
              name="mode"
              value="replace"
              checked={mode === "replace"}
              onChange={() => setMode("replace")}
            />
            Заменить (replace)
          </label>
          <label className="flex items-center gap-1 text-sm">
            <input
              type="radio"
              name="mode"
              value="merge"
              checked={mode === "merge"}
              onChange={() => setMode("merge")}
            />
            Дополнить (merge)
          </label>
        </div>

        <Button
          onClick={() => mutation.mutate()}
          disabled={!file || mutation.isPending}
        >
          {mutation.isPending ? "Загрузка…" : "Импортировать"}
        </Button>

        {mutation.isError && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            {mutation.error instanceof ApiError
              ? `Ошибка ${mutation.error.status}: ${JSON.stringify(mutation.error.detail)}`
              : (mutation.error as Error).message}
          </div>
        )}

        {mutation.data && <ReportSummary report={mutation.data} />}
      </div>
    </div>
  );
}

function ReportSummary({ report }: { report: ImportReport }) {
  return (
    <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-900">
      <div className="font-medium">{report.source_name}</div>
      <ul className="mt-1 grid grid-cols-2 gap-x-4 text-xs">
        <li>Всего строк: {report.rows_total}</li>
        <li>Добавлено: {report.rows_imported}</li>
        {report.rows_updated > 0 && <li>Обновлено: {report.rows_updated}</li>}
        {report.rows_deactivated > 0 && (
          <li>Деактивировано: {report.rows_deactivated}</li>
        )}
        {report.rows_skipped > 0 && <li>Пропущено: {report.rows_skipped}</li>}
      </ul>
      {report.duplicates.length > 0 && (
        <div className="mt-2 text-xs">
          Дубликаты артикулов ({report.duplicates.length}):{" "}
          {report.duplicates
            .slice(0, 5)
            .map((d) => d.article)
            .join(", ")}
          {report.duplicates.length > 5 && "…"}
        </div>
      )}
    </div>
  );
}
