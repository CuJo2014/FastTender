// Типы зеркалят Pydantic-схемы бэкенда (src/fasttender/schemas/*.py).
// Меняешь схему на бэке — обнови здесь.

export type SpecificationStatus =
  | "uploaded"
  | "parsing"
  | "parse_failed"
  | "parsed"
  | "matching"
  | "match_failed"
  | "matched"
  | "reviewing"
  | "verified"
  | "exported"
  | "cancelled";

export type DataSourceType =
  | "company_catalog"
  | "supplier_pricelist"
  | "web_scraper";

export type MatchType =
  | "exact_article"
  | "fuzzy_article"
  | "lexical"
  | "semantic"
  | "hybrid";

export type VerificationDecision =
  | "confirmed"
  | "rejected"
  | "not_found"
  | "new_item_requested";

// --- Specifications ---

export interface SpecificationCounts {
  items_total: number;
  items_matched_high: number;
  items_matched_medium: number;
  items_not_found: number;
  items_verified: number;
  items_pending: number;
}

export interface SpecificationRead {
  id: string;
  source_filename: string;
  client_name: string | null;
  status: SpecificationStatus;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  counts: SpecificationCounts;
}

export interface SpecificationUploadResponse {
  spec_id: string;
  status: SpecificationStatus;
  filename: string;
  created_at: string;
}

export interface CandidateExplanation {
  article_match: string;
  article_similarity: number;
  lexical_score: number;
  semantic_similarity: number;
  brand_match: boolean;
  unit_match: boolean;
  final_score: number;
  human_readable: string;
  levels_hit: MatchType[];
}

export interface LinkedCatalogItemRead {
  item_id: string;
  code_1c: string | null;
  article: string | null;
  name: string;
  manufacturer: string | null;
}

export interface CandidateRead {
  item_id: string;
  source_id: string;
  source_type: DataSourceType;
  article: string | null;
  code_1c: string | null;
  supplier_sku: string | null;
  linked_catalog: LinkedCatalogItemRead | null;
  catalog_link_source: "auto" | "manual" | null;
  name: string;
  manufacturer: string | null;
  category_path: string | null;
  price: string | null; // Decimal сериализуется в строку
  currency: string | null;
  unit: string | null;
  in_stock: boolean;
  confidence: number;
  match_type: MatchType;
  rank: number;
  explanation: CandidateExplanation;
}

export interface VerificationRead {
  decision: VerificationDecision;
  chosen_item_id: string | null;
  decided_by: string | null;
  notes: string | null;
  decided_at: string;
}

export interface SpecItemRead {
  id: string;
  line_number: number;
  name_raw: string;
  article_raw: string | null;
  manufacturer_raw: string | null;
  unit_raw: string | null;
  quantity: string | null;
  price_raw: string | null;
  currency_raw: string | null;
  notes: string | null;
  name_normalized: string | null;
  article_normalized: string | null;
  unit_normalized: string | null;
  candidates_catalog: CandidateRead[];
  candidates_suppliers: CandidateRead[];
  verification: VerificationRead | null;
}

export interface PaginatedSpecItems {
  items: SpecItemRead[];
  total: number;
  page: number;
  page_size: number;
}

// --- Verification ---

export interface VerifyRequest {
  decision: VerificationDecision;
  chosen_item_id?: string | null;
  notes?: string | null;
  decided_by?: string | null;
}

export interface VerifyResponse {
  spec_item_id: string;
  decision: VerificationDecision;
  chosen_item_id: string | null;
  decided_by: string | null;
  notes: string | null;
  decided_at: string;
}

export interface AutoConfirmRequest {
  min_confidence?: number | null;
  decided_by?: string | null;
  only_unverified?: boolean;
}

export interface AutoConfirmResponse {
  confirmed_count: number;
  skipped_already_verified: number;
  skipped_below_threshold: number;
  threshold_used: number;
}

// --- Import (catalog + pricelist) ---

export type ImportMode = "replace" | "merge";

export interface DuplicateArticle {
  article: string;
  first_line: number;
  duplicate_lines: number[];
}

export interface RowError {
  line_number: number;
  reason: string;
  raw: Record<string, string | null>;
}

export interface ImportReport {
  source_id: string;
  source_name: string;
  mode: ImportMode;
  rows_total: number;
  rows_imported: number;
  rows_updated: number;
  rows_deactivated: number;
  rows_skipped: number;
  errors: RowError[];
  duplicates: DuplicateArticle[];
}

export interface CatalogInfo {
  items_count: number;
  last_synced_at: string | null;
  created_at: string | null;
}

export interface CatalogSearchResult {
  item_id: string;
  code_1c: string | null;
  supplier_sku: string | null;
  article: string | null;
  name: string;
  manufacturer: string | null;
  category_path: string | null;
  price: number | null;
  currency: string | null;
  unit: string | null;
  source_type: "company_catalog" | "supplier_pricelist";
  source_label: string;
}

// --- Suppliers ---

export interface SupplierTransformations {
  brand_regex?: string | null;
  vat_included?: boolean;
  vat_rate?: number;
  default_unit?: string | null;
  default_currency?: string | null;
  manufacturer?: string | null;
}

export interface SupplierCreate {
  name: string;
  contact_email?: string | null;
  prefix?: string | null;
  transformations?: SupplierTransformations | null;
  meta?: Record<string, unknown>;
}

export interface SupplierUpdate {
  name?: string | null;
  contact_email?: string | null;
  prefix?: string | null;
  transformations?: SupplierTransformations | null;
  meta?: Record<string, unknown> | null;
}

export interface SupplierRead {
  id: string;
  name: string;
  contact_email: string | null;
  prefix: string | null;
  meta: Record<string, unknown>;
  transformations: SupplierTransformations | null;
  created_at: string;
  pricelist_last_synced_at: string | null;
  pricelist_items_count: number;
}

export interface PricelistSourceRead {
  id: string;
  name: string;
  supplier_id: string;
  status: "active" | "paused" | "error";
  config: Record<string, unknown>;
  last_synced_at: string | null;
  created_at: string;
}
