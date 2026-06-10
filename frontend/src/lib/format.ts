import type { SpecificationStatus } from "../types/api";

export function formatConfidence(value: number): string {
  return (value * 100).toFixed(0) + "%";
}

export function confidenceTone(
  value: number,
  high = 0.9,
  min = 0.5,
): "success" | "warning" | "danger" {
  if (value >= high) return "success";
  if (value >= min) return "warning";
  return "danger";
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatPrice(value: string | null | undefined): string {
  if (!value) return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num.toLocaleString("ru-RU", { maximumFractionDigits: 4 });
}

/**
 * Количество без хвостовых нулей: `18.0000 → 18`, `147.4900 → 147,49`.
 * `toLocaleString` сам отбрасывает незначащие нули; держим до 4 знаков
 * (как в исходных данных спеки). null/пустое → «—».
 */
export function formatQuantity(
  value: string | number | null | undefined,
): string {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return num.toLocaleString("ru-RU", { maximumFractionDigits: 4 });
}

const STATUS_LABELS: Record<SpecificationStatus, string> = {
  uploaded: "Загружен",
  parsing: "Парсинг…",
  parse_failed: "Ошибка парсинга",
  parsed: "Распарсен",
  matching: "Матчинг…",
  match_failed: "Ошибка матчинга",
  matched: "На верификации",
  reviewing: "На верификации",
  verified: "Полностью верифицирован",
  exported: "Выгружен",
  cancelled: "Отменён",
};

export function statusLabel(status: SpecificationStatus): string {
  return STATUS_LABELS[status] ?? status;
}

const ACTIVE_STATUSES: ReadonlySet<SpecificationStatus> = new Set([
  "uploaded",
  "parsing",
  "matching",
]);

export function isInProgress(status: SpecificationStatus): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function statusTone(
  status: SpecificationStatus,
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (status === "verified" || status === "exported") {
    return "success"; // зелёный
  }
  if (status === "matched" || status === "reviewing") {
    return "warning"; // жёлтый — ждёт менеджера
  }
  if (status === "parse_failed" || status === "match_failed") {
    return "danger";
  }
  if (status === "cancelled") {
    return "neutral";
  }
  if (isInProgress(status)) return "info";
  return "neutral";
}
