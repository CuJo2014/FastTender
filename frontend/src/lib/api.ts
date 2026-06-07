// Тонкий обёрток над fetch для бэка FastAPI.
// База — /api/v1, dev-сервер Vite проксирует на http://127.0.0.1:8000.

import type {
  AutoConfirmRequest,
  AutoConfirmResponse,
  CatalogInfo,
  ClientCreate,
  ClientRead,
  TradingPlatformCreate,
  TradingPlatformRead,
  CatalogSearchResult,
  GoldRowCreate,
  GoldRowFromSpecItem,
  GoldRowRead,
  GoldRowUpdate,
  GoldLabelStatus,
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

  deleteSpecification: (specId: string) =>
    request<void>(`/specifications/${specId}`, { method: "DELETE" }),

  unverifySpecItem: (specId: string, specItemId: string) =>
    request<void>(
      `/specifications/${specId}/items/${specItemId}/verify`,
      { method: "DELETE" },
    ),

  updateSpecification: (
    specId: string,
    patch: {
      client_id?: string | null;
      client_name?: string | null;
      is_tp?: boolean;
      trading_platform_id?: string | null;
      spec_number?: string | null;
      spec_date?: string | null;
      delivery_date?: string | null;
    },
  ) =>
    request<SpecificationRead>(`/specifications/${specId}`, {
      method: "PATCH",
      json: patch,
    }),

  exportUrl: (specId: string, format: "xlsx" | "csv" = "xlsx") =>
    `${BASE}/specifications/${specId}/export?format=${format}`,

  // --- Clients ---

  listClients: (q?: string) =>
    request<ClientRead[]>(
      `/clients/${q ? `?q=${encodeURIComponent(q)}` : ""}`,
    ),

  createClient: (payload: ClientCreate) =>
    request<ClientRead>("/clients/", { method: "POST", json: payload }),

  updateClient: (id: string, payload: Partial<ClientCreate>) =>
    request<ClientRead>(`/clients/${id}`, { method: "PATCH", json: payload }),

  deleteClient: (id: string) =>
    request<void>(`/clients/${id}`, { method: "DELETE" }),

  // --- Trading platforms ---

  listPlatforms: (q?: string) =>
    request<TradingPlatformRead[]>(
      `/trading-platforms/${q ? `?q=${encodeURIComponent(q)}` : ""}`,
    ),

  createPlatform: (payload: TradingPlatformCreate) =>
    request<TradingPlatformRead>("/trading-platforms/", {
      method: "POST",
      json: payload,
    }),

  updatePlatform: (id: string, payload: Partial<TradingPlatformCreate>) =>
    request<TradingPlatformRead>(`/trading-platforms/${id}`, {
      method: "PATCH",
      json: payload,
    }),

  deletePlatform: (id: string) =>
    request<void>(`/trading-platforms/${id}`, { method: "DELETE" }),

  // --- Catalog ---

  getCatalogInfo: () => request<CatalogInfo>("/catalog/info"),

  searchCatalog: (q: string, limit = 20) =>
    request<CatalogSearchResult[]>(
      `/catalog/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

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

  // --- Gold dataset ---

  listGoldRows: (status?: GoldLabelStatus) =>
    request<GoldRowRead[]>(
      `/gold-rows/${status ? `?label_status=${encodeURIComponent(status)}` : ""}`,
    ),

  createGoldRow: (payload: GoldRowCreate) =>
    request<GoldRowRead>("/gold-rows/", { method: "POST", json: payload }),

  createGoldRowFromSpecItem: (payload: GoldRowFromSpecItem) =>
    request<GoldRowRead>("/gold-rows/from-spec-item", {
      method: "POST",
      json: payload,
    }),

  updateGoldRow: (id: string, payload: GoldRowUpdate) =>
    request<GoldRowRead>(`/gold-rows/${id}`, { method: "PATCH", json: payload }),

  deleteGoldRow: (id: string) =>
    request<void>(`/gold-rows/${id}`, { method: "DELETE" }),

  goldExportUrl: () => `${BASE}/gold-rows/export.xlsx`,

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
