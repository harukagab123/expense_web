import { apiConfig } from "./config";
import type {
  AttentionCountResponse,
  AttentionListResponse,
  CategoryCatalogResponse,
  FileManagerTree,
  SearchResponse,
  SortBy,
  SortDirection,
  StatementDetection,
  StatementAnalysisResponse,
  StatementLookupResponse,
  StatementUpdate,
  StatementTransaction,
  TransactionTypeBulkPayload,
  TransactionTypeBulkUpdateResponse,
  TransactionTypeClassificationRunResponse,
  TransactionTypePayload,
  TransactionCategorizationRunResponse,
  TransactionCategoryBulkPayload,
  TransactionCategoryBulkUpdateResponse,
  TransactionCategoryPayload,
  TransactionExtractionRunResponse,
  TransactionInclusionBulkPayload,
  TransactionInclusionBulkUpdateResponse,
  TransactionInclusionPayload,
  TransactionListResponse,
  TransactionNormalizationPayload,
  TransactionNormalizationRunResponse,
  TransactionPayload,
  TransactionReviewBulkPayload,
  TransactionReviewBulkUpdateResponse,
  TransactionReviewPayload,
  StoredFile,
  UploadBatchResponse,
} from "../types/fileManager";

type RequestOptions = RequestInit & {
  json?: unknown;
};

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  let body = options.body;

  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }

  const response = await fetch(`${apiConfig.baseUrl}${path}`, {
    ...options,
    headers,
    body,
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new Error(formatApiError(data));
  }

  return data as T;
}

function formatApiError(data: unknown): string {
  if (!data || typeof data !== "object" || !("detail" in data)) {
    return "Request failed.";
  }

  const detail = (data as { detail: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return "";
      })
      .filter(Boolean);
    return messages.join(" ") || "Request failed.";
  }
  return "Request failed.";
}

export async function getFileManagerTree(params: {
  search?: string;
  sortBy: SortBy;
  sortDirection: SortDirection;
}): Promise<FileManagerTree> {
  const query = new URLSearchParams({
    search: params.search ?? "",
    sort_by: params.sortBy,
    sort_direction: params.sortDirection,
  });
  return requestJson<FileManagerTree>(`/api/file-manager/tree?${query.toString()}`);
}

export async function searchFileManager(queryText: string, signal?: AbortSignal): Promise<SearchResponse> {
  const query = new URLSearchParams({ query: queryText });
  return requestJson<SearchResponse>(`/api/file-manager/search?${query.toString()}`, { signal });
}

export async function getCategoryCatalog(): Promise<CategoryCatalogResponse> {
  return requestJson<CategoryCatalogResponse>("/api/categories/catalog");
}

export async function getAttention(limit = 100): Promise<AttentionListResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  return requestJson<AttentionListResponse>(`/api/attention?${query.toString()}`);
}

export async function getAttentionCount(): Promise<AttentionCountResponse> {
  return requestJson<AttentionCountResponse>("/api/attention/count");
}

export async function createFolder(name: string, parentFolderId: number | null) {
  return requestJson("/api/folders", {
    method: "POST",
    json: { name, parent_folder_id: parentFolderId },
  });
}

export async function updateFolder(
  folderId: number,
  payload: { name?: string; parent_folder_id?: number | null },
) {
  return requestJson(`/api/folders/${folderId}`, {
    method: "PATCH",
    json: payload,
  });
}

export async function deleteFolder(folderId: number) {
  await requestJson(`/api/folders/${folderId}`, { method: "DELETE" });
}

export async function uploadFiles(files: File[], folderId: number | null): Promise<UploadBatchResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  if (folderId !== null) {
    formData.append("folder_id", String(folderId));
  }

  return requestJson<UploadBatchResponse>("/api/files", {
    method: "POST",
    body: formData,
  });
}

export async function updateStoredFile(
  fileId: number,
  payload: { display_name?: string; folder_id?: number | null },
): Promise<StoredFile> {
  return requestJson<StoredFile>(`/api/files/${fileId}`, {
    method: "PATCH",
    json: payload,
  });
}

export async function deleteStoredFile(fileId: number) {
  await requestJson(`/api/files/${fileId}`, { method: "DELETE" });
}

export async function getStatementForFile(fileId: number, signal?: AbortSignal): Promise<StatementLookupResponse> {
  return requestJson<StatementLookupResponse>(`/api/files/${fileId}/statement`, { signal });
}

export async function detectStatement(fileId: number): Promise<StatementDetection> {
  return requestJson<StatementDetection>(`/api/files/${fileId}/detect-statement`, { method: "POST" });
}

export async function analyzeStatementFile(fileId: number): Promise<StatementAnalysisResponse> {
  return requestJson<StatementAnalysisResponse>(`/api/files/${fileId}/analyze`, { method: "POST" });
}

export async function updateStatementForFile(fileId: number, payload: StatementUpdate): Promise<StatementDetection> {
  return requestJson<StatementDetection>(`/api/files/${fileId}/statement`, {
    method: "PATCH",
    json: payload,
  });
}

export async function getTransactionsForStatement(
  statementId: number,
  signal?: AbortSignal,
): Promise<TransactionListResponse> {
  return requestJson<TransactionListResponse>(`/api/statements/${statementId}/transactions`, { signal });
}

export async function extractTransactions(statementId: number): Promise<TransactionExtractionRunResponse> {
  return requestJson<TransactionExtractionRunResponse>(`/api/statements/${statementId}/extract-transactions`, {
    method: "POST",
  });
}

export async function normalizeTransactions(statementId: number): Promise<TransactionNormalizationRunResponse> {
  return requestJson<TransactionNormalizationRunResponse>(`/api/statements/${statementId}/normalize-transactions`, {
    method: "POST",
  });
}

export async function classifyTransactionTypes(
  statementId: number,
): Promise<TransactionTypeClassificationRunResponse> {
  return requestJson<TransactionTypeClassificationRunResponse>(
    `/api/statements/${statementId}/classify-transaction-types`,
    { method: "POST" },
  );
}

export async function categorizeTransactions(statementId: number): Promise<TransactionCategorizationRunResponse> {
  return requestJson<TransactionCategorizationRunResponse>(`/api/statements/${statementId}/categorize-transactions`, {
    method: "POST",
  });
}

export async function createTransactionForStatement(
  statementId: number,
  payload: Required<TransactionPayload>,
): Promise<StatementTransaction> {
  return requestJson<StatementTransaction>(`/api/statements/${statementId}/transactions`, {
    method: "POST",
    json: payload,
  });
}

export async function updateTransaction(
  transactionId: number,
  payload: TransactionPayload,
): Promise<StatementTransaction> {
  return requestJson<StatementTransaction>(`/api/transactions/${transactionId}`, {
    method: "PATCH",
    json: payload,
  });
}

export async function updateTransactionNormalization(
  transactionId: number,
  payload: TransactionNormalizationPayload,
): Promise<StatementTransaction> {
  return requestJson<StatementTransaction>(`/api/transactions/${transactionId}/normalization`, {
    method: "PATCH",
    json: payload,
  });
}

export async function updateTransactionType(
  transactionId: number,
  payload: TransactionTypePayload,
): Promise<StatementTransaction> {
  return requestJson<StatementTransaction>(`/api/transactions/${transactionId}/type`, {
    method: "PATCH",
    json: payload,
  });
}

export async function bulkUpdateTransactionTypes(
  payload: TransactionTypeBulkPayload,
): Promise<TransactionTypeBulkUpdateResponse> {
  return requestJson<TransactionTypeBulkUpdateResponse>("/api/transactions/bulk-type", {
    method: "PATCH",
    json: payload,
  });
}

export async function updateTransactionCategory(
  transactionId: number,
  payload: TransactionCategoryPayload,
): Promise<StatementTransaction> {
  return requestJson<StatementTransaction>(`/api/transactions/${transactionId}/category`, {
    method: "PATCH",
    json: payload,
  });
}

export async function bulkUpdateTransactionCategories(
  payload: TransactionCategoryBulkPayload,
): Promise<TransactionCategoryBulkUpdateResponse> {
  return requestJson<TransactionCategoryBulkUpdateResponse>("/api/transactions/bulk-category", {
    method: "PATCH",
    json: payload,
  });
}

export async function updateTransactionInclusion(
  transactionId: number,
  payload: TransactionInclusionPayload,
): Promise<StatementTransaction> {
  return requestJson<StatementTransaction>(`/api/transactions/${transactionId}/inclusion`, {
    method: "PATCH",
    json: payload,
  });
}

export async function bulkUpdateTransactionInclusion(
  payload: TransactionInclusionBulkPayload,
): Promise<TransactionInclusionBulkUpdateResponse> {
  return requestJson<TransactionInclusionBulkUpdateResponse>("/api/transactions/bulk-inclusion", {
    method: "PATCH",
    json: payload,
  });
}

export async function updateTransactionReview(
  transactionId: number,
  payload: TransactionReviewPayload,
): Promise<StatementTransaction> {
  return requestJson<StatementTransaction>(`/api/transactions/${transactionId}/review`, {
    method: "PATCH",
    json: payload,
  });
}

export async function bulkUpdateTransactionReview(
  payload: TransactionReviewBulkPayload,
): Promise<TransactionReviewBulkUpdateResponse> {
  return requestJson<TransactionReviewBulkUpdateResponse>("/api/transactions/bulk-review", {
    method: "PATCH",
    json: payload,
  });
}

export async function excludeTransaction(transactionId: number): Promise<StatementTransaction> {
  return requestJson<StatementTransaction>(`/api/transactions/${transactionId}`, { method: "DELETE" });
}

export function fileDownloadUrl(fileId: number): string {
  return `${apiConfig.baseUrl}/api/files/${fileId}/download`;
}

export function filePreviewUrl(fileId: number): string {
  return `${apiConfig.baseUrl}/api/files/${fileId}/preview`;
}
