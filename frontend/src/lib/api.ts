// Тонкий обёрток над fetch для бэка FastAPI.
// База — /api/v1, dev-сервер Vite проксирует на http://127.0.0.1:8000.

import type {
  AutoConfirmRequest,
  AutoConfirmResponse,
  CatalogInfo,
  ImportMode,
  ImportReport,
  PaginatedSpecItems,
  PricelistSourceRead,
  SpecificationRead,
  SpecificationUploadResponse,
  SupplierCreate,
  SupplierRead,
  SupplierUpdate,
  VerifyRequest,
  VerifyResponse,
} from "../types/api";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const { json, headers, ...rest } = init ?? {};
  const finalInit: RequestInit = {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
  };
  if (json !== undefined) {
    finalInit.body = JSON.stringify(json);
  }

  const response = await fetch(`${BASE}${path}`, finalInit);
  if (!response.ok) {
    let detail: unknown = await response.text();
    try {
      detail = JSON.parse(detail as string);
    } catch {
      // оставляем как строку
    }
    throw new ApiError(response.status, detail);
  }

  // 204 / пустое тело
  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

// --- Specifications ---

export const api = {
  listSpecifications: () => request<SpecificationRead[]>("/specifications/"),

  getSpecification: (id: string) =>
    request<SpecificationRead>(`/specifications/${id}`),

  getSpecificationItems: (id: string, page = 1, pageSize = 50) =>
    request<PaginatedSpecItems>(
      `/specifications/${id}/items?page=${page}&page_size=${pageSize}`,
    ),

  uploadSpecification: async (file: File, clientName?: string) => {
    const form = new FormData();
    form.append("file", file);
    const url = clientName
      ? `/specifications/?client_name=${encodeURIComponent(clientName)}`
      : "/specifications/";
    const response = await fetch(`${BASE}${url}`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as SpecificationUploadResponse;
  },

  verifySpecItem: (
    specId: string,
    specItemId: string,
    payload: VerifyRequest,
  ) =>
    request<VerifyResponse>(
      `/specifications/${specId}/items/${specItemId}/verify`,
      { method: "POST", json: payload },
    ),

  autoConfirm: (specId: string, payload: AutoConfirmRequest = {}) =>
    request<AutoConfirmResponse>(
      `/specifications/${specId}/auto-confirm`,
      { method: "POST", json: payload },
    ),

  cancelSpecification: (specId: string, reason?: string) =>
    request<SpecificationRead>(
      `/specifications/${specId}/cancel`,
      { method: "POST", json: { reason: reason ?? null } },
    ),

  exportUrl: (specId: string, format: "xlsx" | "csv" = "xlsx") =>
    `${BASE}/specifications/${specId}/export?format=${format}`,

  // --- Catalog ---

  getCatalogInfo: () => request<CatalogInfo>("/catalog/info"),

  importCatalog: async (file: File, mode: ImportMode = "replace") => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(
      `${BASE}/catalog/import?mode=${mode}`,
      { method: "POST", body: form },
    );
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as ImportReport;
  },

  // --- Suppliers ---

  listSuppliers: () => request<SupplierRead[]>("/suppliers/"),

  createSupplier: (payload: SupplierCreate) =>
    request<SupplierRead>("/suppliers/", { method: "POST", json: payload }),

  updateSupplier: (supplierId: string, payload: SupplierUpdate) =>
    request<SupplierRead>(`/suppliers/${supplierId}`, {
      method: "PATCH",
      json: payload,
    }),

  getSupplierPricelist: (supplierId: string) =>
    request<PricelistSourceRead | null>(
      `/suppliers/${supplierId}/pricelist`,
    ),

  importSupplierPricelist: async (
    supplierId: string,
    file: File,
    mode: ImportMode = "replace",
  ) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(
      `${BASE}/suppliers/${supplierId}/pricelists/import?mode=${mode}`,
      { method: "POST", body: form },
    );
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as ImportReport;
  },
};
