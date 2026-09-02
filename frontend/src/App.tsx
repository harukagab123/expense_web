import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import "./App.css";
import {
  ApiRequestError,
  analyzeStatementFile,
  bulkUpdateTransactionReview,
  createTransactionForStatement,
  createFolder,
  confirmStatementTerm,
  deleteCategoryRule,
  deleteFolder,
  deleteStoredFile,
  excludeTransaction,
  expenseSummaryExportUrl,
  createMaintenanceBackup,
  exportDiagnosticBundle,
  fileDownloadUrl,
  filePreviewUrl,
  getAttention,
  getAttentionCount,
  getCategoryCatalog,
  getCategoryRules,
  getExpenseSummary,
  getMaintenanceStatus,
  getFileManagerTree,
  getStatementForFile,
  getStatementTerms,
  getTransactionsForStatement,
  searchFileManager,
  openBackupFolder,
  restoreMaintenanceBackup,
  updateFolder,
  updateCategoryRule,
  updateStatementForFile,
  updateStoredFile,
  updateTransaction,
  updateTransactionCategory,
  updateTransactionInclusion,
  updateTransactionNormalization,
  uploadFiles,
} from "./api/fileManager";
import type {
  AnalysisStep,
  AttentionItem,
  AttentionListResponse,
  FileManagerTree,
  FolderNode,
  SearchResult,
  SelectedItem,
  SortBy,
  SortDirection,
  StatementDetection,
  StatementUpdate,
  StatementTransaction,
  StatementTerm,
  StoredFile,
  CategoryMainValue,
  CategoryCatalogResponse,
  CategoryRule,
  CategorySubcategoryValue,
  TransactionDirection,
  TransactionExtraction,
  TransactionCategoryPayload,
  TransactionInclusionPayload,
  TransactionNormalizationPayload,
  TransactionPayload,
  TransactionReviewBulkPayload,
  TransactionTypeValue,
  ExpenseSummary,
  SummaryGroup,
  SummarySubcategory,
  SummaryTransaction,
  MaintenanceStatus,
} from "./types/fileManager";

type MoveDialogState =
  | { type: "folder"; id: number; name: string }
  | { type: "file"; id: number; name: string }
  | null;

type NameDialogState =
  | { type: "create-folder"; title: string; label: string; initialValue: string }
  | { type: "rename-folder"; id: number; title: string; label: string; initialValue: string }
  | { type: "rename-file"; id: number; title: string; label: string; initialValue: string }
  | null;

type ConfirmDialogState =
  | { type: "folder"; id: number; name: string }
  | { type: "file"; id: number; name: string }
  | null;

type AttentionFocusTarget = {
  attentionId: string;
  fileId: number;
  statementId: number | null;
  transactionId: number | null;
  targetSection: "statement" | "transaction";
  targetField: string | null;
  requestedAt: number;
};

type ActiveAttentionFocus = AttentionFocusTarget & {
  softened: boolean;
};

type StatementEditValues = {
  document_type: string;
  institution: string;
  product_name: string;
  account_type: string;
  account_last_four: string;
  statement_start_date: string;
  statement_end_date: string;
};

type TransactionSortBy =
  | "source_order"
  | "normalized_name"
  | "main_category"
  | "subcategory"
  | "transaction_date"
  | "amount";

type TransactionFormValues = {
  transaction_date: string;
  transaction_detail: string;
  amount: string;
  direction: TransactionDirection;
};

type InlineTransactionEditValues = TransactionFormValues & {
  normalized_name: string;
  main_category: CategoryMainValue;
  subcategory: CategorySubcategoryValue;
  use_for_future: boolean;
};

type CategoryOption = {
  value: CategoryMainValue;
  label: string;
  subcategories: Array<{ value: CategorySubcategoryValue; label: string }>;
};

type TransactionDialogState = { mode: "add" } | null;

type NormalizationFilter = "all" | "normalized" | "needs_review" | "user_edited" | "unresolved";

type CategoryFilter =
  | "all"
  | "auto"
  | "home"
  | "business"
  | "needs_review"
  | "not_applicable";

type InclusionFilter = "all" | "included" | "excluded" | "needs_review" | "reviewed";

type AppView = "files" | "summary" | "maintenance";
type SummaryMode = "tax_year" | "custom";
type SummarySortBy = "date" | "name" | "amount" | "source";
type SummaryDrillDown =
  | { type: "subcategory"; group: SummaryGroup; subcategory: SummarySubcategory }
  | { type: "review"; transactions: SummaryTransaction[] }
  | null;

type CategoryFormValues = {
  main_category: CategoryMainValue;
  subcategory: CategorySubcategoryValue;
  use_for_future: boolean;
};

const emptyTree: FileManagerTree = {
  type: "root",
  name: "My Files",
  folders: [],
  files: [],
};

const emptyAttention: AttentionListResponse = {
  total: 0,
  blocking_total: 0,
  review_total: 0,
  ready_for_summary: true,
  items: [],
};

const analyzeStepLabels: Array<{ key: string; label: string }> = [
  { key: "statement_detection", label: "Statement detection" },
  { key: "transaction_extraction", label: "Transaction extraction" },
  { key: "transaction_normalization", label: "Normalize transaction names" },
  { key: "transaction_type_classification", label: "Classify transaction types" },
  { key: "transaction_categorization", label: "Categorize eligible transactions" },
  { key: "review_notification_refresh", label: "Refresh review notifications" },
  { key: "source_file_retention", label: "Apply source file retention" },
];

function initialAnalyzeSteps(): AnalysisStep[] {
  return analyzeStepLabels.map((step, index) => ({
    ...step,
    status: index === 0 ? "RUNNING" : "PENDING",
    message: null,
  }));
}

function analysisStepMarker(status: AnalysisStep["status"]): string {
  if (status === "COMPLETED") {
    return "✓";
  }
  if (status === "RUNNING") {
    return "→";
  }
  if (status === "FAILED") {
    return "!";
  }
  if (status === "SKIPPED") {
    return "-";
  }
  return "○";
}

const sortOptions: Array<{ value: SortBy; label: string }> = [
  { value: "name", label: "Name" },
  { value: "created_at", label: "Date Created" },
  { value: "updated_at", label: "Date Modified" },
  { value: "file_size", label: "File Size" },
];

const documentTypeLabels: Record<string, string> = {
  BANK_STATEMENT: "Bank Statement",
  CREDIT_CARD_STATEMENT: "Credit Card Statement",
  PAYMENT_ACCOUNT_STATEMENT: "Payment Account Statement",
  OTHER_DOCUMENT: "Other Document",
  UNKNOWN: "Unknown",
};

const institutionLabels: Record<string, string> = {
  CHASE: "Chase",
  CAPITAL_ONE: "Capital One",
  AMEX: "American Express",
  PAYPAL: "PayPal",
  TJX: "TJX / TJ Maxx",
  AMAZON: "Amazon",
  OTHER_BANK: "Other Bank",
  UNKNOWN: "Unknown",
};

const accountTypeLabels: Record<string, string> = {
  CHECKING: "Checking",
  SAVINGS: "Savings",
  CREDIT_CARD: "Credit Card",
  PAYMENT_ACCOUNT: "Payment Account",
  OTHER: "Other",
  UNKNOWN: "Unknown",
};

const detectionStatusLabels: Record<string, string> = {
  NOT_ANALYZED: "Not Analyzed",
  ANALYZING: "Analyzing",
  DETECTED: "Detected",
  NEEDS_REVIEW: "Needs Review",
  NOT_A_STATEMENT: "Not a Statement",
  FAILED: "Failed",
};

const extractionStatusLabels: Record<string, string> = {
  NOT_EXTRACTED: "Not Extracted",
  EXTRACTING: "Extracting",
  EXTRACTED: "Extracted",
  NEEDS_REVIEW: "Needs Review",
  FAILED: "Failed",
  UNSUPPORTED: "Unsupported",
};

const normalizationStatusLabels: Record<string, string> = {
  NOT_NORMALIZED: "Not Normalized",
  NORMALIZED: "Normalized",
  NEEDS_REVIEW: "Needs Review",
  USER_CONFIRMED: "User Confirmed",
};

const categoryLabels: Record<string, string> = {
  AUTO_EXPENSE: "AUTO EXPENSE",
  BUSINESS_USE_OF_HOME: "BUSINESS USE OF HOME",
  PROFIT_LOSS_BUSINESS: "PROFIT OR LOSS FROM BUSINESS",
};

const subcategoryLabels: Record<string, string> = {
  AUTO_GAS: "Gas",
  AUTO_INSURANCE: "Insurance",
  AUTO_MAINTENANCE: "Car Maintenance",
  AUTO_PARKING: "Parking Fee",
  AUTO_TIRES: "Tires",
  AUTO_TOLLS: "Tolls",
  AUTO_CAR_PAYMENT: "Car Payment",
  HOME_INSURANCE: "Insurance",
  HOME_RENT: "Rent",
  HOME_REPAIRS_MAINTENANCE: "Repairs and Maintenance",
  HOME_UTILITIES: "Utilities",
  HOME_TELECOM_INTERNET: "Telecom/Internet",
  HOME_OTHER_EXPENSE: "Other Expense",
  BUSINESS_MATERIALS: "Materials",
  BUSINESS_ADVERTISING: "Advertising",
  BUSINESS_INTEREST_OTHER: "Interest - Other",
  BUSINESS_LEGAL_PROFESSIONAL: "Legal and Professional Services",
  BUSINESS_OFFICE_EXPENSE: "Office Expense",
  BUSINESS_TRAVEL: "Travel",
  BUSINESS_TOTAL_MEALS: "Total Meals",
  BUSINESS_TRANSPORTATION: "Transportation",
  BUSINESS_GOVERNMENT: "Government",
  BUSINESS_DONATIONS: "Donations",
  BUSINESS_BANK_MEMBERSHIP: "Bank Membership",
  BUSINESS_MEDICAL: "Medical",
  BUSINESS_EDUCATION_LEARNING: "Education & Learning",
  BUSINESS_OTHER_SUPPLIES: "Other Supplies",
};

const categoryStatusLabels: Record<string, string> = {
  NOT_CATEGORIZED: "Not Categorized",
  CATEGORIZED: "Categorized",
  NEEDS_REVIEW: "Needs Review",
  USER_CONFIRMED: "User Confirmed",
  NOT_APPLICABLE: "Not Applicable",
};

const directionLabels: Record<string, string> = {
  INFLOW: "Inflow",
  OUTFLOW: "Outflow",
  UNKNOWN: "Unknown",
};

const transactionDirectionOptions: Array<{ value: TransactionDirection; label: string }> = [
  { value: "OUTFLOW", label: "Outflow" },
  { value: "INFLOW", label: "Inflow" },
  { value: "UNKNOWN", label: "Unknown" },
];

const normalizationFilterOptions: Array<{ value: NormalizationFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "normalized", label: "Normalized" },
  { value: "needs_review", label: "Needs Review" },
  { value: "user_edited", label: "User Edited" },
  { value: "unresolved", label: "Unresolved" },
];

const transactionTypeValues: TransactionTypeValue[] = [
  "EXPENSE",
  "INCOME",
  "TRANSFER",
  "CREDIT_CARD_PAYMENT",
  "REFUND",
  "ATM_CASH_WITHDRAWAL",
  "CHECK",
  "BANK_FEE",
  "INTEREST",
  "OTHER",
  "UNKNOWN",
];

const categoryFilterOptions: Array<{ value: CategoryFilter; label: string }> = [
  { value: "all", label: "All Categories" },
  { value: "auto", label: "Auto Expense" },
  { value: "home", label: "Business Use of Home" },
  { value: "business", label: "Profit or Loss From Business" },
  { value: "needs_review", label: "Needs Review" },
  { value: "not_applicable", label: "Not Applicable" },
];

const inclusionFilterOptions: Array<{ value: InclusionFilter; label: string }> = [
  { value: "all", label: "All Selections" },
  { value: "included", label: "Included" },
  { value: "excluded", label: "Excluded" },
  { value: "needs_review", label: "Needs Review" },
  { value: "reviewed", label: "Reviewed" },
];

const documentTypeOptions = optionsFromLabels(documentTypeLabels);
const institutionOptions = optionsFromLabels(institutionLabels);
const accountTypeOptions = optionsFromLabels(accountTypeLabels);

function optionsFromLabels(labels: Record<string, string>): Array<{ value: string; label: string }> {
  return Object.entries(labels).map(([value, label]) => ({ value, label }));
}

function formatBytes(bytes: number): string {
  if (bytes === 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDateOnly(value: string | null): string {
  if (!value) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
  }).format(new Date(`${value}T00:00:00`));
}

function formatDateRange(startDate: string | null, endDate: string | null): string {
  if (!startDate && !endDate) {
    return "Unknown";
  }
  return `${formatDateOnly(startDate)} to ${formatDateOnly(endDate)}`;
}

function labelFor(labels: Record<string, string>, value: string | null | undefined): string {
  if (!value) {
    return "Unknown";
  }
  return labels[value] ?? value.replaceAll("_", " ").toLowerCase();
}

function formatConfidence(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "0%";
  }
  return `${Math.round(value * 100)}%`;
}

function transactionNormalizationStatus(transaction: StatementTransaction): string {
  return transaction.normalization_status ?? "NOT_NORMALIZED";
}

function transactionNormalizationSource(transaction: StatementTransaction): string {
  return transaction.normalization_source ?? "UNRESOLVED";
}

function transactionNormalizationConfidence(transaction: StatementTransaction): number {
  return Number.isFinite(transaction.normalization_confidence) ? transaction.normalization_confidence : 0;
}

function isTransactionTypeValue(value: string | null | undefined): value is TransactionTypeValue {
  return transactionTypeValues.some((type) => type === value);
}

function transactionTypeValue(transaction: StatementTransaction): TransactionTypeValue {
  const value = transaction.transaction_type ?? "UNKNOWN";
  return isTransactionTypeValue(value) ? value : "UNKNOWN";
}

function transactionSuggestedInclude(transaction: StatementTransaction): string {
  return transaction.suggested_include ?? "REVIEW";
}

function isCategoryMainValue(value: string | null | undefined): value is CategoryMainValue {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(categoryLabels, value);
}

function isCategorySubcategoryValue(value: string | null | undefined): value is CategorySubcategoryValue {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(subcategoryLabels, value);
}

function categoryOptionsFromCatalog(catalog: CategoryCatalogResponse): CategoryOption[] {
  return catalog.categories.flatMap((category) => {
    if (!isCategoryMainValue(category.id)) {
      return [];
    }
    return [{
      value: category.id,
      label: category.label,
      subcategories: category.subcategories.flatMap((subcategory) =>
        isCategorySubcategoryValue(subcategory.id)
          ? [{ value: subcategory.id, label: subcategory.label }]
          : [],
      ),
    }];
  });
}

function subcategoryOptionsFor(
  categoryOptions: CategoryOption[],
  mainCategory: CategoryMainValue,
): Array<{ value: CategorySubcategoryValue; label: string }> {
  return categoryOptions.find((option) => option.value === mainCategory)?.subcategories ?? [];
}

function defaultSubcategoryFor(
  categoryOptions: CategoryOption[],
  mainCategory: CategoryMainValue,
): CategorySubcategoryValue {
  return subcategoryOptionsFor(categoryOptions, mainCategory)[0]?.value ?? "BUSINESS_OTHER_SUPPLIES";
}

function categoryStatus(transaction: StatementTransaction): string {
  return transaction.category_status ?? "NOT_CATEGORIZED";
}

function categorySource(transaction: StatementTransaction): string {
  return transaction.category_source ?? "UNRESOLVED";
}

function categoryConfidence(transaction: StatementTransaction): number {
  return Number.isFinite(transaction.category_confidence) ? transaction.category_confidence : 0;
}

function categoryNeedsReview(transaction: StatementTransaction): boolean {
  return categoryStatus(transaction) === "NEEDS_REVIEW";
}

function categoryMainValue(transaction: StatementTransaction): CategoryMainValue | null {
  const value = transaction.main_category;
  return isCategoryMainValue(value) ? value : null;
}

function categorySubcategoryValue(transaction: StatementTransaction): CategorySubcategoryValue | null {
  const value = transaction.subcategory;
  return isCategorySubcategoryValue(value) ? value : null;
}

function categoryPairLabel(transaction: StatementTransaction): string {
  const mainCategory = categoryMainValue(transaction);
  const subcategory = categorySubcategoryValue(transaction);
  if (categoryStatus(transaction) === "NOT_APPLICABLE") {
    return "Not Applicable";
  }
  if (!mainCategory || !subcategory) {
    return "Needs Review";
  }
  return `${labelFor(categoryLabels, mainCategory)} / ${labelFor(subcategoryLabels, subcategory)}`;
}

function transactionMatchesCategoryFilter(transaction: StatementTransaction, filter: CategoryFilter): boolean {
  const mainCategory = categoryMainValue(transaction);
  const status = categoryStatus(transaction);
  if (filter === "all") {
    return true;
  }
  if (filter === "auto") {
    return mainCategory === "AUTO_EXPENSE";
  }
  if (filter === "home") {
    return mainCategory === "BUSINESS_USE_OF_HOME";
  }
  if (filter === "business") {
    return mainCategory === "PROFIT_LOSS_BUSINESS";
  }
  if (filter === "needs_review") {
    return status === "NEEDS_REVIEW";
  }
  return status === "NOT_APPLICABLE";
}

function validateCategoryForm(values: CategoryFormValues, categoryOptions: CategoryOption[]): string {
  if (!isCategoryMainValue(values.main_category)) {
    return "Main category is required.";
  }
  if (!subcategoryOptionsFor(categoryOptions, values.main_category).some((option) => option.value === values.subcategory)) {
    return "Subcategory is not valid for the selected main category.";
  }
  return "";
}

function transactionIncluded(transaction: StatementTransaction): boolean {
  return transaction.include_in_expenses === true;
}

function transactionReviewStatus(transaction: StatementTransaction): string {
  return transaction.review_status ?? "PENDING";
}

function transactionNeedsPhase8Review(transaction: StatementTransaction): boolean {
  if (transactionReviewStatus(transaction) === "REVIEWED") {
    return false;
  }
  return (
    transactionReviewStatus(transaction) === "NEEDS_REVIEW" ||
    transaction.needs_review ||
    transactionNormalizationStatus(transaction) === "NEEDS_REVIEW" ||
    transactionSuggestedInclude(transaction) === "REVIEW" ||
    categoryStatus(transaction) === "NEEDS_REVIEW" ||
    categoryStatus(transaction) === "NOT_CATEGORIZED"
  );
}

function transactionMatchesInclusionFilter(transaction: StatementTransaction, filter: InclusionFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "included") {
    return transactionIncluded(transaction);
  }
  if (filter === "excluded") {
    return !transactionIncluded(transaction);
  }
  if (filter === "needs_review") {
    return transactionNeedsPhase8Review(transaction);
  }
  return transactionReviewStatus(transaction) === "REVIEWED";
}

function transactionInclusionWarning(transaction: StatementTransaction): string | null {
  const type = transactionTypeValue(transaction);
  const suggestion = transactionSuggestedInclude(transaction);
  const included = transactionIncluded(transaction);
  if (
    included &&
    ["INCOME", "TRANSFER", "CREDIT_CARD_PAYMENT", "REFUND", "ATM_CASH_WITHDRAWAL", "CHECK", "OTHER"].includes(type)
  ) {
    return "Selected - transaction type is excluded from Summary";
  }
  if (included && type === "UNKNOWN" && !transaction.user_edited_category) {
    return "Selected - resolve transaction type before Summary";
  }
  if (type === "CREDIT_CARD_PAYMENT") {
    return "Recommended Exclude - may duplicate card purchases";
  }
  if (["INCOME", "REFUND"].includes(type) || suggestion === "NO") {
    return "Recommended Exclude";
  }
  if (["TRANSFER", "ATM_CASH_WITHDRAWAL", "CHECK", "UNKNOWN"].includes(type) || suggestion === "REVIEW") {
    return "Recommended Review";
  }
  return null;
}

function moneyToCents(value: string | number | null): number {
  if (value === null) {
    return 0;
  }
  const match = String(value).trim().replaceAll(",", "").match(/^(-?)(\d+)(?:\.(\d{0,2}))?$/);
  if (!match) {
    return 0;
  }
  const cents = `${match[3] ?? ""}00`.slice(0, 2);
  const total = Number.parseInt(match[2], 10) * 100 + Number.parseInt(cents, 10);
  return match[1] === "-" ? -total : total;
}

function formatMoneyCents(cents: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
  }).format(cents / 100);
}

function selectedAmountCents(transactions: StatementTransaction[]): number {
  return transactions.reduce((total, transaction) => {
    if (!transactionIncluded(transaction)) {
      return total;
    }
    return total + moneyToCents(transaction.amount);
  }, 0);
}

function replaceTransactionInList(
  transactions: StatementTransaction[],
  updatedTransaction: StatementTransaction,
): StatementTransaction[] {
  return transactions.map((transaction) =>
    transaction.id === updatedTransaction.id ? updatedTransaction : transaction,
  );
}

function mergeUpdatedTransactions(
  transactions: StatementTransaction[],
  updatedTransactions: StatementTransaction[],
): StatementTransaction[] {
  const updates = new Map(updatedTransactions.map((transaction) => [transaction.id, transaction]));
  return transactions.map((transaction) => updates.get(transaction.id) ?? transaction);
}

function formatMoney(value: string | number | null): string {
  if (value === null) {
    return "Unknown";
  }
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return String(value);
  }
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
  }).format(numericValue);
}

function transactionToFormValues(transaction: StatementTransaction): TransactionFormValues {
  return {
    transaction_date: transaction.transaction_date,
    transaction_detail: transaction.transaction_detail,
    amount: String(transaction.amount),
    direction: (transaction.direction as TransactionDirection) || "UNKNOWN",
  };
}

function emptyTransactionFormValues(): TransactionFormValues {
  return {
    transaction_date: "",
    transaction_detail: "",
    amount: "",
    direction: "OUTFLOW",
  };
}

function validateTransactionForm(values: TransactionFormValues): string {
  if (!values.transaction_date) {
    return "Transaction date is required.";
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.transaction_date)) {
    return "Transaction date must use YYYY-MM-DD format.";
  }
  const parsedDate = new Date(`${values.transaction_date}T00:00:00`);
  if (Number.isNaN(parsedDate.getTime())) {
    return "Transaction date must be valid.";
  }
  if (!values.transaction_detail.trim()) {
    return "Transaction detail is required.";
  }
  if (!/^\d+(\.\d{1,2})?$/.test(values.amount.trim())) {
    return "Amount must be valid money, such as 100 or 100.00.";
  }
  if (!["INFLOW", "OUTFLOW", "UNKNOWN"].includes(values.direction)) {
    return "Direction must be Inflow, Outflow, or Unknown.";
  }
  return "";
}

function transactionPayloadFromValues(values: TransactionFormValues): Required<TransactionPayload> {
  return {
    transaction_date: values.transaction_date,
    transaction_detail: values.transaction_detail.trim(),
    amount: values.amount.trim(),
    direction: values.direction,
  };
}

function inlineEditValuesFromTransaction(
  transaction: StatementTransaction,
  categoryOptions: CategoryOption[],
): InlineTransactionEditValues {
  const mainCategory = categoryMainValue(transaction) ?? "PROFIT_LOSS_BUSINESS";
  const subcategory = categorySubcategoryValue(transaction);
  const validSubcategories = subcategoryOptionsFor(categoryOptions, mainCategory);
  return {
    ...transactionToFormValues(transaction),
    normalized_name: transaction.normalized_name ?? "",
    main_category: mainCategory,
    subcategory: subcategory && validSubcategories.some((option) => option.value === subcategory)
      ? subcategory
      : defaultSubcategoryFor(categoryOptions, mainCategory),
    use_for_future: false,
  };
}

function validateInlineTransactionEdit(
  values: InlineTransactionEditValues,
  transaction: StatementTransaction,
  categoryOptions: CategoryOption[],
): string {
  const transactionValidation = validateTransactionForm(values);
  if (transactionValidation) {
    return transactionValidation;
  }
  const initialValues = inlineEditValuesFromTransaction(transaction, categoryOptions);
  if (values.normalized_name !== initialValues.normalized_name && !values.normalized_name.trim()) {
    return "Name is required.";
  }
  return validateCategoryForm({ ...values, use_for_future: false }, categoryOptions);
}

function inlineTransactionEditIsDirty(
  transaction: StatementTransaction,
  values: InlineTransactionEditValues,
  categoryOptions: CategoryOption[],
): boolean {
  const initialValues = inlineEditValuesFromTransaction(transaction, categoryOptions);
  return (
    values.transaction_date !== initialValues.transaction_date ||
    values.transaction_detail !== initialValues.transaction_detail ||
    moneyToCents(values.amount) !== moneyToCents(initialValues.amount) ||
    values.direction !== initialValues.direction ||
    values.normalized_name !== initialValues.normalized_name ||
    values.main_category !== initialValues.main_category ||
    values.subcategory !== initialValues.subcategory ||
    values.use_for_future
  );
}

function categoryRuleConflict(error: unknown): { message: string; rule: CategoryRule } | null {
  if (!(error instanceof ApiRequestError) || error.status !== 409) {
    return null;
  }
  const data = error.data;
  if (!data || typeof data !== "object" || !("detail" in data)) {
    return null;
  }
  const detail = (data as { detail: unknown }).detail;
  if (!detail || typeof detail !== "object" || !("code" in detail) || !("rule" in detail)) {
    return null;
  }
  if ((detail as { code: unknown }).code !== "CATEGORY_RULE_CONFLICT") {
    return null;
  }
  return {
    message: String((detail as { message?: unknown }).message ?? error.message),
    rule: (detail as { rule: CategoryRule }).rule,
  };
}

function transactionPayloadChanges(
  transaction: StatementTransaction,
  values: InlineTransactionEditValues,
): TransactionPayload {
  const payload: TransactionPayload = {};
  if (values.transaction_date !== transaction.transaction_date) {
    payload.transaction_date = values.transaction_date;
  }
  if (values.transaction_detail.trim() !== transaction.transaction_detail) {
    payload.transaction_detail = values.transaction_detail.trim();
  }
  if (moneyToCents(values.amount) !== moneyToCents(transaction.amount)) {
    payload.amount = values.amount.trim();
  }
  if (values.direction !== transaction.direction) {
    payload.direction = values.direction;
  }
  return payload;
}

function hasPayloadChanges(payload: TransactionPayload): boolean {
  return (
    payload.transaction_date !== undefined ||
    payload.transaction_detail !== undefined ||
    payload.amount !== undefined ||
    payload.direction !== undefined
  );
}

function transactionMatchesNormalizationFilter(
  transaction: StatementTransaction,
  filter: NormalizationFilter,
): boolean {
  const status = transactionNormalizationStatus(transaction);
  const source = transactionNormalizationSource(transaction);
  if (filter === "all") {
    return true;
  }
  if (filter === "normalized") {
    return Boolean(
      transaction.normalized_name &&
        ["NORMALIZED", "USER_CONFIRMED"].includes(status),
    );
  }
  if (filter === "needs_review") {
    return status === "NEEDS_REVIEW";
  }
  if (filter === "user_edited") {
    return transaction.user_edited_normalization;
  }
  return (
    !transaction.normalized_name ||
    source === "UNRESOLVED" ||
    status === "NOT_NORMALIZED"
  );
}

function transactionMatchesSearch(transaction: StatementTransaction, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }
  return [transaction.normalized_name ?? "", transaction.transaction_detail].some((value) =>
    value.toLowerCase().includes(normalizedQuery),
  );
}

function statementToEditValues(statement: StatementDetection): StatementEditValues {
  return {
    document_type: statement.document_type,
    institution: statement.institution,
    product_name: statement.product_name ?? "",
    account_type: statement.account_type,
    account_last_four: statement.account_last_four ?? "",
    statement_start_date: statement.statement_start_date ?? "",
    statement_end_date: statement.statement_end_date ?? "",
  };
}

function statementPayloadFromValues(values: StatementEditValues): StatementUpdate {
  return {
    document_type: values.document_type,
    institution: values.institution,
    product_name: values.product_name.trim() || null,
    account_type: values.account_type,
    account_last_four: values.account_last_four.trim() || null,
    statement_start_date: values.statement_start_date || null,
    statement_end_date: values.statement_end_date || null,
  };
}

function validateStatementEdit(values: StatementEditValues): string {
  const lastFour = values.account_last_four.trim();
  if (lastFour && !/^\d{1,4}$/.test(lastFour)) {
    return "Account last four must contain 1 to 4 digits only.";
  }
  if (values.statement_start_date && values.statement_end_date) {
    const start = new Date(`${values.statement_start_date}T00:00:00`);
    const end = new Date(`${values.statement_end_date}T00:00:00`);
    if (start > end) {
      return "Statement start date must be on or before statement end date.";
    }
  }
  return "";
}

function collectDescendantFolderIds(folder: FolderNode): number[] {
  return folder.folders.flatMap((child) => [child.id, ...collectDescendantFolderIds(child)]);
}

function flattenFolders(folders: FolderNode[], trail: string[] = []): Array<{ id: number; label: string }> {
  return folders.flatMap((folder) => {
    const nextTrail = [...trail, folder.name];
    return [
      { id: folder.id, label: nextTrail.join(" > ") },
      ...flattenFolders(folder.folders, nextTrail),
    ];
  });
}

function findFolder(folders: FolderNode[], folderId: number): FolderNode | undefined {
  for (const folder of folders) {
    if (folder.id === folderId) {
      return folder;
    }
    const found = findFolder(folder.folders, folderId);
    if (found) {
      return found;
    }
  }
  return undefined;
}

function findFile(folders: FolderNode[], files: StoredFile[], fileId: number): StoredFile | undefined {
  const rootMatch = files.find((file) => file.id === fileId);
  if (rootMatch) {
    return rootMatch;
  }

  for (const folder of folders) {
    const directMatch = folder.files.find((file) => file.id === fileId);
    if (directMatch) {
      return directMatch;
    }
    const nestedMatch = findFile(folder.folders, [], fileId);
    if (nestedMatch) {
      return nestedMatch;
    }
  }

  return undefined;
}

function folderPath(folders: FolderNode[], folderId: number): FolderNode[] {
  for (const folder of folders) {
    if (folder.id === folderId) {
      return [folder];
    }
    const childPath = folderPath(folder.folders, folderId);
    if (childPath.length > 0) {
      return [folder, ...childPath];
    }
  }
  return [];
}

function selectedFolderId(selected: SelectedItem, selectedFile: StoredFile | undefined): number | null {
  if (selected.type === "folder") {
    return selected.id;
  }
  if (selected.type === "file") {
    return selectedFile?.folder_id ?? null;
  }
  return null;
}

function fileCanPreview(file: StoredFile): "image" | "pdf" | "unsupported" {
  const name = file.display_name.toLowerCase();
  if (
    file.mime_type === "image/png" ||
    file.mime_type === "image/jpeg" ||
    name.endsWith(".png") ||
    name.endsWith(".jpg") ||
    name.endsWith(".jpeg")
  ) {
    return "image";
  }
  if (file.mime_type === "application/pdf" || name.endsWith(".pdf")) {
    return "pdf";
  }
  return "unsupported";
}

function formatLocation(pathParts: string[]): string {
  return pathParts.join(" > ");
}

function searchResultKey(result: SearchResult): string {
  return `${result.type}-${result.id}`;
}

function scrollTreeRowIntoView(result: SearchResult) {
  scrollTreeKeyIntoView(searchResultKey(result));
}

function scrollTreeKeyIntoView(key: string) {
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(`[data-tree-key="${key}"]`)
        ?.scrollIntoView({ block: "nearest" });
    });
  });
}

export default function App() {
  const [tree, setTree] = useState<FileManagerTree>(emptyTree);
  const [categoryOptions, setCategoryOptions] = useState<CategoryOption[]>([]);
  const [selected, setSelected] = useState<SelectedItem>({ type: "root" });
  const [activeView, setActiveView] = useState<AppView>("files");
  const [expandedFolders, setExpandedFolders] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isSearchLoading, setIsSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [isLoading, setIsLoading] = useState(true);
  const [isDragging, setIsDragging] = useState(false);
  const [notice, setNotice] = useState("Loading file manager...");
  const [error, setError] = useState("");
  const [moveDialog, setMoveDialog] = useState<MoveDialogState>(null);
  const [moveDestination, setMoveDestination] = useState<string>("root");
  const [nameDialog, setNameDialog] = useState<NameDialogState>(null);
  const [nameValue, setNameValue] = useState("");
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState>(null);
  const [attention, setAttention] = useState<AttentionListResponse>(emptyAttention);
  const [isAttentionLoading, setIsAttentionLoading] = useState(false);
  const [attentionError, setAttentionError] = useState("");
  const [isAttentionOpen, setIsAttentionOpen] = useState(false);
  const [isRulesOpen, setIsRulesOpen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(
    () => window.localStorage.getItem("file-sidebar-collapsed") === "true",
  );
  const [attentionFocusTarget, setAttentionFocusTarget] = useState<AttentionFocusTarget | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attentionRef = useRef<HTMLDivElement>(null);
  const searchRequestRef = useRef(0);

  const selectedFolder = selected.type === "folder" ? findFolder(tree.folders, selected.id) : undefined;
  const selectedFile = selected.type === "file" ? findFile(tree.folders, tree.files, selected.id) : undefined;
  const uploadTargetFolderId = selectedFolderId(selected, selectedFile);
  const allFolders = useMemo(() => flattenFolders(tree.folders), [tree.folders]);
  const folderMoveExclusions = useMemo(() => {
    if (moveDialog?.type !== "folder") {
      return new Set<number>();
    }
    const folder = findFolder(tree.folders, moveDialog.id);
    return new Set(folder ? [folder.id, ...collectDescendantFolderIds(folder)] : [moveDialog.id]);
  }, [moveDialog, tree.folders]);

  const breadcrumbs = useMemo(() => {
    if (selected.type === "root") {
      return [];
    }
    if (selected.type === "folder") {
      return folderPath(tree.folders, selected.id);
    }
    if (selectedFile?.folder_id) {
      return folderPath(tree.folders, selectedFile.folder_id);
    }
    return [];
  }, [selected, selectedFile, tree.folders]);
  const selectedLocationPath = formatLocation(["My Files", ...breadcrumbs.map((folder) => folder.name)]);

  const selectedFolderContents = selectedFolder
    ? { folders: selectedFolder.folders.length, files: selectedFolder.files.length }
    : { folders: tree.folders.length, files: tree.files.length };

  const loadTree = useCallback(async () => {
    setIsLoading(true);
    setError("");

    try {
      const nextTree = await getFileManagerTree({ sortBy, sortDirection });
      setTree(nextTree);
      setNotice("File manager ready.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Backend unavailable.");
      setNotice("Unable to load files.");
    } finally {
      setIsLoading(false);
    }
  }, [sortBy, sortDirection]);

  const refreshAttention = useCallback(async () => {
    setIsAttentionLoading(true);
    setAttentionError("");
    try {
      if (isAttentionOpen) {
        const nextAttention = await getAttention();
        setAttention(nextAttention);
      } else {
        const nextCount = await getAttentionCount();
        setAttention((current) => ({
          ...current,
          ...nextCount,
          items: nextCount.total === 0 ? [] : current.items,
        }));
      }
    } catch (caught) {
      setAttentionError(caught instanceof Error ? caught.message : "Attention items could not be loaded.");
    } finally {
      setIsAttentionLoading(false);
    }
  }, [isAttentionOpen]);

  useEffect(() => {
    void loadTree();
  }, [loadTree]);

  useEffect(() => {
    let isActive = true;
    void getCategoryCatalog()
      .then((catalog) => {
        if (isActive) {
          setCategoryOptions(categoryOptionsFromCatalog(catalog));
        }
      })
      .catch((caught) => {
        if (isActive) {
          setError(caught instanceof Error ? caught.message : "Category options could not be loaded.");
        }
      });
    return () => {
      isActive = false;
    };
  }, []);

  useEffect(() => {
    void refreshAttention();
  }, [refreshAttention]);

  useEffect(() => {
    window.localStorage.setItem("file-sidebar-collapsed", String(isSidebarCollapsed));
  }, [isSidebarCollapsed]);

  useEffect(() => {
    if (!isAttentionOpen) {
      return;
    }

    function handlePointerDown(event: MouseEvent) {
      if (attentionRef.current && !attentionRef.current.contains(event.target as Node)) {
        setIsAttentionOpen(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsAttentionOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isAttentionOpen]);

  useEffect(() => {
    const query = search.trim();
    searchRequestRef.current += 1;
    const requestId = searchRequestRef.current;

    if (!query) {
      setSearchResults([]);
      setSearchError("");
      setIsSearchLoading(false);
      setIsSearchOpen(false);
      return;
    }

    const controller = new AbortController();
    setIsSearchOpen(true);
    setIsSearchLoading(true);
    setSearchError("");

    const timeoutId = window.setTimeout(() => {
      void searchFileManager(query, controller.signal)
        .then((response) => {
          if (searchRequestRef.current !== requestId) {
            return;
          }
          setSearchResults(response.results);
        })
        .catch((caught) => {
          if (controller.signal.aborted || searchRequestRef.current !== requestId) {
            return;
          }
          setSearchResults([]);
          setSearchError(caught instanceof Error ? caught.message : "Search failed.");
        })
        .finally(() => {
          if (!controller.signal.aborted && searchRequestRef.current === requestId) {
            setIsSearchLoading(false);
          }
        });
    }, 250);

    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [search]);

  function toggleFolder(folderId: number) {
    setExpandedFolders((current) => {
      const next = new Set(current);
      if (next.has(folderId)) {
        next.delete(folderId);
      } else {
        next.add(folderId);
      }
      return next;
    });
  }

  function selectFolder(folderId: number) {
    setAttentionFocusTarget(null);
    setActiveView("files");
    setSelected({ type: "folder", id: folderId });
  }

  function selectFile(fileId: number) {
    setAttentionFocusTarget(null);
    setActiveView("files");
    setSelected({ type: "file", id: fileId });
  }

  function selectRoot() {
    setAttentionFocusTarget(null);
    setActiveView("files");
    setSelected({ type: "root" });
  }

  function clearSearch() {
    searchRequestRef.current += 1;
    setSearch("");
    setSearchResults([]);
    setSearchError("");
    setIsSearchLoading(false);
    setIsSearchOpen(false);
  }

  function selectSearchResult(result: SearchResult) {
    setExpandedFolders((current) => new Set([...current, ...result.expand_folder_ids]));
    setSelected({ type: result.type, id: result.id });
    clearSearch();
    setNotice(`Selected ${result.type} "${result.name}".`);
    scrollTreeRowIntoView(result);
  }

  function handleSelectAttentionItem(item: AttentionItem) {
    if (item.file_id === null) {
      setIsAttentionOpen(false);
      setNotice("This item no longer exists.");
      void refreshAttention();
      return;
    }

    const file = findFile(tree.folders, tree.files, item.file_id);
    if (!file) {
      setIsAttentionOpen(false);
      setNotice("This item no longer exists.");
      void loadTree();
      void refreshAttention();
      return;
    }

    setExpandedFolders((current) => new Set([...current, ...item.folder_path.map((folder) => folder.id)]));
    setActiveView("files");
    setSelected({ type: "file", id: item.file_id });
    clearSearch();
    setIsAttentionOpen(false);
    setAttentionFocusTarget({
      attentionId: item.attention_id,
      fileId: item.file_id,
      statementId: item.statement_id,
      transactionId: item.transaction_id,
      targetSection: item.target_section,
      targetField: item.target_field,
      requestedAt: Date.now(),
    });
    setNotice(`Opened ${file.display_name} for ${item.title.toLowerCase()}.`);
    scrollTreeKeyIntoView(`file-${item.file_id}`);
  }

  function handleOpenSummaryTransaction(transaction: SummaryTransaction) {
    if (!transaction.source_file_available) {
      setNotice("Source file no longer retained. Transaction record preserved in Summary.");
      return;
    }
    const file = findFile(tree.folders, tree.files, transaction.file_id);
    if (!file) {
      setNotice("The source file is not currently available in the File Manager.");
      void loadTree();
      return;
    }
    const ancestors = file.folder_id ? folderPath(tree.folders, file.folder_id) : [];
    setExpandedFolders((current) => new Set([...current, ...ancestors.map((folder) => folder.id)]));
    setActiveView("files");
    setSelected({ type: "file", id: file.id });
    setAttentionFocusTarget({
      attentionId: `summary:transaction:${transaction.id}`,
      fileId: file.id,
      statementId: transaction.statement_id,
      transactionId: transaction.id,
      targetSection: "transaction",
      targetField: "transaction_detail",
      requestedAt: Date.now(),
    });
    setNotice(`Opened ${file.display_name} from Summary.`);
    scrollTreeKeyIntoView(`file-${file.id}`);
  }

  function openNameDialog(dialog: Exclude<NameDialogState, null>) {
    setError("");
    setNameDialog(dialog);
    setNameValue(dialog.initialValue);
  }

  async function submitNameDialog(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!nameDialog) {
      return;
    }

    const value = nameValue.trim();
    if (!value) {
      setError(`${nameDialog.label} is required.`);
      return;
    }

    try {
      if (nameDialog.type === "create-folder") {
        const folder = (await createFolder(value, uploadTargetFolderId)) as FolderNode;
        if (uploadTargetFolderId !== null) {
          setExpandedFolders((current) => new Set([...current, uploadTargetFolderId]));
        }
        setSelected({ type: "folder", id: folder.id });
        setNotice(`Created folder "${folder.name}".`);
      }

      if (nameDialog.type === "rename-folder") {
        await updateFolder(nameDialog.id, { name: value });
        setNotice("Folder renamed.");
      }

      if (nameDialog.type === "rename-file") {
        await updateStoredFile(nameDialog.id, { display_name: value });
        setNotice("File renamed.");
      }

      setNameDialog(null);
      await loadTree();
      await refreshAttention();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Name change failed.");
    }
  }

  function handleCreateFolder() {
    openNameDialog({
      type: "create-folder",
      title: "New Folder",
      label: "Folder name",
      initialValue: "",
    });
  }

  function handleRenameSelected() {
    if (selected.type === "folder" && selectedFolder) {
      openNameDialog({
        type: "rename-folder",
        id: selectedFolder.id,
        title: "Rename Folder",
        label: "Folder name",
        initialValue: selectedFolder.name,
      });
    }

    if (selected.type === "file" && selectedFile) {
      openNameDialog({
        type: "rename-file",
        id: selectedFile.id,
        title: "Rename File",
        label: "Filename",
        initialValue: selectedFile.display_name,
      });
    }
  }

  function handleDeleteSelected() {
    if (selected.type === "folder" && selectedFolder) {
      setConfirmDialog({ type: "folder", id: selectedFolder.id, name: selectedFolder.name });
    }

    if (selected.type === "file" && selectedFile) {
      setConfirmDialog({ type: "file", id: selectedFile.id, name: selectedFile.display_name });
    }
  }

  async function confirmDelete() {
    if (!confirmDialog) {
      return;
    }

    try {
      if (confirmDialog.type === "folder") {
        await deleteFolder(confirmDialog.id);
        setNotice("Folder deleted.");
      } else {
        await deleteStoredFile(confirmDialog.id);
        setNotice("File deleted.");
      }
      setSelected({ type: "root" });
      setConfirmDialog(null);
      await loadTree();
      await refreshAttention();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Item could not be deleted.");
    }
  }

  function openMoveDialog() {
    if (selected.type === "folder" && selectedFolder) {
      setMoveDialog({ type: "folder", id: selectedFolder.id, name: selectedFolder.name });
      setMoveDestination(selectedFolder.parent_folder_id === null ? "root" : String(selectedFolder.parent_folder_id));
    }
    if (selected.type === "file" && selectedFile) {
      setMoveDialog({ type: "file", id: selectedFile.id, name: selectedFile.display_name });
      setMoveDestination(selectedFile.folder_id === null ? "root" : String(selectedFile.folder_id));
    }
  }

  async function confirmMove() {
    if (!moveDialog) {
      return;
    }
    const destination = moveDestination === "root" ? null : Number(moveDestination);
    try {
      if (moveDialog.type === "folder") {
        await updateFolder(moveDialog.id, { parent_folder_id: destination });
      } else {
        await updateStoredFile(moveDialog.id, { folder_id: destination });
      }
      if (destination !== null) {
        setExpandedFolders((current) => new Set([...current, destination]));
      }
      setMoveDialog(null);
      setNotice("Move complete.");
      await loadTree();
      await refreshAttention();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Item could not be moved.");
    }
  }

  async function handleUpload(fileList: FileList | File[]) {
    const files = Array.from(fileList);
    if (files.length === 0) {
      return;
    }
    setError("");
    try {
      const result = await uploadFiles(files, uploadTargetFolderId);
      if (uploadTargetFolderId !== null) {
        setExpandedFolders((current) => new Set([...current, uploadTargetFolderId]));
      }
      if (result.uploaded.length > 0) {
        setSelected({ type: "file", id: result.uploaded[0].file.id });
      }
      const failed = result.failed.length > 0 ? ` ${result.failed.length} failed.` : "";
      setNotice(`${result.uploaded.length} uploaded.${failed}`);
      await loadTree();
      await refreshAttention();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed.");
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function renderFileRow(file: StoredFile, depth: number) {
    const isSelected = selected.type === "file" && selected.id === file.id;
    return (
      <li key={`file-${file.id}`}>
        <button
          className={`tree-row tree-row--file ${isSelected ? "tree-row--selected" : ""}`}
          data-tree-key={`file-${file.id}`}
          onClick={() => selectFile(file.id)}
          style={{ paddingLeft: `${depth * 18 + 38}px` }}
          type="button"
        >
          <span className="tree-row__name">{file.display_name}</span>
          <span className="tree-row__meta">{formatBytes(file.file_size)}</span>
        </button>
      </li>
    );
  }

  function renderFolder(folder: FolderNode, depth: number) {
    const isExpanded = expandedFolders.has(folder.id);
    const isSelected = selected.type === "folder" && selected.id === folder.id;
    return (
      <li key={`folder-${folder.id}`}>
        <div
          className={`tree-row tree-row--folder ${isSelected ? "tree-row--selected" : ""}`}
          data-tree-key={`folder-${folder.id}`}
          style={{ paddingLeft: `${depth * 18 + 8}px` }}
        >
          <button
            aria-label={isExpanded ? `Collapse ${folder.name}` : `Expand ${folder.name}`}
            className="tree-toggle"
            onClick={() => toggleFolder(folder.id)}
            type="button"
          >
            {isExpanded ? "▾" : "▸"}
          </button>
          <button className="tree-name-button" onClick={() => selectFolder(folder.id)} type="button">
            <span className="tree-row__name">{folder.name}</span>
            <span className="tree-row__meta">{folder.folders.length + folder.files.length}</span>
          </button>
        </div>
        {isExpanded ? (
          <ul className="tree-list">
            {folder.folders.map((child) => renderFolder(child, depth + 1))}
            {folder.files.map((file) => renderFileRow(file, depth + 1))}
          </ul>
        ) : null}
      </li>
    );
  }

  const uploadTargetPath =
    uploadTargetFolderId === null
      ? "My Files"
      : ["My Files", ...folderPath(tree.folders, uploadTargetFolderId).map((folder) => folder.name)].join(" > ");

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div className="top-bar__inner">
          <h1>Personal Financial File Manager</h1>
          <div className="top-actions">
            <button
              aria-current={activeView === "summary" ? "page" : undefined}
              className={activeView === "summary" ? "primary-navigation--active" : ""}
              onClick={() => {
                setAttentionFocusTarget(null);
                setActiveView("summary");
              }}
              type="button"
            >
              Summary
            </button>
            <button
              aria-current={activeView === "maintenance" ? "page" : undefined}
              className={activeView === "maintenance" ? "primary-navigation--active" : ""}
              onClick={() => {
                setAttentionFocusTarget(null);
                setActiveView("maintenance");
              }}
              type="button"
            >
              Maintenance
            </button>
            <div className="attention-menu" ref={attentionRef}>
              <NotificationBell
                attention={attention}
                error={attentionError}
                isLoading={isAttentionLoading}
                isOpen={isAttentionOpen}
                onRefresh={() => void refreshAttention()}
                onSelect={handleSelectAttentionItem}
                onToggle={() => setIsAttentionOpen((current) => !current)}
              />
            </div>
            <button
              disabled={categoryOptions.length === 0}
              onClick={() => setIsRulesOpen(true)}
              type="button"
            >
              Learned Rules
            </button>
            <button onClick={handleCreateFolder} type="button">
              New Folder
            </button>
            <button onClick={() => fileInputRef.current?.click()} type="button">
              Upload
            </button>
          </div>
        </div>
      </header>

      <nav className="breadcrumbs" aria-label="Breadcrumbs">
        <button onClick={selectRoot} type="button">
          My Files
        </button>
        {activeView === "summary" ? (
          <span>
            <span className="breadcrumb-separator">/</span>
            <button aria-current="page" onClick={() => setActiveView("summary")} type="button">Summary</button>
          </span>
        ) : activeView === "maintenance" ? (
          <span>
            <span className="breadcrumb-separator">/</span>
            <button aria-current="page" onClick={() => setActiveView("maintenance")} type="button">Maintenance</button>
          </span>
        ) : breadcrumbs.map((folder) => (
          <span key={folder.id}>
            <span className="breadcrumb-separator">/</span>
            <button onClick={() => selectFolder(folder.id)} type="button">
              {folder.name}
            </button>
          </span>
        ))}
        {activeView === "files" && selectedFile ? (
          <span>
            <span className="breadcrumb-separator">/</span>
            <button onClick={() => selectFile(selectedFile.id)} type="button">
              {selectedFile.display_name}
            </button>
          </span>
        ) : null}
      </nav>

      <section
        className={`manager-layout ${isSidebarCollapsed ? "manager-layout--sidebar-collapsed" : ""}`}
        aria-label="File manager"
      >
        <aside
          className={`tree-pane ${isSidebarCollapsed ? "tree-pane--collapsed" : ""}`}
          aria-label="Folders and files"
        >
          <div className="pane-header">
            {!isSidebarCollapsed ? (
              <div>
                <h2>My Files</h2>
                <span>{isLoading ? "Loading" : `${tree.folders.length + tree.files.length} root items`}</span>
              </div>
            ) : null}
            <button
              aria-label={isSidebarCollapsed ? "Expand file sidebar" : "Collapse file sidebar"}
              className="sidebar-collapse-button"
              onClick={() => setIsSidebarCollapsed((current) => !current)}
              title={isSidebarCollapsed ? "Expand files" : "Collapse files"}
              type="button"
            >
              {isSidebarCollapsed ? "›" : "‹"}
            </button>
          </div>
          {!isSidebarCollapsed ? (
            <>
              <section className="sidebar-toolbar" aria-label="File sidebar controls">
                <div className="search-box">
                  <label htmlFor="file-search">Search files</label>
                  <div className="search-input-wrap">
                    <input
                      aria-controls="file-search-results"
                      aria-expanded={isSearchOpen}
                      autoComplete="off"
                      id="file-search"
                      onChange={(event) => setSearch(event.target.value)}
                      onFocus={() => search.trim() && setIsSearchOpen(true)}
                      onKeyDown={(event) => event.key === "Escape" && setIsSearchOpen(false)}
                      placeholder="Find folders or files"
                      role="combobox"
                      value={search}
                    />
                    {search ? (
                      <button aria-label="Clear search" className="search-clear" onClick={clearSearch} type="button">
                        x
                      </button>
                    ) : null}
                  </div>
                  {isSearchOpen && search.trim() ? (
                    <div className="search-results" id="file-search-results" role="listbox">
                      {isSearchLoading ? <div className="search-state">Searching...</div> : null}
                      {!isSearchLoading && searchError ? <div className="search-state search-state--error">{searchError}</div> : null}
                      {!isSearchLoading && !searchError && searchResults.length === 0 ? (
                        <div className="search-state">No files or folders found.</div>
                      ) : null}
                      {!isSearchLoading && !searchError
                        ? searchResults.map((result) => (
                            <button
                              className="search-result-row"
                              key={searchResultKey(result)}
                              onClick={() => selectSearchResult(result)}
                              role="option"
                              type="button"
                            >
                              <span className="search-result-row__type">{result.type === "folder" ? "Folder" : "File"}</span>
                              <span className="search-result-row__body">
                                <span className="search-result-row__name">{result.name}</span>
                                <span className="search-result-row__path">{formatLocation(result.parent_path)}</span>
                              </span>
                            </button>
                          ))
                        : null}
                    </div>
                  ) : null}
                </div>
                <div className="sidebar-sort-controls">
                  <label>
                    <span>Sort</span>
                    <select onChange={(event) => setSortBy(event.target.value as SortBy)} value={sortBy}>
                      {sortOptions.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Direction</span>
                    <select onChange={(event) => setSortDirection(event.target.value as SortDirection)} value={sortDirection}>
                      <option value="asc">Ascending</option>
                      <option value="desc">Descending</option>
                    </select>
                  </label>
                  <button onClick={() => void loadTree()} type="button">Refresh</button>
                </div>
              </section>
              {error ? <p className="error-banner">{error}</p> : null}
              <ul className="tree-list tree-list--root">
            <li>
              <div
                className={`tree-row tree-row--folder ${selected.type === "root" ? "tree-row--selected" : ""}`}
                data-tree-key="root"
              >
                <span className="tree-toggle" aria-hidden="true">
                  ▾
                </span>
                <button className="tree-name-button" onClick={selectRoot} type="button">
                  <span className="tree-row__name">My Files</span>
                  <span className="tree-row__meta">{tree.folders.length + tree.files.length}</span>
                </button>
              </div>
              <ul className="tree-list">
                {tree.folders.map((folder) => renderFolder(folder, 1))}
                {tree.files.map((file) => renderFileRow(file, 1))}
              </ul>
            </li>
              </ul>
            </>
          ) : null}
        </aside>

        <section className="details-pane" aria-label={activeView === "summary" ? "Expense summary" : activeView === "maintenance" ? "Maintenance" : "Selected item details"}>
          {activeView === "summary" ? (
            <SummaryPage onOpenTransaction={handleOpenSummaryTransaction} />
          ) : activeView === "maintenance" ? (
            <MaintenancePage />
          ) : (
            <>
          <div className="pane-header">
            <div>
              <h2>
                {selectedFile?.display_name ?? selectedFolder?.name ?? "My Files"}
              </h2>
              <p>{selected.type === "file" ? "File" : "Folder"}</p>
            </div>
            <div className="detail-actions">
              <button onClick={handleCreateFolder} type="button">
                New Folder
              </button>
              <button onClick={() => fileInputRef.current?.click()} type="button">
                Upload
              </button>
              {selected.type !== "root" ? (
                <>
                  <button onClick={handleRenameSelected} type="button">
                    Rename
                  </button>
                  <button onClick={openMoveDialog} type="button">
                    Move
                  </button>
                  <button className="danger-button" onClick={handleDeleteSelected} type="button">
                    Delete
                  </button>
                </>
              ) : null}
            </div>
          </div>

          <input
            accept=".pdf,.jpg,.jpeg,.png,.csv,.xlsx,.txt"
            multiple
            onChange={(event) => {
              if (event.target.files) {
                void handleUpload(event.target.files);
              }
            }}
            ref={fileInputRef}
            type="file"
          />

          {!selectedFile ? (
            <div
              className={`drop-zone ${isDragging ? "drop-zone--active" : ""}`}
              onDragLeave={() => setIsDragging(false)}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragging(true);
              }}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragging(false);
                void handleUpload(event.dataTransfer.files);
              }}
            >
              <strong>Drop files here</strong>
              <span>Upload target: {uploadTargetPath}</span>
              <button onClick={() => fileInputRef.current?.click()} type="button">
                Browse Files
              </button>
            </div>
          ) : null}

          <p className={`notice ${error ? "notice--error" : ""}`}>{error || notice}</p>

          {selectedFile ? (
            <FileDetails
              attentionTarget={attentionFocusTarget?.fileId === selectedFile.id ? attentionFocusTarget : null}
              categoryOptions={categoryOptions}
              file={selectedFile}
              locationPath={selectedLocationPath}
              onAttentionRefresh={refreshAttention}
              onAttentionTargetConsumed={() => setAttentionFocusTarget(null)}
              onTreeRefresh={loadTree}
            />
          ) : (
            <FolderDetails
              createdAt={selectedFolder?.created_at}
              fileCount={selectedFolderContents.files}
              folderCount={selectedFolderContents.folders}
              modifiedAt={selectedFolder?.updated_at}
              name={selectedFolder?.name ?? "My Files"}
            />
          )}
            </>
          )}
        </section>
      </section>

      {isRulesOpen ? (
        <LearnedRulesDialog categoryOptions={categoryOptions} onClose={() => setIsRulesOpen(false)} />
      ) : null}

      {nameDialog ? (
        <div className="modal-backdrop" role="presentation">
          <form aria-modal="true" className="move-dialog" onSubmit={submitNameDialog} role="dialog">
            <h2>{nameDialog.title}</h2>
            <label>
              <span>{nameDialog.label}</span>
              <input
                autoFocus
                onChange={(event) => setNameValue(event.target.value)}
                value={nameValue}
              />
            </label>
            <div className="modal-actions">
              <button onClick={() => setNameDialog(null)} type="button">
                Cancel
              </button>
              <button type="submit">Save</button>
            </div>
          </form>
        </div>
      ) : null}

      {confirmDialog ? (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="move-dialog" role="dialog">
            <h2>Delete {confirmDialog.name}</h2>
            <p>
              {confirmDialog.type === "folder"
                ? "This permanently removes the folder, nested folders, files, and stored file copies."
                : "This permanently removes the file record and stored file copy."}
            </p>
            <div className="modal-actions">
              <button onClick={() => setConfirmDialog(null)} type="button">
                Cancel
              </button>
              <button className="danger-button" onClick={() => void confirmDelete()} type="button">
                Delete
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {moveDialog ? (
        <div className="modal-backdrop" role="presentation">
          <div aria-modal="true" className="move-dialog" role="dialog">
            <h2>Move {moveDialog.name}</h2>
            <label>
              <span>Destination</span>
              <select onChange={(event) => setMoveDestination(event.target.value)} value={moveDestination}>
                <option value="root">My Files</option>
                {allFolders
                  .filter((folder) => !folderMoveExclusions.has(folder.id))
                  .map((folder) => (
                    <option key={folder.id} value={folder.id}>
                      {folder.label}
                    </option>
                  ))}
              </select>
            </label>
            <div className="modal-actions">
              <button onClick={() => setMoveDialog(null)} type="button">
                Cancel
              </button>
              <button onClick={() => void confirmMove()} type="button">
                Move
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

function NotificationBell({
  attention,
  error,
  isLoading,
  isOpen,
  onRefresh,
  onSelect,
  onToggle,
}: {
  attention: AttentionListResponse;
  error: string;
  isLoading: boolean;
  isOpen: boolean;
  onRefresh: () => void;
  onSelect: (item: AttentionItem) => void;
  onToggle: () => void;
}) {
  const accessibleLabel =
    attention.total > 0
      ? `Notifications, ${attention.total} items need attention`
      : "Notifications, no items need attention";
  const transactionItems = attention.items.filter((item) => item.target_section === "transaction");
  const statementItems = attention.items.filter((item) => item.target_section === "statement");

  return (
    <>
      <button
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={accessibleLabel}
        className={`notification-button ${attention.total > 0 ? "notification-button--active" : ""}`}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onToggle();
          }
        }}
        onClick={onToggle}
        type="button"
      >
        <span aria-hidden="true" className="notification-button__icon">
          🔔
        </span>
        {attention.total > 0 ? <span className="notification-badge">{attention.total}</span> : null}
      </button>
      {isOpen ? (
        <div aria-label="Needs attention" className="attention-panel" role="dialog">
          <div className="attention-panel__header">
            <div>
              <h2>Needs Attention</h2>
              <p>
                {attention.total > 0
                  ? `${attention.blocking_total} blocking, ${attention.review_total} review`
                  : "All selected transactions are ready for summary."}
              </p>
            </div>
            <button disabled={isLoading} onClick={onRefresh} type="button">
              Refresh
            </button>
          </div>
          {isLoading ? <div className="attention-panel__state">Loading attention items...</div> : null}
          {error ? <div className="attention-panel__state attention-panel__state--error">{error}</div> : null}
          {!isLoading && !error && attention.total === 0 ? (
            <div className="attention-panel__state">All selected transactions are ready for summary.</div>
          ) : null}
          <AttentionGroup title="Transactions" items={transactionItems} onSelect={onSelect} />
          <AttentionGroup title="Statements" items={statementItems} onSelect={onSelect} />
        </div>
      ) : null}
    </>
  );
}

function AttentionGroup({
  items,
  onSelect,
  title,
}: {
  items: AttentionItem[];
  onSelect: (item: AttentionItem) => void;
  title: string;
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className="attention-group" aria-label={title}>
      <h3>
        {title} <span>{items.length}</span>
      </h3>
      <div className="attention-list">
        {items.map((item) => (
          <button className="attention-item" key={item.attention_id} onClick={() => onSelect(item)} type="button">
            <span className={`attention-item__severity attention-item__severity--${item.severity.toLowerCase()}`}>
              {item.blocking ? "!" : "?"}
            </span>
            <span className="attention-item__body">
              <span className="attention-item__title">{item.title}</span>
              <span className="attention-item__context">
                {item.transaction_id !== null
                  ? `${item.transaction_name ?? "Transaction"} - ${formatDateOnly(item.transaction_date)} - ${formatMoney(item.transaction_amount)}`
                  : item.description}
              </span>
              <span className="attention-item__source">
                {item.statement_label ?? item.file_name ?? "Selected file"}
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function FolderDetails({
  createdAt,
  fileCount,
  folderCount,
  modifiedAt,
  name,
}: {
  createdAt?: string;
  fileCount: number;
  folderCount: number;
  modifiedAt?: string;
  name: string;
}) {
  return (
    <div className="details-content">
      <dl className="metadata-grid">
        <div>
          <dt>Name</dt>
          <dd>{name}</dd>
        </div>
        <div>
          <dt>Type</dt>
          <dd>Folder</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{createdAt ? formatDate(createdAt) : "Root"}</dd>
        </div>
        <div>
          <dt>Modified</dt>
          <dd>{modifiedAt ? formatDate(modifiedAt) : "Root"}</dd>
        </div>
        <div>
          <dt>Contents</dt>
          <dd>
            {folderCount} folders, {fileCount} files
          </dd>
        </div>
      </dl>
    </div>
  );
}

type PreviewState =
  | { status: "loading"; objectUrl?: undefined; message?: undefined }
  | { status: "ready"; objectUrl: string; message?: undefined }
  | { status: "error"; objectUrl?: undefined; message: string }
  | { status: "unsupported"; objectUrl?: undefined; message?: undefined };

function FileDetails({
  attentionTarget,
  categoryOptions,
  file,
  locationPath,
  onAttentionRefresh,
  onAttentionTargetConsumed,
  onTreeRefresh,
}: {
  attentionTarget: AttentionFocusTarget | null;
  categoryOptions: CategoryOption[];
  file: StoredFile;
  locationPath: string;
  onAttentionRefresh: () => Promise<void>;
  onAttentionTargetConsumed: () => void;
  onTreeRefresh: () => Promise<void>;
}) {
  const isPdf = fileCanPreview(file) === "pdf";
  const [statement, setStatement] = useState<StatementDetection | null>(null);
  const [isStatementLoading, setIsStatementLoading] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [statementError, setStatementError] = useState("");
  const [latestExtraction, setLatestExtraction] = useState<TransactionExtraction | null>(null);
  const [transactions, setTransactions] = useState<StatementTransaction[]>([]);
  const [isTransactionsLoading, setIsTransactionsLoading] = useState(false);
  const [hasLoadedTransactions, setHasLoadedTransactions] = useState(false);
  const [transactionError, setTransactionError] = useState("");
  const [analysisSteps, setAnalysisSteps] = useState<AnalysisStep[]>([]);
  const [analysisNotice, setAnalysisNotice] = useState("");
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setStatement(null);
    setStatementError("");

    if (!isPdf) {
      setIsStatementLoading(false);
      return () => controller.abort();
    }

    setIsStatementLoading(true);
    void getStatementForFile(file.id, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setStatement(response.statement);
        }
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setStatementError(caught instanceof Error ? caught.message : "Statement information could not be loaded.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsStatementLoading(false);
        }
      });

    return () => controller.abort();
  }, [file.id, isPdf]);

  const refreshTransactions = useCallback(async (statementId: number) => {
    const response = await getTransactionsForStatement(statementId);
    setLatestExtraction(response.latest_extraction);
    setTransactions(response.transactions);
    setHasLoadedTransactions(true);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLatestExtraction(null);
    setTransactions([]);
    setTransactionError("");
    setHasLoadedTransactions(false);

    if (!statement) {
      setIsTransactionsLoading(false);
      return () => controller.abort();
    }

    setIsTransactionsLoading(true);
    void getTransactionsForStatement(statement.id, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setLatestExtraction(response.latest_extraction);
          setTransactions(response.transactions);
          setHasLoadedTransactions(true);
        }
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setTransactionError(caught instanceof Error ? caught.message : "Transactions could not be loaded.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsTransactionsLoading(false);
          setHasLoadedTransactions(true);
        }
      });

    return () => controller.abort();
  }, [statement]);

  async function handleAnalyzeStatement() {
    setIsAnalyzing(true);
    setStatementError("");
    setTransactionError("");
    setAnalysisNotice("");
    setAnalysisSteps(initialAnalyzeSteps());
    try {
      const response = await analyzeStatementFile(file.id);
      setStatement(response.statement);
      setLatestExtraction(response.extraction);
      setTransactions(response.transactions);
      setHasLoadedTransactions(true);
      setAnalysisSteps(response.steps);
      if (response.status === "FAILED") {
        const failed = response.steps.find((step) => step.key === response.failed_step);
        setStatementError(
          `Analysis could not be completed. Failed step: ${failed?.label ?? response.failed_step ?? "Unknown"}.`,
        );
      } else if (response.retention.removed_count > 0) {
        setAnalysisNotice(
          `Analysis complete. ${labelFor(institutionLabels, response.retention.institution)} keeps the 5 most recent statement files. ${response.retention.removed_count} older source file${response.retention.removed_count === 1 ? " was" : "s were"} removed.`,
        );
      } else {
        setAnalysisNotice("Analysis complete.");
      }
      await onAttentionRefresh();
      await onTreeRefresh();
    } catch (caught) {
      setStatementError(caught instanceof Error ? caught.message : "Unable to analyze this file.");
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function handleSaveStatement(payload: StatementUpdate) {
    setStatementError("");
    const nextStatement = await updateStatementForFile(file.id, payload);
    setStatement(nextStatement);
    await onAttentionRefresh();
  }

  async function handleCreateTransaction(payload: Required<TransactionPayload>) {
    if (!statement) {
      return;
    }
    setTransactionError("");
    await createTransactionForStatement(statement.id, payload);
    await refreshTransactions(statement.id);
    await onAttentionRefresh();
  }

  async function handleUpdateTransaction(transactionId: number, payload: TransactionPayload) {
    if (!statement) {
      return;
    }
    setTransactionError("");
    await updateTransaction(transactionId, payload);
    await refreshTransactions(statement.id);
    await onAttentionRefresh();
  }

  async function handleUpdateTransactionNormalization(
    transactionId: number,
    payload: TransactionNormalizationPayload,
  ) {
    if (!statement) {
      return;
    }
    setTransactionError("");
    await updateTransactionNormalization(transactionId, payload);
    await refreshTransactions(statement.id);
    await onAttentionRefresh();
  }

  async function handleUpdateTransactionCategory(transactionId: number, payload: TransactionCategoryPayload) {
    if (!statement) {
      return;
    }
    setTransactionError("");
    await updateTransactionCategory(transactionId, payload);
    await refreshTransactions(statement.id);
    await onAttentionRefresh();
  }

  async function handleUpdateTransactionInclusion(
    transactionId: number,
    payload: TransactionInclusionPayload,
  ): Promise<StatementTransaction> {
    setTransactionError("");
    const transaction = await updateTransactionInclusion(transactionId, payload);
    setTransactions((current) => replaceTransactionInList(current, transaction));
    await onAttentionRefresh();
    return transaction;
  }

  async function handleBulkUpdateTransactionReview(payload: TransactionReviewBulkPayload): Promise<number[]> {
    setTransactionError("");
    const response = await bulkUpdateTransactionReview(payload);
    setTransactions((current) => mergeUpdatedTransactions(current, response.transactions));
    await onAttentionRefresh();
    return response.skipped_transaction_ids;
  }

  async function handleExcludeTransaction(transactionId: number) {
    if (!statement) {
      return;
    }
    setTransactionError("");
    try {
      await excludeTransaction(transactionId);
      await refreshTransactions(statement.id);
      await onAttentionRefresh();
    } catch (caught) {
      setTransactionError(caught instanceof Error ? caught.message : "Unable to exclude this transaction.");
    }
  }

  const isStatementWorkspace = isPdf && statement?.detection_status !== "NOT_A_STATEMENT";
  const metadata = (
    <dl className="metadata-grid">
      <div><dt>Filename</dt><dd>{file.display_name}</dd></div>
      <div><dt>File Type</dt><dd>{file.mime_type}</dd></div>
      <div><dt>File Size</dt><dd>{formatBytes(file.file_size)}</dd></div>
      <div><dt>Location</dt><dd>{locationPath}</dd></div>
      <div><dt>Uploaded</dt><dd>{formatDate(file.created_at)}</dd></div>
      <div><dt>Modified</dt><dd>{formatDate(file.updated_at)}</dd></div>
    </dl>
  );

  return (
    <div className={`details-content ${isStatementWorkspace ? "details-content--statement" : ""}`}>
      {isStatementWorkspace ? (
        <StatementPanel
          analysisNotice={analysisNotice}
          analysisSteps={analysisSteps}
          attentionTarget={
            attentionTarget?.targetSection === "statement" &&
            attentionTarget.targetField !== "transaction_list_review"
              ? attentionTarget
              : null
          }
          error={statementError}
          isAnalyzing={isAnalyzing}
          isLoading={isStatementLoading}
          fileName={file.display_name}
          onAnalyze={handleAnalyzeStatement}
          onViewOriginal={() => setIsPreviewOpen(true)}
          onSave={handleSaveStatement}
          onAttentionTargetConsumed={onAttentionTargetConsumed}
          statement={statement}
        />
      ) : (
        <>
          {metadata}
          <div className="preview-header">
            <h3>Preview</h3>
            <a className="download-link" href={fileDownloadUrl(file.id)}>Download</a>
          </div>
          <PreviewPane file={file} />
        </>
      )}
      {isStatementWorkspace && statement ? (
        <TransactionPanel
          categoryOptions={categoryOptions}
          error={transactionError}
          isAnalyzing={isAnalyzing}
          isLoading={isTransactionsLoading}
          latestExtraction={latestExtraction}
          onAdd={handleCreateTransaction}
          onEdit={handleUpdateTransaction}
          onEditNormalization={handleUpdateTransactionNormalization}
          onEditCategory={handleUpdateTransactionCategory}
          onEditInclusion={handleUpdateTransactionInclusion}
          onExclude={handleExcludeTransaction}
          onBulkEditReview={handleBulkUpdateTransactionReview}
          onTransactionsUpdate={(updater) => setTransactions((current) => updater(current))}
          attentionTarget={
            hasLoadedTransactions &&
            (
              attentionTarget?.targetSection === "transaction" ||
              (
                attentionTarget?.targetSection === "statement" &&
                attentionTarget.targetField === "transaction_list_review"
              )
            )
              ? attentionTarget
              : null
          }
          onAttentionRefresh={onAttentionRefresh}
          onAttentionTargetConsumed={onAttentionTargetConsumed}
          transactions={transactions}
        />
      ) : null}
      {isStatementWorkspace ? (
        <details className="file-metadata-disclosure">
          <summary>File details</summary>
          {metadata}
        </details>
      ) : null}
      {isPreviewOpen ? (
        <div className="modal-backdrop preview-backdrop" role="presentation">
          <section aria-label="Original file preview" aria-modal="true" className="preview-dialog" role="dialog">
            <div className="preview-dialog__header">
              <div>
                <h2>Original File</h2>
                <p>{file.display_name}</p>
              </div>
              <div className="detail-actions">
                <a className="download-link" href={fileDownloadUrl(file.id)}>Download</a>
                <button autoFocus onClick={() => setIsPreviewOpen(false)} type="button">Close</button>
              </div>
            </div>
            <PreviewPane file={file} />
          </section>
        </div>
      ) : null}
    </div>
  );
}

function StatementPanel({
  analysisNotice,
  analysisSteps,
  attentionTarget,
  error,
  fileName,
  isAnalyzing,
  isLoading,
  onAnalyze,
  onAttentionTargetConsumed,
  onSave,
  onViewOriginal,
  statement,
}: {
  analysisNotice: string;
  analysisSteps: AnalysisStep[];
  attentionTarget: AttentionFocusTarget | null;
  error: string;
  fileName: string;
  isAnalyzing: boolean;
  isLoading: boolean;
  onAnalyze: () => void;
  onAttentionTargetConsumed: () => void;
  onSave: (payload: StatementUpdate) => Promise<void>;
  onViewOriginal: () => void;
  statement: StatementDetection | null;
}) {
  const [editValues, setEditValues] = useState<StatementEditValues | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const [activeAttentionField, setActiveAttentionField] = useState<string | null>(null);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const handledAttentionRef = useRef("");
  const buttonText = statement ? "Analyze Again" : "Analyze";
  const statusText = statement ? labelFor(detectionStatusLabels, statement.detection_status) : "Not Analyzed";
  const subtitle = statement?.metadata_source === "USER_EDITED" ? `${statusText} - User edited` : statusText;
  const isBusy = isAnalyzing || isLoading || isSaving;

  useEffect(() => {
    if (!statement) {
      setIsEditing(false);
      setEditValues(null);
      setEditError("");
      setActiveAttentionField(null);
      return;
    }
    if (!isEditing) {
      setEditValues(statementToEditValues(statement));
    }
  }, [statement, isEditing]);

  useEffect(() => {
    if (!attentionTarget || !statement || attentionTarget.statementId !== statement.id) {
      return;
    }
    const attentionKey = `${attentionTarget.attentionId}:${attentionTarget.requestedAt}`;
    if (handledAttentionRef.current === attentionKey) {
      return;
    }

    handledAttentionRef.current = attentionKey;
    setEditValues(statementToEditValues(statement));
    setEditError("");
    setIsEditing(true);
    setIsDetailsOpen(true);
    setActiveAttentionField(attentionTarget.targetField);
    onAttentionTargetConsumed();
  }, [attentionTarget, onAttentionTargetConsumed, statement]);

  useEffect(() => {
    if (!isEditing || !activeAttentionField) {
      return;
    }
    window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(`.statement-edit-form [data-attention-field="${activeAttentionField}"]`)
        ?.focus({ preventScroll: true });
    });
  }, [activeAttentionField, isEditing]);

  function updateEditValue(field: keyof StatementEditValues, value: string) {
    setEditValues((current) => (current ? { ...current, [field]: value } : current));
  }

  function startEditing() {
    if (!statement) {
      return;
    }
    setEditValues(statementToEditValues(statement));
    setEditError("");
    setActiveAttentionField(null);
    setIsEditing(true);
  }

  function cancelEditing() {
    setEditValues(statement ? statementToEditValues(statement) : null);
    setEditError("");
    setActiveAttentionField(null);
    setIsEditing(false);
  }

  function statementFieldClass(field: string): string {
    return activeAttentionField === field ? "attention-field attention-field--active" : "";
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editValues) {
      return;
    }

    const validationMessage = validateStatementEdit(editValues);
    if (validationMessage) {
      setEditError(validationMessage);
      return;
    }

    setIsSaving(true);
    setEditError("");
    try {
      await onSave(statementPayloadFromValues(editValues));
      setActiveAttentionField(null);
      setIsEditing(false);
    } catch (caught) {
      setEditError(caught instanceof Error ? caught.message : "Statement details could not be saved.");
    } finally {
      setIsSaving(false);
    }
  }

  function correctionNote(
    currentValue: string | null,
    detectedValue: string | null,
    formatter: (value: string | null) => string,
  ) {
    if (!statement?.user_corrected || currentValue === detectedValue) {
      return null;
    }
    return (
      <span className="statement-correction-note">User corrected from {formatter(detectedValue)}</span>
    );
  }

  function periodCorrectionNote() {
    if (!statement?.user_corrected) {
      return null;
    }
    const currentKey = `${statement.statement_start_date ?? ""}|${statement.statement_end_date ?? ""}`;
    const detectedKey = `${statement.detected_statement_start_date ?? ""}|${statement.detected_statement_end_date ?? ""}`;
    if (currentKey === detectedKey) {
      return null;
    }
    return (
      <span className="statement-correction-note">
        User corrected from {formatDateRange(statement.detected_statement_start_date, statement.detected_statement_end_date)}
      </span>
    );
  }

  const formatDocumentType = (value: string | null) => (value ? labelFor(documentTypeLabels, value) : "Unknown");
  const formatInstitution = (value: string | null) => (value ? labelFor(institutionLabels, value) : "Unknown");
  const formatAccountType = (value: string | null) => (value ? labelFor(accountTypeLabels, value) : "Unknown");
  const formatLastFour = (value: string | null) => (value ? `ending in ${value}` : "Unknown");
  const formatProduct = (value: string | null) => value || "Not set";
  const statementSummary = statement
    ? [
        formatInstitution(statement.institution),
        formatAccountType(statement.account_type),
        formatDateRange(statement.statement_start_date, statement.statement_end_date),
      ].join(" • ")
    : "This statement has not been analyzed.";

  return (
    <section className="statement-panel" aria-label="Statement information">
      <div className="statement-panel__header">
        <div>
          <h3>{isEditing ? "Edit Statement Details" : fileName}</h3>
          <p>{statementSummary}</p>
          <span className="statement-status">{subtitle}</span>
        </div>
        <div className="statement-actions">
          {statement && !isEditing ? (
            <>
              <button disabled={isBusy} onClick={() => setIsDetailsOpen((current) => !current)} type="button">
                {isDetailsOpen ? "Hide Details" : "Details"}
              </button>
              <button disabled={isBusy} onClick={startEditing} type="button">Edit Details</button>
            </>
          ) : null}
          <button disabled={isBusy} onClick={onAnalyze} type="button">
            {isAnalyzing ? "Analyzing..." : buttonText}
          </button>
          <button disabled={isBusy} onClick={onViewOriginal} type="button">View Original File</button>
        </div>
      </div>

      {isLoading ? <div className="statement-state">Loading statement information...</div> : null}
      {isAnalyzing ? <div className="statement-state">Analyzing statement...</div> : null}
      {error ? <div className="statement-state statement-state--error">{error}</div> : null}
      {editError ? <div className="statement-state statement-state--error">{editError}</div> : null}
      {analysisNotice ? <div className="statement-state">{analysisNotice}</div> : null}
      {analysisSteps.length > 0 ? (
        <ol className="analysis-progress" aria-label="Analysis progress">
          {analysisSteps.map((step) => (
            <li className={`analysis-progress__item analysis-progress__item--${step.status.toLowerCase()}`} key={step.key}>
              <span aria-hidden="true">{analysisStepMarker(step.status)}</span>
              <span>{step.label}</span>
              {step.message ? <span className="analysis-progress__message">{step.message}</span> : null}
            </li>
          ))}
        </ol>
      ) : null}

      {!isLoading && !statement && !error ? (
        <div className="statement-state">No statement analysis yet.</div>
      ) : null}

      {statement && isEditing && editValues ? (
        <form className="statement-edit-form" onSubmit={(event) => void handleSave(event)}>
          <label className={statementFieldClass("document_type")}>
            <span>Document Type</span>
            <select
              data-attention-field="document_type"
              value={editValues.document_type}
              onChange={(event) => updateEditValue("document_type", event.target.value)}
            >
              {documentTypeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={statementFieldClass("institution")}>
            <span>Institution</span>
            <select
              data-attention-field="institution"
              value={editValues.institution}
              onChange={(event) => updateEditValue("institution", event.target.value)}
            >
              {institutionOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={statementFieldClass("product_name")}>
            <span>Product Name</span>
            <input
              data-attention-field="product_name"
              maxLength={255}
              type="text"
              value={editValues.product_name}
              onChange={(event) => updateEditValue("product_name", event.target.value)}
            />
          </label>
          <label className={statementFieldClass("account_type")}>
            <span>Account Type</span>
            <select
              data-attention-field="account_type"
              value={editValues.account_type}
              onChange={(event) => updateEditValue("account_type", event.target.value)}
            >
              {accountTypeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={statementFieldClass("account_last_four")}>
            <span>Account Last Four</span>
            <input
              data-attention-field="account_last_four"
              inputMode="numeric"
              maxLength={4}
              pattern="[0-9]{0,4}"
              type="text"
              value={editValues.account_last_four}
              onChange={(event) => updateEditValue("account_last_four", event.target.value)}
            />
          </label>
          <label className={statementFieldClass("statement_start_date")}>
            <span>Statement Start</span>
            <input
              data-attention-field="statement_start_date"
              type="date"
              value={editValues.statement_start_date}
              onChange={(event) => updateEditValue("statement_start_date", event.target.value)}
            />
          </label>
          <label className={statementFieldClass("statement_end_date")}>
            <span>Statement End</span>
            <input
              data-attention-field="statement_end_date"
              type="date"
              value={editValues.statement_end_date}
              onChange={(event) => updateEditValue("statement_end_date", event.target.value)}
            />
          </label>
          <div className="statement-edit-form__actions">
            <button disabled={isSaving} onClick={cancelEditing} type="button">
              Cancel
            </button>
            <button disabled={isSaving} type="submit">
              {isSaving ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </form>
      ) : null}

      {statement && !isEditing && isDetailsOpen ? (
        <dl className="statement-grid">
          <div>
            <dt>Document Type</dt>
            <dd>
              {formatDocumentType(statement.document_type)}
              {correctionNote(statement.document_type, statement.detected_document_type, formatDocumentType)}
            </dd>
          </div>
          <div>
            <dt>Institution</dt>
            <dd>
              {formatInstitution(statement.institution)}
              {correctionNote(statement.institution, statement.detected_institution, formatInstitution)}
            </dd>
          </div>
          {statement.product_name || statement.detected_product_name ? (
            <div>
              <dt>Product</dt>
              <dd>
                {formatProduct(statement.product_name)}
                {correctionNote(statement.product_name, statement.detected_product_name, formatProduct)}
              </dd>
            </div>
          ) : null}
          <div>
            <dt>Account Type</dt>
            <dd>
              {formatAccountType(statement.account_type)}
              {correctionNote(statement.account_type, statement.detected_account_type, formatAccountType)}
            </dd>
          </div>
          <div>
            <dt>Account</dt>
            <dd>
              {statement.account_last_four ? `Ending in ${statement.account_last_four}` : "Unknown"}
              {correctionNote(statement.account_last_four, statement.detected_account_last_four, formatLastFour)}
            </dd>
          </div>
          <div>
            <dt>Statement Period</dt>
            <dd>
              {formatDateRange(statement.statement_start_date, statement.statement_end_date)}
              {periodCorrectionNote()}
            </dd>
          </div>
          <div>
            <dt>Detection Confidence</dt>
            <dd>{formatConfidence(statement.detection_confidence)}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{labelFor(detectionStatusLabels, statement.detection_status)}</dd>
          </div>
          {statement.detection_reason ? (
            <div className="statement-grid__wide">
              <dt>Reason</dt>
              <dd>{statement.detection_reason}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </section>
  );
}

function TransactionPanel({
  attentionTarget,
  categoryOptions,
  error,
  isAnalyzing,
  isLoading,
  latestExtraction,
  onAdd,
  onBulkEditReview,
  onEdit,
  onEditCategory,
  onEditInclusion,
  onEditNormalization,
  onExclude,
  onTransactionsUpdate,
  onAttentionRefresh,
  onAttentionTargetConsumed,
  transactions,
}: {
  attentionTarget: AttentionFocusTarget | null;
  categoryOptions: CategoryOption[];
  error: string;
  isAnalyzing: boolean;
  isLoading: boolean;
  latestExtraction: TransactionExtraction | null;
  onAdd: (payload: Required<TransactionPayload>) => Promise<void>;
  onBulkEditReview: (payload: TransactionReviewBulkPayload) => Promise<number[]>;
  onEdit: (transactionId: number, payload: TransactionPayload) => Promise<void>;
  onEditCategory: (transactionId: number, payload: TransactionCategoryPayload) => Promise<void>;
  onEditInclusion: (transactionId: number, payload: TransactionInclusionPayload) => Promise<StatementTransaction>;
  onEditNormalization: (transactionId: number, payload: TransactionNormalizationPayload) => Promise<void>;
  onExclude: (transactionId: number) => Promise<void>;
  onTransactionsUpdate: (updater: (current: StatementTransaction[]) => StatementTransaction[]) => void;
  onAttentionRefresh: () => Promise<void>;
  onAttentionTargetConsumed: () => void;
  transactions: StatementTransaction[];
}) {
  const [sortBy, setSortBy] = useState<TransactionSortBy>("source_order");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [dialogState, setDialogState] = useState<TransactionDialogState>(null);
  const [formValues, setFormValues] = useState<TransactionFormValues>(emptyTransactionFormValues);
  const [formError, setFormError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [normalizationFilter, setNormalizationFilter] = useState<NormalizationFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [inclusionFilter, setInclusionFilter] = useState<InclusionFilter>("all");
  const [isSavingBulkReview, setIsSavingBulkReview] = useState(false);
  const [inclusionError, setInclusionError] = useState("");
  const [inclusionNotice, setInclusionNotice] = useState("");
  const [savingInclusionIds, setSavingInclusionIds] = useState<Set<number>>(new Set());
  const [transactionSearch, setTransactionSearch] = useState("");
  const [activeAttentionFocus, setActiveAttentionFocus] = useState<ActiveAttentionFocus | null>(null);
  const [editingTransactionId, setEditingTransactionId] = useState<number | null>(null);
  const [inlineEditValues, setInlineEditValues] = useState<InlineTransactionEditValues | null>(null);
  const [inlineEditError, setInlineEditError] = useState("");
  const [isSavingInlineEdit, setIsSavingInlineEdit] = useState(false);
  const inclusionRequestVersions = useRef<Map<number, number>>(new Map());
  const handledAttentionRef = useRef("");
  const reviewCount = transactions.filter((transaction) => transaction.needs_review).length;
  const normalizationReviewCount = transactions.filter(
    (transaction) => transactionNormalizationStatus(transaction) === "NEEDS_REVIEW",
  ).length;
  const categoryReviewCount = transactions.filter(categoryNeedsReview).length;
  const phase8ReviewCount = transactions.filter(transactionNeedsPhase8Review).length;
  const includedCount = transactions.filter(transactionIncluded).length;
  const excludedFromSummaryCount = transactions.length - includedCount;
  const activeTransactionIds = useMemo(
    () => transactions.filter((transaction) => !transaction.excluded).map((transaction) => transaction.id),
    [transactions],
  );
  const allTransactionsReviewed =
    activeTransactionIds.length > 0 &&
    transactions
      .filter((transaction) => activeTransactionIds.includes(transaction.id))
      .every((transaction) => transactionReviewStatus(transaction) === "REVIEWED");
  const selectedTotalCents = selectedAmountCents(transactions);
  const isActionBusy = isAnalyzing || isLoading;
  const visibleTransactions = useMemo(() => {
    return transactions.filter(
      (transaction) =>
        transactionMatchesNormalizationFilter(transaction, normalizationFilter) &&
        transactionMatchesCategoryFilter(transaction, categoryFilter) &&
        transactionMatchesInclusionFilter(transaction, inclusionFilter) &&
        transactionMatchesSearch(transaction, transactionSearch),
    );
  }, [categoryFilter, inclusionFilter, normalizationFilter, transactionSearch, transactions]);
  const sortedTransactions = useMemo(() => {
    return [...visibleTransactions].sort((left, right) => {
      const multiplier = sortDirection === "asc" ? 1 : -1;
      if (sortBy === "normalized_name") {
        const leftName = left.normalized_name ?? "";
        const rightName = right.normalized_name ?? "";
        return (leftName.localeCompare(rightName) || left.id - right.id) * multiplier;
      }
      if (sortBy === "main_category") {
        return (categoryPairLabel(left).localeCompare(categoryPairLabel(right)) || left.id - right.id) * multiplier;
      }
      if (sortBy === "subcategory") {
        const leftSubcategory = labelFor(subcategoryLabels, categorySubcategoryValue(left));
        const rightSubcategory = labelFor(subcategoryLabels, categorySubcategoryValue(right));
        return (leftSubcategory.localeCompare(rightSubcategory) || left.id - right.id) * multiplier;
      }
      if (sortBy === "transaction_date") {
        return left.transaction_date.localeCompare(right.transaction_date) * multiplier;
      }
      if (sortBy === "amount") {
        return (Number(left.amount) - Number(right.amount)) * multiplier;
      }
      return (left.source_order - right.source_order || left.id - right.id) * multiplier;
    });
  }, [sortBy, sortDirection, visibleTransactions]);
  const editingTransaction = useMemo(
    () => transactions.find((transaction) => transaction.id === editingTransactionId) ?? null,
    [editingTransactionId, transactions],
  );
  const hasUnsavedInlineEdit = useCallback(() => {
    if (!editingTransaction || !inlineEditValues) {
      return false;
    }
    return inlineTransactionEditIsDirty(editingTransaction, inlineEditValues, categoryOptions);
  }, [categoryOptions, editingTransaction, inlineEditValues]);
  const startInlineEdit = useCallback(
    (transaction: StatementTransaction, targetField: string | null = null, preserveAttention = false) => {
      if (
        editingTransactionId !== null &&
        editingTransactionId !== transaction.id &&
        hasUnsavedInlineEdit() &&
        !window.confirm("You have unsaved changes. Discard changes and edit another transaction?")
      ) {
        return;
      }
      if (!preserveAttention) {
        setActiveAttentionFocus(null);
      }
      setEditingTransactionId(transaction.id);
      setInlineEditValues(inlineEditValuesFromTransaction(transaction, categoryOptions));
      setInlineEditError("");
      if (targetField) {
        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => {
            document
              .querySelector<HTMLElement>(
                `[data-transaction-id="${transaction.id}"] [data-attention-field="${targetField}"]`,
              )
              ?.focus({ preventScroll: true });
          });
        });
      }
    },
    [categoryOptions, editingTransactionId, hasUnsavedInlineEdit],
  );

  useEffect(() => {
    if (editingTransactionId !== null && !transactions.some((transaction) => transaction.id === editingTransactionId)) {
      setEditingTransactionId(null);
      setInlineEditValues(null);
      setInlineEditError("");
    }
  }, [editingTransactionId, transactions]);

  useEffect(() => {
    if (!attentionTarget) {
      return;
    }
    const attentionKey = `${attentionTarget.attentionId}:${attentionTarget.requestedAt}`;
    if (handledAttentionRef.current === attentionKey || isLoading) {
      return;
    }

    const targetField = attentionTarget.targetField ?? "transaction_detail";
    if (attentionTarget.transactionId === null) {
      if (targetField !== "transaction_list_review") {
        return;
      }
      handledAttentionRef.current = attentionKey;
      onAttentionTargetConsumed();
      setActiveAttentionFocus({ ...attentionTarget, targetField, softened: false });
      return;
    }

    const targetTransaction = transactions.find((transaction) => transaction.id === attentionTarget.transactionId);
    if (!targetTransaction) {
      handledAttentionRef.current = attentionKey;
      setInclusionError("This item no longer exists.");
      void onAttentionRefresh();
      onAttentionTargetConsumed();
      return;
    }

    handledAttentionRef.current = attentionKey;
    onAttentionTargetConsumed();
    setTransactionSearch("");
    setNormalizationFilter("all");
    setCategoryFilter("all");
    setInclusionFilter("all");
    setActiveAttentionFocus({ ...attentionTarget, targetField, softened: false });
    startInlineEdit(targetTransaction, targetField, true);
  }, [attentionTarget, isLoading, onAttentionRefresh, onAttentionTargetConsumed, startInlineEdit, transactions]);

  const activeAttentionTransactionId = activeAttentionFocus?.transactionId ?? null;
  const activeAttentionRequestedAt = activeAttentionFocus?.requestedAt ?? null;
  const activeAttentionTargetField = activeAttentionFocus?.targetField ?? null;
  const activeAttentionTargetsListReview = activeAttentionTargetField === "transaction_list_review";

  useEffect(() => {
    if (activeAttentionRequestedAt === null) {
      return;
    }

    const targetField = activeAttentionTargetField ?? "transaction_detail";
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        if (targetField === "transaction_list_review") {
          const control = document.querySelector<HTMLElement>('[data-attention-field="transaction_list_review"]');
          control?.scrollIntoView({
            block: "center",
            behavior: prefersReducedMotion ? "auto" : "smooth",
          });
          control?.focus({ preventScroll: true });
          return;
        }
        if (activeAttentionTransactionId === null) {
          return;
        }
        const row = document.querySelector<HTMLElement>(`[data-transaction-id="${activeAttentionTransactionId}"]`);
        const scrollContainer = row?.closest<HTMLElement>(".details-pane");
        if (row && scrollContainer && scrollContainer.scrollHeight > scrollContainer.clientHeight + 1) {
          const rowRect = row.getBoundingClientRect();
          const containerRect = scrollContainer.getBoundingClientRect();
          const offset = rowRect.top - containerRect.top - containerRect.height * 0.32;
          scrollContainer.scrollTo({
            top: scrollContainer.scrollTop + offset,
            behavior: prefersReducedMotion ? "auto" : "smooth",
          });
        } else if (row) {
          const rowRect = row.getBoundingClientRect();
          window.scrollTo({
            top: window.scrollY + rowRect.top - window.innerHeight * 0.35,
            behavior: prefersReducedMotion ? "auto" : "smooth",
          });
        }
        row
          ?.querySelector<HTMLElement>(`[data-attention-field="${targetField}"]`)
          ?.focus({ preventScroll: true });
      });
    });

    const timeoutId = window.setTimeout(() => {
      setActiveAttentionFocus((current) =>
        current?.requestedAt === activeAttentionRequestedAt ? { ...current, softened: true } : current,
      );
    }, 4200);

    return () => window.clearTimeout(timeoutId);
  }, [
    activeAttentionRequestedAt,
    activeAttentionTargetField,
    activeAttentionTransactionId,
    sortedTransactions,
  ]);

  function openAddDialog() {
    setActiveAttentionFocus(null);
    setDialogState({ mode: "add" });
    setFormValues(emptyTransactionFormValues());
    setFormError("");
  }

  function closeDialog() {
    setDialogState(null);
    setFormValues(emptyTransactionFormValues());
    setFormError("");
    setActiveAttentionFocus(null);
  }

  function cancelInlineEdit() {
    setEditingTransactionId(null);
    setInlineEditValues(null);
    setInlineEditError("");
    setActiveAttentionFocus(null);
  }

  function updateInlineEditValue<K extends keyof InlineTransactionEditValues>(
    field: K,
    value: InlineTransactionEditValues[K],
  ) {
    setInlineEditValues((current) => {
      if (!current) {
        return current;
      }
      if (field === "main_category" && typeof value === "string" && isCategoryMainValue(value)) {
        return {
          ...current,
          main_category: value,
          subcategory: defaultSubcategoryFor(categoryOptions, value),
        };
      }
      return { ...current, [field]: value };
    });
    setInlineEditError("");
  }

  async function handleSaveInlineEdit(transaction: StatementTransaction) {
    if (!inlineEditValues || editingTransactionId !== transaction.id) {
      return;
    }

    const validationMessage = validateInlineTransactionEdit(inlineEditValues, transaction, categoryOptions);
    if (validationMessage) {
      setInlineEditError(validationMessage);
      return;
    }

    const initialValues = inlineEditValuesFromTransaction(transaction, categoryOptions);
    const corePayload = transactionPayloadChanges(transaction, inlineEditValues);
    const normalizedNameChanged = inlineEditValues.normalized_name !== initialValues.normalized_name;
    const categoryChanged =
      inlineEditValues.main_category !== initialValues.main_category ||
      inlineEditValues.subcategory !== initialValues.subcategory;
    const categorySaveRequested = categoryChanged || inlineEditValues.use_for_future;

    if (
      !hasPayloadChanges(corePayload) &&
      !normalizedNameChanged &&
      !categorySaveRequested
    ) {
      cancelInlineEdit();
      return;
    }

    setIsSavingInlineEdit(true);
    setInlineEditError("");
    try {
      if (hasPayloadChanges(corePayload)) {
        await onEdit(transaction.id, corePayload);
      }
      if (normalizedNameChanged) {
        await onEditNormalization(transaction.id, {
          normalized_name: inlineEditValues.normalized_name.trim().replace(/\s+/g, " "),
          use_for_future: false,
        });
      }
      if (categorySaveRequested) {
        const categoryPayload: TransactionCategoryPayload = {
          main_category: inlineEditValues.main_category,
          subcategory: inlineEditValues.subcategory,
          use_for_future: inlineEditValues.use_for_future,
        };
        try {
          await onEditCategory(transaction.id, categoryPayload);
        } catch (caught) {
          const conflict = categoryRuleConflict(caught);
          if (!conflict) {
            throw caught;
          }
          const replace = window.confirm(
            `${conflict.message}\n\nExisting: ${labelFor(categoryLabels, conflict.rule.main_category)} → ${labelFor(subcategoryLabels, conflict.rule.subcategory)}\nNew: ${labelFor(categoryLabels, inlineEditValues.main_category)} → ${labelFor(subcategoryLabels, inlineEditValues.subcategory)}\n\nReplace the saved rule?`,
          );
          if (!replace) {
            throw new Error("The saved rule was not replaced. Uncheck the future-transactions option to save this row only.");
          }
          await onEditCategory(transaction.id, { ...categoryPayload, replace_existing_rule: true });
        }
      }
      cancelInlineEdit();
    } catch (caught) {
      setInlineEditError(caught instanceof Error ? caught.message : "Transaction could not be saved.");
    } finally {
      setIsSavingInlineEdit(false);
    }
  }

  function updateFormValue(field: keyof TransactionFormValues, value: string) {
    setFormValues((current) => ({ ...current, [field]: value }));
  }

  async function handleToggleExpenseInclusion(transaction: StatementTransaction, checked: boolean) {
    const previousTransaction = transaction;
    const nextVersion = (inclusionRequestVersions.current.get(transaction.id) ?? 0) + 1;
    inclusionRequestVersions.current.set(transaction.id, nextVersion);
    setInclusionError("");
    setInclusionNotice("");
    setSavingInclusionIds((current) => new Set(current).add(transaction.id));
    setTransactionsOptimistic(transaction.id, {
      include_in_expenses: checked,
      inclusion_initialized: true,
      inclusion_source: checked ? "USER_SELECTED" : "USER_EXCLUDED",
      inclusion_updated_at: new Date().toISOString(),
    });

    try {
      const saved = await onEditInclusion(transaction.id, { include_in_expenses: checked });
      if (inclusionRequestVersions.current.get(transaction.id) === nextVersion) {
        setTransactionsOptimistic(transaction.id, saved);
      }
    } catch (caught) {
      if (inclusionRequestVersions.current.get(transaction.id) === nextVersion) {
        setTransactionsOptimistic(transaction.id, previousTransaction);
        setInclusionError(caught instanceof Error ? caught.message : "Could not save transaction selection.");
      }
    } finally {
      if (inclusionRequestVersions.current.get(transaction.id) === nextVersion) {
        setSavingInclusionIds((current) => {
          const next = new Set(current);
          next.delete(transaction.id);
          return next;
        });
      }
    }
  }

  function setTransactionsOptimistic(
    transactionId: number,
    patch: Partial<StatementTransaction> | StatementTransaction,
  ) {
    const updatedTransaction = patch as StatementTransaction;
    if ("id" in updatedTransaction && updatedTransaction.id === transactionId && "transaction_detail" in updatedTransaction) {
      onTransactionsUpdate((current) => replaceTransactionInList(current, updatedTransaction));
      return;
    }
    onTransactionsUpdate((current) =>
      current.map((transaction) =>
        transaction.id === transactionId ? { ...transaction, ...patch } : transaction,
      ),
    );
  }

  async function handleMarkListReviewed() {
    if (activeTransactionIds.length === 0) {
      setInclusionError("No transactions are available to review.");
      setInclusionNotice("");
      return;
    }

    setIsSavingBulkReview(true);
    setInclusionError("");
    setInclusionNotice("");
    try {
      const skippedIds = await onBulkEditReview({
        transaction_ids: activeTransactionIds,
        review_status: "REVIEWED",
      });
      const changedCount = activeTransactionIds.length - skippedIds.length;
      setActiveAttentionFocus(null);
      setInclusionNotice(
        `Reviewed ${changedCount} transaction${changedCount === 1 ? "" : "s"} in this statement.`,
      );
    } catch (caught) {
      setInclusionError(caught instanceof Error ? caught.message : "Could not mark this statement reviewed.");
    } finally {
      setIsSavingBulkReview(false);
    }
  }

  function clearAttentionFocusOnInteraction() {
    if (activeAttentionFocus?.softened) {
      setActiveAttentionFocus(null);
    }
  }

  function attentionRowClass(transactionId: number): string {
    if (activeAttentionFocus?.transactionId !== transactionId) {
      return "";
    }
    return activeAttentionFocus.softened ? "transaction-row--attention-soft" : "transaction-row--attention";
  }

  function attentionFieldClass(field: string): string {
    return activeAttentionFocus?.targetField === field
      ? activeAttentionFocus.softened
        ? "attention-field attention-field--soft"
        : "attention-field attention-field--active"
      : "";
  }

  function attentionCellClass(transactionId: number, field: string, extraClass = ""): string {
    return [
      extraClass,
      activeAttentionFocus?.transactionId === transactionId && activeAttentionFocus.targetField === field
        ? "transaction-cell--attention"
        : "",
    ].filter(Boolean).join(" ");
  }

  async function handleSubmitTransaction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validationMessage = validateTransactionForm(formValues);
    if (validationMessage) {
      setFormError(validationMessage);
      return;
    }

    setIsSaving(true);
    setFormError("");
    try {
      const payload = transactionPayloadFromValues(formValues);
      await onAdd(payload);
      closeDialog();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : "Transaction could not be saved.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section
      className="transactions-panel"
      aria-label="Extracted transactions"
      onKeyDownCapture={clearAttentionFocusOnInteraction}
      onPointerDownCapture={clearAttentionFocusOnInteraction}
    >
      <div className="transactions-panel__header">
        <div>
          <h3>Transactions</h3>
          <p>
            {latestExtraction?.transaction_count ?? transactions.length} transactions extracted
            {latestExtraction && latestExtraction.transaction_count !== transactions.length
              ? ` - ${transactions.length} active`
              : ""}
            {reviewCount > 0 ? ` - ${reviewCount} need review` : ""}
            {normalizationReviewCount > 0 ? ` - ${normalizationReviewCount} name review` : ""}
            {categoryReviewCount > 0 ? ` - ${categoryReviewCount} category review` : ""}
            {phase8ReviewCount > 0 ? ` - ${phase8ReviewCount} summary review` : ""}
          </p>
        </div>
        <div className="transactions-actions">
          <button
            aria-label="Mark this bank statement transaction list reviewed"
            className={[
              "reviewed-list-button",
              activeAttentionTargetsListReview
                ? activeAttentionFocus?.softened
                  ? "attention-field--soft"
                  : "attention-field--active"
                : "",
            ].filter(Boolean).join(" ")}
            data-attention-field="transaction_list_review"
            disabled={
              isActionBusy ||
              isSavingBulkReview ||
              activeTransactionIds.length === 0 ||
              allTransactionsReviewed
            }
            onClick={() => void handleMarkListReviewed()}
            type="button"
          >
            {isSavingBulkReview ? "Saving..." : "Reviewed"}
          </button>
          <button disabled={isActionBusy} onClick={openAddDialog} type="button">
            + Add Transaction
          </button>
        </div>
      </div>

      {latestExtraction ? (
        <div className="transaction-state">
          {labelFor(extractionStatusLabels, latestExtraction.status)}
          {latestExtraction.message ? ` - ${latestExtraction.message}` : ""}
        </div>
      ) : null}
      {isLoading ? <div className="transaction-state">Loading transactions...</div> : null}
      {isAnalyzing ? <div className="transaction-state">Analyzing statement transactions...</div> : null}
      {error ? <div className="transaction-state transaction-state--error">{error}</div> : null}
      {inclusionError ? <div className="transaction-state transaction-state--error">{inclusionError}</div> : null}
      {inclusionNotice ? <div className="transaction-state">{inclusionNotice}</div> : null}

      {transactions.length > 0 ? (
        <div className="transaction-summary-grid">
          <div>
            <dt>Total Transactions</dt>
            <dd>{transactions.length}</dd>
          </div>
          <div>
            <dt>Selected</dt>
            <dd>{includedCount}</dd>
          </div>
          <div>
            <dt>Excluded</dt>
            <dd>{excludedFromSummaryCount}</dd>
          </div>
          <div>
            <dt>Needs Review</dt>
            <dd>{phase8ReviewCount}</dd>
          </div>
          <div className="transaction-summary-grid__wide">
            <dt>Selected Amount</dt>
            <dd>{formatMoneyCents(selectedTotalCents)}</dd>
          </div>
        </div>
      ) : null}

      <div className="transaction-sort-bar">
        <label>
          <span>Search Transactions</span>
          <input
            autoComplete="off"
            onChange={(event) => setTransactionSearch(event.target.value)}
            placeholder="Name or detail"
            type="text"
            value={transactionSearch}
          />
        </label>
        <label>
          <span>Sort Transactions</span>
          <select value={sortBy} onChange={(event) => setSortBy(event.target.value as TransactionSortBy)}>
            <option value="source_order">Statement Order</option>
            <option value="normalized_name">Name</option>
            <option value="main_category">Category</option>
            <option value="subcategory">Subcategory</option>
            <option value="transaction_date">Date</option>
            <option value="amount">Amount</option>
          </select>
        </label>
        <label>
          <span>Direction</span>
          <select value={sortDirection} onChange={(event) => setSortDirection(event.target.value as SortDirection)}>
            <option value="asc">Ascending</option>
            <option value="desc">Descending</option>
          </select>
        </label>
        <label>
          <span>Name Filter</span>
          <select
            value={normalizationFilter}
            onChange={(event) => setNormalizationFilter(event.target.value as NormalizationFilter)}
          >
            {normalizationFilterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Category Filter</span>
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value as CategoryFilter)}>
            {categoryFilterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Selection Filter</span>
          <select value={inclusionFilter} onChange={(event) => setInclusionFilter(event.target.value as InclusionFilter)}>
            {inclusionFilterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {transactions.length === 0 && !isLoading ? (
        <div className="transaction-empty">No transactions extracted yet.</div>
      ) : null}

      {transactions.length > 0 && sortedTransactions.length === 0 ? (
        <div className="transaction-empty">No transactions match the current view.</div>
      ) : null}

      {sortedTransactions.length > 0 ? (
        <div className="transaction-table-wrap">
          <table className="transaction-table">
            <thead>
              <tr>
                <th className="transaction-include-cell">
                  <span>Include in Expenses</span>
                </th>
                <th>Date</th>
                <th>Name</th>
                <th>Category</th>
                <th>Subcategory</th>
                <th>Transaction Detail</th>
                <th>Direction</th>
                <th className="transaction-table__amount">Amount</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedTransactions.map((transaction) => {
                const currentCategoryStatus = categoryStatus(transaction);
                const currentCategorySource = categorySource(transaction);
                const currentMainCategory = categoryMainValue(transaction);
                const currentSubcategory = categorySubcategoryValue(transaction);
                const needsCategoryReview = categoryNeedsReview(transaction);
                const isIncluded = transactionIncluded(transaction);
                const needsPhase8Review = transactionNeedsPhase8Review(transaction);
                const inclusionWarning = transactionInclusionWarning(transaction);
                const isEditing = editingTransactionId === transaction.id && inlineEditValues !== null;
                const editValues = isEditing ? inlineEditValues : null;
                return (
                  <tr
                    key={transaction.id}
                    data-transaction-id={transaction.id}
                    className={[
                      isIncluded ? "transaction-row--included" : "transaction-row--excluded",
                      needsPhase8Review ? "transaction-row--review" : "",
                      isEditing ? "transaction-row--editing" : "",
                      attentionRowClass(transaction.id),
                    ].filter(Boolean).join(" ")}
                    onKeyDown={(event) => {
                      if (!isEditing) {
                        return;
                      }
                      if (event.key === "Escape") {
                        event.preventDefault();
                        cancelInlineEdit();
                        return;
                      }
                      if (event.key === "Enter" && !(event.target instanceof HTMLSelectElement)) {
                        event.preventDefault();
                        void handleSaveInlineEdit(transaction);
                      }
                    }}
                  >
                    <td className="transaction-include-cell">
                      <input
                        aria-label={`Include ${transaction.normalized_name ?? transaction.transaction_detail} ${formatMoney(transaction.amount)}`}
                        checked={isIncluded}
                        className="transaction-table__select"
                        disabled={savingInclusionIds.has(transaction.id)}
                        onChange={(event) => void handleToggleExpenseInclusion(transaction, event.target.checked)}
                        type="checkbox"
                      />
                      {savingInclusionIds.has(transaction.id) ? (
                        <span className="transaction-include-saving">Saving</span>
                      ) : null}
                      {inclusionWarning ? <span className="transaction-badge">{inclusionWarning}</span> : null}
                    </td>
                    <td className={attentionCellClass(transaction.id, "transaction_date")}>
                      {editValues ? (
                        <input
                          className="transaction-inline-input"
                          data-attention-field="transaction_date"
                          type="date"
                          value={editValues.transaction_date}
                          onInput={(event) => updateInlineEditValue("transaction_date", event.currentTarget.value)}
                        />
                      ) : (
                        formatDateOnly(transaction.transaction_date)
                      )}
                    </td>
                    <td className={attentionCellClass(transaction.id, "normalized_name")}>
                      {editValues ? (
                        <input
                          className="transaction-inline-input"
                          data-attention-field="normalized_name"
                          maxLength={255}
                          placeholder="Unresolved"
                          type="text"
                          value={editValues.normalized_name}
                          onChange={(event) => updateInlineEditValue("normalized_name", event.target.value)}
                        />
                      ) : (
                        <span className={transaction.normalized_name ? "transaction-name-text" : "transaction-name-empty"}>
                          {transaction.normalized_name ?? "Unresolved"}
                        </span>
                      )}
                      <span className="transaction-name-meta">
                        {labelFor(normalizationStatusLabels, transactionNormalizationStatus(transaction))} -{" "}
                        {formatConfidence(transactionNormalizationConfidence(transaction))}
                      </span>
                      {transaction.user_edited_normalization ? (
                        <span className="transaction-badge">Name edited</span>
                      ) : null}
                      {transactionNormalizationSource(transaction) === "LEARNED_RULE" ? (
                        <span className="transaction-badge">Rule</span>
                      ) : null}
                      {transactionNormalizationStatus(transaction) === "NEEDS_REVIEW" ? (
                        <span className="transaction-badge">Name review</span>
                      ) : null}
                    </td>
                    <td className={attentionCellClass(transaction.id, "main_category")}>
                      {editValues ? (
                        <select
                          className="transaction-inline-input"
                          data-attention-field="main_category"
                          value={editValues.main_category}
                          onChange={(event) =>
                            updateInlineEditValue("main_category", event.target.value as CategoryMainValue)
                          }
                        >
                          {categoryOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className={currentMainCategory ? "transaction-category-text" : "transaction-category-empty"}>
                          {currentMainCategory
                            ? labelFor(categoryLabels, currentMainCategory)
                            : currentCategoryStatus === "NOT_APPLICABLE"
                              ? "Not Applicable"
                              : "Needs Review"}
                        </span>
                      )}
                      <span className="transaction-category-meta">
                        {labelFor(categoryStatusLabels, currentCategoryStatus)} -{" "}
                        {formatConfidence(categoryConfidence(transaction))}
                      </span>
                      {transaction.user_edited_category ? (
                        <span className="transaction-badge">Category edited</span>
                      ) : null}
                      {currentCategorySource === "LEARNED_RULE" ? (
                        <span className="transaction-badge">Learned from your previous correction</span>
                      ) : null}
                      {needsCategoryReview ? <span className="transaction-badge">Category review</span> : null}
                    </td>
                    <td className={attentionCellClass(transaction.id, "subcategory")}>
                      {editValues ? (
                        <select
                          className="transaction-inline-input"
                          data-attention-field="subcategory"
                          value={editValues.subcategory}
                          onChange={(event) =>
                            updateInlineEditValue("subcategory", event.target.value as CategorySubcategoryValue)
                          }
                        >
                          {subcategoryOptionsFor(categoryOptions, editValues.main_category).map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className={currentSubcategory ? "transaction-category-text" : "transaction-category-empty"}>
                          {currentSubcategory ? labelFor(subcategoryLabels, currentSubcategory) : "-"}
                        </span>
                      )}
                    </td>
                    <td className={attentionCellClass(transaction.id, "transaction_detail")}>
                      {editValues ? (
                        <input
                          className="transaction-inline-input"
                          data-attention-field="transaction_detail"
                          type="text"
                          value={editValues.transaction_detail}
                          onChange={(event) => updateInlineEditValue("transaction_detail", event.target.value)}
                        />
                      ) : (
                        <span className="transaction-detail-text">{transaction.transaction_detail}</span>
                      )}
                      {transaction.source_page ? (
                        <span className="transaction-source">Page {transaction.source_page}</span>
                      ) : null}
                    </td>
                    <td className={attentionCellClass(transaction.id, "direction")}>
                      {editValues ? (
                        <select
                          className="transaction-inline-input"
                          data-attention-field="direction"
                          value={editValues.direction}
                          onChange={(event) =>
                            updateInlineEditValue("direction", event.target.value as TransactionDirection)
                          }
                        >
                          {transactionDirectionOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        labelFor(directionLabels, String(transaction.direction))
                      )}
                    </td>
                    <td className={attentionCellClass(transaction.id, "amount", "transaction-table__amount")}>
                      {editValues ? (
                        <input
                          className="transaction-inline-input transaction-inline-input--amount"
                          data-attention-field="amount"
                          inputMode="decimal"
                          type="text"
                          value={editValues.amount}
                          onChange={(event) => updateInlineEditValue("amount", event.target.value)}
                        />
                      ) : (
                        formatMoney(transaction.amount)
                      )}
                    </td>
                    <td>
                      <div className="transaction-row-actions">
                        {isEditing ? (
                          <>
                            <label className="checkbox-label transaction-rule-checkbox">
                              <input
                                checked={editValues?.use_for_future ?? false}
                                onChange={(event) => updateInlineEditValue("use_for_future", event.target.checked)}
                                type="checkbox"
                              />
                              <span>Use this category for similar future transactions</span>
                            </label>
                            <button disabled={isSavingInlineEdit} onClick={() => void handleSaveInlineEdit(transaction)} type="button">
                              {isSavingInlineEdit ? "Saving..." : "Save"}
                            </button>
                            <button disabled={isSavingInlineEdit} onClick={cancelInlineEdit} type="button">
                              Cancel
                            </button>
                            {inlineEditError ? (
                              <span className="transaction-inline-error">{inlineEditError}</span>
                            ) : null}
                          </>
                        ) : (
                          <>
                            <button disabled={isActionBusy} onClick={() => startInlineEdit(transaction)} type="button">
                              Edit
                            </button>
                            <button className="danger-button" onClick={() => void onExclude(transaction.id)} type="button">
                              Exclude
                            </button>
                          </>
                        )}
                        {!isIncluded ? <span className="transaction-badge">Excluded from summary</span> : null}
                        {transaction.user_edited ? <span className="transaction-badge">Edited</span> : null}
                        {transaction.user_added ? <span className="transaction-badge">User added</span> : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {dialogState ? (
        <div className="modal-backdrop" role="presentation">
          <form className="transaction-dialog" onSubmit={(event) => void handleSubmitTransaction(event)}>
            <div>
              <h3>Add Transaction</h3>
            </div>
            {formError ? <div className="transaction-state transaction-state--error">{formError}</div> : null}
            <label className={attentionFieldClass("transaction_date")}>
              <span>Date</span>
              <input
                data-attention-field="transaction_date"
                placeholder="YYYY-MM-DD"
                type="text"
                value={formValues.transaction_date}
                onChange={(event) => updateFormValue("transaction_date", event.target.value)}
              />
            </label>
            <label className={attentionFieldClass("transaction_detail")}>
              <span>Transaction Detail</span>
              <input
                data-attention-field="transaction_detail"
                type="text"
                value={formValues.transaction_detail}
                onChange={(event) => updateFormValue("transaction_detail", event.target.value)}
              />
            </label>
            <label className={attentionFieldClass("amount")}>
              <span>Amount</span>
              <input
                data-attention-field="amount"
                inputMode="decimal"
                type="text"
                value={formValues.amount}
                onChange={(event) => updateFormValue("amount", event.target.value)}
              />
            </label>
            <label className={attentionFieldClass("direction")}>
              <span>Direction</span>
              <select
                data-attention-field="direction"
                value={formValues.direction}
                onChange={(event) => updateFormValue("direction", event.target.value as TransactionDirection)}
              >
                {transactionDirectionOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="modal-actions">
              <button disabled={isSaving} onClick={closeDialog} type="button">
                Cancel
              </button>
              <button disabled={isSaving} type="submit">
                {isSaving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

    </section>
  );
}

function LearnedRulesDialog({
  categoryOptions,
  onClose,
}: {
  categoryOptions: CategoryOption[];
  onClose: () => void;
}) {
  const [rules, setRules] = useState<CategoryRule[]>([]);
  const [terms, setTerms] = useState<StatementTerm[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<CategoryFormValues>({
    main_category: "PROFIT_LOSS_BUSINESS",
    subcategory: defaultSubcategoryFor(categoryOptions, "PROFIT_LOSS_BUSINESS"),
    use_for_future: false,
  });

  const loadRules = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const [nextRules, nextTerms] = await Promise.all([getCategoryRules(), getStatementTerms()]);
      setRules(nextRules);
      setTerms(nextTerms);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Learned rules could not be loaded.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  function startRuleEdit(rule: CategoryRule) {
    const mainCategory = isCategoryMainValue(rule.main_category) ? rule.main_category : "PROFIT_LOSS_BUSINESS";
    const subcategory = isCategorySubcategoryValue(rule.subcategory)
      ? rule.subcategory
      : defaultSubcategoryFor(categoryOptions, mainCategory);
    setEditingRuleId(rule.id);
    setEditValues({ main_category: mainCategory, subcategory, use_for_future: false });
    setError("");
  }

  async function saveRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editingRuleId === null) {
      return;
    }
    const validationMessage = validateCategoryForm(editValues, categoryOptions);
    if (validationMessage) {
      setError(validationMessage);
      return;
    }
    try {
      await updateCategoryRule(editingRuleId, {
        main_category: editValues.main_category,
        subcategory: editValues.subcategory,
      });
      setEditingRuleId(null);
      await loadRules();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Learned rule could not be saved.");
    }
  }

  async function removeRule(rule: CategoryRule) {
    if (!window.confirm(`Delete the learned rule for ${rule.pattern}? Historical categories will stay unchanged.`)) {
      return;
    }
    try {
      await deleteCategoryRule(rule.id);
      if (editingRuleId === rule.id) {
        setEditingRuleId(null);
      }
      await loadRules();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Learned rule could not be deleted.");
    }
  }

  async function confirmTerm(term: StatementTerm) {
    try {
      await confirmStatementTerm(term.id);
      await loadRules();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Statement terminology could not be confirmed.");
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="Learned category rules" aria-modal="true" className="learned-rules-dialog" role="dialog">
        <div className="learned-rules-dialog__header">
          <div>
            <h2>Learned Category Rules</h2>
            <p>These rules categorize future matching transactions. Historical edits are never rewritten.</p>
          </div>
          <button autoFocus onClick={onClose} type="button">Close</button>
        </div>
        {isLoading ? <div className="transaction-state">Loading learned rules...</div> : null}
        {error ? <div className="transaction-state transaction-state--error">{error}</div> : null}
        {!isLoading && rules.length === 0 ? (
          <div className="transaction-empty">No learned category rules yet.</div>
        ) : null}
        {rules.length > 0 ? (
          <div className="learned-rules-table-wrap">
            <table className="learned-rules-table">
              <thead>
                <tr><th>Merchant / Pattern</th><th>Category</th><th>Subcategory</th><th>Match</th><th>Confirmed</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id}>
                    <td>{rule.pattern}</td>
                    <td>{labelFor(categoryLabels, rule.main_category)}</td>
                    <td>{labelFor(subcategoryLabels, rule.subcategory)}</td>
                    <td>{rule.match_type === "NORMALIZED_NAME" ? "Exact merchant name" : labelFor({}, rule.match_type)}</td>
                    <td>{rule.times_confirmed}</td>
                    <td>
                      <div className="transaction-row-actions">
                        <button onClick={() => startRuleEdit(rule)} type="button">Edit</button>
                        <button className="danger-button" onClick={() => void removeRule(rule)} type="button">Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <div className="learned-rules-dialog__header">
          <div>
            <h2>Statement Terminology</h2>
            <p>Token and phrase meanings are scoped by institution and strengthen with confirmation.</p>
          </div>
        </div>
        {terms.length > 0 ? (
          <div className="learned-rules-table-wrap">
            <table className="learned-rules-table">
              <thead>
                <tr><th>Term</th><th>Meaning</th><th>Institution</th><th>Seen</th><th>Confirmed</th><th>Action</th></tr>
              </thead>
              <tbody>
                {terms.map((term) => (
                  <tr key={term.id}>
                    <td>{term.term}</td>
                    <td>{term.normalized_meaning}</td>
                    <td>{term.institution}</td>
                    <td>{term.times_seen}</td>
                    <td>{term.times_confirmed}</td>
                    <td><button onClick={() => void confirmTerm(term)} type="button">Confirm Meaning</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {editingRuleId !== null ? (
          <form className="learned-rule-edit" onSubmit={(event) => void saveRule(event)}>
            <label>
              <span>Category</span>
              <select
                value={editValues.main_category}
                onChange={(event) => {
                  const mainCategory = event.target.value as CategoryMainValue;
                  setEditValues({
                    main_category: mainCategory,
                    subcategory: defaultSubcategoryFor(categoryOptions, mainCategory),
                    use_for_future: false,
                  });
                }}
              >
                {categoryOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label>
              <span>Subcategory</span>
              <select
                value={editValues.subcategory}
                onChange={(event) => setEditValues((current) => ({
                  ...current,
                  subcategory: event.target.value as CategorySubcategoryValue,
                }))}
              >
                {subcategoryOptionsFor(categoryOptions, editValues.main_category).map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <div className="modal-actions">
              <button onClick={() => setEditingRuleId(null)} type="button">Cancel</button>
              <button type="submit">Save Rule</button>
            </div>
          </form>
        ) : null}
      </section>
    </div>
  );
}

function formatStorageSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MaintenancePage() {
  const [status, setStatus] = useState<MaintenanceStatus | null>(null);
  const [message, setMessage] = useState("Loading maintenance status...");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const restoreInput = useRef<HTMLInputElement>(null);

  const loadStatus = useCallback(async (integrity = false) => {
    setError("");
    try {
      setStatus(await getMaintenanceStatus(integrity));
      setMessage(integrity ? "Full database health check completed." : "Maintenance status is current.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Maintenance status could not be loaded.");
    }
  }, []);

  useEffect(() => { void loadStatus(); }, [loadStatus]);

  async function run(action: () => Promise<void>, success: string) {
    setBusy(true);
    setError("");
    try {
      await action();
      setMessage(success);
      await loadStatus();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Maintenance action failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRestore(file: File) {
    if (!window.confirm(
      "Restore this backup?\n\nCurrent data will be replaced by the selected backup. A safety backup of the current state will be created first.",
    )) return;
    await run(async () => {
      await restoreMaintenanceBackup(file);
      window.setTimeout(() => window.location.reload(), 500);
    }, "Backup restored. Reloading the application...");
  }

  return (
    <div className="maintenance-page">
      <header className="maintenance-header">
        <div>
          <p>Settings</p>
          <h2>Maintenance</h2>
          <span>Protect your local data and check application health.</span>
        </div>
        <span className={`maintenance-status maintenance-status--${status?.application.status ?? "attention"}`}>
          {status?.application.status === "healthy" ? "Healthy" : "Needs Attention"}
        </span>
      </header>

      <section className="maintenance-card maintenance-application">
        <h3>Application</h3>
        <dl>
          <div><dt>Version</dt><dd>{status?.application.version ?? "—"}</dd></div>
          <div><dt>Database</dt><dd>{status?.database.status === "healthy" ? "Healthy" : status?.database.status ?? "Checking"}</dd></div>
          <div><dt>Storage</dt><dd>{status?.storage.status === "healthy" ? "Healthy" : status?.storage.status ?? "Checking"}</dd></div>
        </dl>
        <button disabled={busy} onClick={() => void loadStatus(true)} type="button">Run Health Check</button>
      </section>

      <section className="maintenance-card">
        <h3>Backup</h3>
        <p>
          Last backup: {status?.backup.last_successful_at
            ? new Date(status.backup.last_successful_at).toLocaleString()
            : "No backup created yet"}
        </p>
        <div className="maintenance-actions">
          <button disabled={busy} onClick={() => void run(createMaintenanceBackup, "Backup created and downloaded.")} type="button">Create Backup</button>
          <button disabled={busy} onClick={() => restoreInput.current?.click()} type="button">Restore Backup</button>
          <button disabled={busy} onClick={() => void run(openBackupFolder, "Backup folder opened.")} type="button">Open Backup Folder</button>
        </div>
        <input
          accept=".zip,application/zip"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleRestore(file);
            event.currentTarget.value = "";
          }}
          ref={restoreInput}
          type="file"
        />
      </section>

      <section className="maintenance-card">
        <h3>Diagnostics</h3>
        <p>Creates a privacy-safe report without your database, statements, transactions, account data, or exports.</p>
        <button disabled={busy} onClick={() => void run(exportDiagnosticBundle, "Diagnostic bundle created and downloaded.")} type="button">Export Diagnostic Bundle</button>
      </section>

      <details className="maintenance-card maintenance-advanced">
        <summary>Advanced</summary>
        <dl>
          <div><dt>Schema revision</dt><dd>{status?.database.schema_revision ?? "Not initialized"}</dd></div>
          <div><dt>Retained files</dt><dd>{status?.storage.retained_file_count ?? 0}</dd></div>
          <div><dt>Storage size</dt><dd>{formatStorageSize(status?.storage.size_bytes ?? 0)}</dd></div>
          <div><dt>Data directory</dt><dd>{status?.paths.data ?? "—"}</dd></div>
          <div><dt>Log directory</dt><dd>{status?.paths.logs ?? "—"}</dd></div>
        </dl>
      </details>

      <p className={`maintenance-message ${error ? "maintenance-message--error" : ""}`} role="status">
        {error || (busy ? "Working..." : message)}
      </p>
    </div>
  );
}

function SummaryPage({ onOpenTransaction }: { onOpenTransaction: (transaction: SummaryTransaction) => void }) {
  const [summary, setSummary] = useState<ExpenseSummary | null>(null);
  const [mode, setMode] = useState<SummaryMode>("tax_year");
  const [taxYear, setTaxYear] = useState<number | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [drillDown, setDrillDown] = useState<SummaryDrillDown>(null);
  const [detailSearch, setDetailSearch] = useState("");
  const [sortBy, setSortBy] = useState<SummarySortBy>("date");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const requestIdRef = useRef(0);

  const loadSummary = useCallback(async (
    query: { taxYear: number } | { startDate: string; endDate: string } | Record<string, never> = {},
  ) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setIsLoading(true);
    setError("");
    try {
      const nextSummary = await getExpenseSummary(query);
      if (requestIdRef.current !== requestId) {
        return;
      }
      setSummary(nextSummary);
      if (nextSummary.period.mode === "TAX_YEAR") {
        setMode("tax_year");
        setTaxYear(nextSummary.period.tax_year);
      }
      setStartDate(nextSummary.period.start_date);
      setEndDate(nextSummary.period.end_date);
      setDrillDown(null);
    } catch (caught) {
      if (requestIdRef.current === requestId) {
        setError(caught instanceof Error ? caught.message : "Expense summary could not be loaded.");
      }
    } finally {
      if (requestIdRef.current === requestId) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const detailTransactions = useMemo(() => {
    const source = drillDown?.type === "subcategory"
      ? drillDown.subcategory.transactions
      : drillDown?.type === "review"
        ? drillDown.transactions
        : [];
    const query = detailSearch.trim().toLocaleLowerCase();
    const filtered = query
      ? source.filter((transaction) => [
          transaction.normalized_name,
          transaction.transaction_detail,
          transaction.institution,
          transaction.source_file,
        ].some((value) => value?.toLocaleLowerCase().includes(query)))
      : source;
    return [...filtered].sort((left, right) => {
      let comparison = 0;
      if (sortBy === "date") {
        comparison = left.transaction_date.localeCompare(right.transaction_date);
      } else if (sortBy === "name") {
        comparison = (left.normalized_name ?? left.transaction_detail).localeCompare(
          right.normalized_name ?? right.transaction_detail,
          undefined,
          { sensitivity: "base" },
        );
      } else if (sortBy === "amount") {
        comparison = moneyToCents(left.amount) - moneyToCents(right.amount);
      } else {
        comparison = `${left.institution} ${left.source_file}`.localeCompare(
          `${right.institution} ${right.source_file}`,
          undefined,
          { sensitivity: "base" },
        );
      }
      if (comparison === 0) {
        comparison = left.id - right.id;
      }
      return sortDirection === "asc" ? comparison : -comparison;
    });
  }, [detailSearch, drillDown, sortBy, sortDirection]);

  const drillDownTotalCents = useMemo(() => {
    const source = drillDown?.type === "subcategory"
      ? drillDown.subcategory.transactions
      : drillDown?.type === "review"
        ? drillDown.transactions
        : [];
    return source.reduce((total, transaction) => total + moneyToCents(transaction.amount), 0);
  }, [drillDown]);

  const availableYears = useMemo(() => {
    const years = new Set(summary?.period.available_years ?? []);
    if (taxYear !== null) {
      years.add(taxYear);
    }
    return [...years].sort((left, right) => right - left);
  }, [summary?.period.available_years, taxYear]);

  function currentQuery(): { taxYear: number } | { startDate: string; endDate: string } | null {
    if (mode === "tax_year") {
      return taxYear === null ? null : { taxYear };
    }
    if (!startDate || !endDate) {
      setError("Start date and end date are required.");
      return null;
    }
    if (startDate > endDate) {
      setError("Start date must be on or before end date.");
      return null;
    }
    return { startDate, endDate };
  }

  function refresh() {
    const query = currentQuery();
    if (query) {
      void loadSummary(query);
    }
  }

  function exportWorkbook() {
    const query = currentQuery();
    if (!query) {
      return;
    }
    const link = document.createElement("a");
    link.href = expenseSummaryExportUrl(query);
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function openSubcategory(group: SummaryGroup, subcategory: SummarySubcategory) {
    setDetailSearch("");
    setSortBy("date");
    setSortDirection("asc");
    setDrillDown({ type: "subcategory", group, subcategory });
  }

  function openReview() {
    if (!summary) {
      return;
    }
    setDetailSearch("");
    setSortBy("date");
    setSortDirection("asc");
    setDrillDown({ type: "review", transactions: summary.needs_review_transactions });
  }

  const periodTransactionCount = summary
    ? summary.metrics.included_eligible_count + summary.metrics.not_applicable_count + summary.metrics.unselected_count
    : 0;

  return (
    <div className="summary-page">
      <header className="summary-header">
        <div>
          <p className="summary-eyebrow">Combined expense report</p>
          <h2>{summary ? `${summary.period.label} Expense Summary` : "Expense Summary"}</h2>
          <p>Selected, eligible transactions from every analyzed statement.</p>
        </div>
        <div className={`summary-readiness ${summary?.readiness === "REVIEW_REQUIRED" ? "summary-readiness--review" : ""}`}>
          {summary?.readiness === "REVIEW_REQUIRED" ? "Review Required" : "Summary Ready"}
        </div>
      </header>

      <section className="summary-controls" aria-label="Reporting period">
        <label>
          <span>Reporting period</span>
          <select onChange={(event) => setMode(event.target.value as SummaryMode)} value={mode}>
            <option value="tax_year">Tax Year</option>
            <option value="custom">Custom Date Range</option>
          </select>
        </label>
        {mode === "tax_year" ? (
          <label>
            <span>Tax year</span>
            <select
              disabled={availableYears.length === 0}
              onChange={(event) => setTaxYear(Number(event.target.value))}
              value={taxYear ?? ""}
            >
              {availableYears.map((year) => <option key={year} value={year}>{year}</option>)}
            </select>
          </label>
        ) : (
          <>
            <label>
              <span>Start date</span>
              <input onChange={(event) => setStartDate(event.target.value)} type="date" value={startDate} />
            </label>
            <label>
              <span>End date</span>
              <input onChange={(event) => setEndDate(event.target.value)} type="date" value={endDate} />
            </label>
          </>
        )}
        <div className="summary-control-actions">
          <button disabled={isLoading} onClick={refresh} type="button">{isLoading ? "Refreshing..." : "Refresh"}</button>
          <button disabled={!summary || isLoading} onClick={exportWorkbook} type="button">Export Excel</button>
        </div>
      </section>

      {error ? <p className="summary-message summary-message--error" role="alert">{error}</p> : null}
      {isLoading && !summary ? <div className="summary-message">Loading expense summary...</div> : null}

      {summary ? (
        <>
          <section className="summary-overview" aria-label="Summary overview">
            <article>
              <span>Included Expenses</span>
              <strong>{formatMoney(summary.grand_total)}</strong>
            </article>
            <article>
              <span>Included Transactions</span>
              <strong>{summary.metrics.contributing_transaction_count}</strong>
            </article>
            <button
              className={summary.metrics.needs_review_count > 0 ? "summary-overview__review" : ""}
              disabled={summary.metrics.needs_review_count === 0}
              onClick={openReview}
              type="button"
            >
              <span>Needs Review</span>
              <strong>{summary.metrics.needs_review_count}</strong>
            </button>
            <article>
              <span>Statements / Sources</span>
              <strong>{summary.metrics.source_count}</strong>
            </article>
          </section>

          {summary.metrics.needs_review_count > 0 ? (
            <button className="summary-review-warning" onClick={openReview} type="button">
              <strong>{summary.metrics.needs_review_count} included {summary.metrics.needs_review_count === 1 ? "transaction needs" : "transactions need"} review</strong>
              <span>Open the unresolved transactions and return to their source records.</span>
            </button>
          ) : null}

          {summary.metrics.selected_non_expense_count > 0 ? (
            <div className="summary-message summary-message--review">
              {summary.metrics.selected_non_expense_count} selected {summary.metrics.selected_non_expense_count === 1 ? "transaction is" : "transactions are"} excluded because the saved transaction type is not expense-eligible (for example, a payment, transfer, income, or refund).
            </div>
          ) : null}

          {periodTransactionCount === 0 ? (
            <div className="summary-message">No analyzed transactions available for this reporting period.</div>
          ) : summary.metrics.included_eligible_count === 0 ? (
            <div className="summary-message">No included expenses for this reporting period.</div>
          ) : summary.metrics.contributing_transaction_count === 0 ? (
            <div className="summary-message summary-message--review">Included transactions require category review before they can contribute to totals.</div>
          ) : null}

          <div className="summary-groups">
            {summary.groups.map((group) => (
              <section className="summary-group" key={group.id}>
                <header>
                  <div>
                    <h3>{group.label}</h3>
                    <span>{group.transaction_count} {group.transaction_count === 1 ? "transaction" : "transactions"}</span>
                  </div>
                  <strong>{formatMoney(group.total)}</strong>
                </header>
                <div className="summary-category-list">
                  {group.subcategories.map((subcategory) => (
                    <button
                      className="summary-category-row"
                      key={subcategory.id}
                      onClick={() => openSubcategory(group, subcategory)}
                      type="button"
                    >
                      <span className="summary-category-row__name">{subcategory.label}</span>
                      <span>{subcategory.transaction_count} {subcategory.transaction_count === 1 ? "transaction" : "transactions"}</span>
                      <strong>{formatMoney(subcategory.total)}</strong>
                      <span aria-hidden="true" className="summary-category-row__arrow">›</span>
                    </button>
                  ))}
                </div>
                <footer>
                  <strong>Total {group.label}</strong>
                  <strong>{formatMoney(group.total)}</strong>
                </footer>
              </section>
            ))}
          </div>

          <div className="summary-grand-total">
            <div>
              <span>Total Included Expenses</span>
              <small>{summary.metrics.contributing_transaction_count} selected, eligible transactions</small>
            </div>
            <strong>{formatMoney(summary.grand_total)}</strong>
          </div>
        </>
      ) : null}

      {drillDown ? (
        <div className="modal-backdrop summary-detail-backdrop" role="presentation">
          <section aria-modal="true" className="summary-detail-dialog" role="dialog">
            <header className="summary-detail-header">
              <div>
                <p>{drillDown.type === "subcategory" ? drillDown.group.label : "Included Expenses"}</p>
                <h2>{drillDown.type === "subcategory" ? drillDown.subcategory.label : "Needs Review"}</h2>
                <span>
                  {drillDown.type === "subcategory"
                    ? `${drillDown.subcategory.transaction_count} contributing ${drillDown.subcategory.transaction_count === 1 ? "transaction" : "transactions"}`
                    : `${drillDown.transactions.length} unresolved included ${drillDown.transactions.length === 1 ? "transaction" : "transactions"}`}
                </span>
              </div>
              <div className="summary-detail-total">
                <span>{drillDown.type === "subcategory" ? "Drill-down total" : "Unresolved amount"}</span>
                <strong>{formatMoneyCents(drillDownTotalCents)}</strong>
              </div>
              <button autoFocus onClick={() => setDrillDown(null)} type="button">Close</button>
            </header>

            <div className="summary-detail-controls">
              <label className="summary-detail-search">
                <span>Search transactions</span>
                <input
                  onChange={(event) => setDetailSearch(event.target.value)}
                  placeholder="Name, detail, institution, or source file"
                  type="search"
                  value={detailSearch}
                />
              </label>
              <label>
                <span>Sort by</span>
                <select onChange={(event) => setSortBy(event.target.value as SummarySortBy)} value={sortBy}>
                  <option value="date">Date</option>
                  <option value="name">Name</option>
                  <option value="amount">Amount</option>
                  <option value="source">Source</option>
                </select>
              </label>
              <label>
                <span>Direction</span>
                <select onChange={(event) => setSortDirection(event.target.value as "asc" | "desc")} value={sortDirection}>
                  <option value="asc">Ascending</option>
                  <option value="desc">Descending</option>
                </select>
              </label>
            </div>

            {detailTransactions.length === 0 ? (
              <div className="summary-detail-empty">
                {detailSearch ? "No contributing transactions match this search." : "No transactions contribute to this category."}
              </div>
            ) : (
              <div className="summary-detail-table-wrap">
                <table className="summary-detail-table">
                  <thead>
                    <tr>
                      <th>Date</th><th>Name</th><th>Transaction Detail</th><th>Source / Institution</th>
                      <th>Source File</th><th>Amount</th><th>Category</th><th>Subcategory</th><th>Review Status</th><th>Source Record</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailTransactions.map((transaction) => (
                      <tr key={transaction.id}>
                        <td>{formatDateOnly(transaction.transaction_date)}</td>
                        <td>{transaction.normalized_name ?? "—"}</td>
                        <td>{transaction.transaction_detail}</td>
                        <td>{transaction.institution}</td>
                        <td>
                          <span>{transaction.source_file}</span>
                          {!transaction.source_file_available ? <small>Source file no longer retained. Transaction record preserved.</small> : null}
                        </td>
                        <td className="summary-detail-table__amount">{formatMoney(transaction.amount)}</td>
                        <td>{transaction.main_category_label ?? "Needs Review"}</td>
                        <td>{transaction.subcategory_label ?? "Needs Review"}</td>
                        <td>{transaction.review_status === "REVIEWED" ? "Reviewed" : labelFor({}, transaction.category_status)}</td>
                        <td>
                          <button
                            disabled={!transaction.source_file_available}
                            onClick={() => onOpenTransaction(transaction)}
                            type="button"
                          >
                            {transaction.source_file_available ? "Open Transaction" : "Unavailable"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={5}>Exact total</td>
                      <td className="summary-detail-table__amount">{formatMoneyCents(drillDownTotalCents)}</td>
                      <td colSpan={4}></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
            {detailSearch ? <p className="summary-detail-filter-note">Showing {detailTransactions.length} of {drillDown.type === "subcategory" ? drillDown.subcategory.transactions.length : drillDown.transactions.length} transactions. The exact total above is not changed by search.</p> : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}

function PreviewPane({ file }: { file: StoredFile }) {
  const previewType = fileCanPreview(file);
  const [previewState, setPreviewState] = useState<PreviewState>(
    previewType === "unsupported"
      ? { status: "unsupported" }
      : previewType === "pdf"
        ? { status: "ready", objectUrl: filePreviewUrl(file.id) }
        : { status: "loading" },
  );

  useEffect(() => {
    if (previewType === "unsupported") {
      setPreviewState({ status: "unsupported" });
      return;
    }
    if (previewType === "pdf") {
      setPreviewState({ status: "ready", objectUrl: filePreviewUrl(file.id) });
      return;
    }

    const controller = new AbortController();
    let objectUrl: string | null = null;
    let isActive = true;

    setPreviewState({ status: "loading" });

    void fetch(filePreviewUrl(file.id), { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          let message = "Preview could not be loaded.";
          try {
            const data = (await response.json()) as { detail?: unknown };
            if (typeof data.detail === "string") {
              message = data.detail;
            }
          } catch {
            message = response.status === 404 ? "Stored file is missing." : message;
          }
          throw new Error(message);
        }
        const blob = await response.blob();
        const nextUrl = URL.createObjectURL(blob);
        if (!isActive) {
          URL.revokeObjectURL(nextUrl);
          return;
        }
        objectUrl = nextUrl;
        setPreviewState({ status: "ready", objectUrl: nextUrl });
      })
      .catch((caught) => {
        if (controller.signal.aborted || !isActive) {
          return;
        }
        setPreviewState({
          status: "error",
          message: caught instanceof Error ? caught.message : "Preview could not be loaded.",
        });
      });

    return () => {
      isActive = false;
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [file.id, previewType]);

  if (previewState.status === "unsupported") {
    return (
      <div className="unsupported-preview">
        Preview is not available for this file type. Use Download to open it locally.
      </div>
    );
  }

  if (previewState.status === "loading") {
    return <div className="preview-status" aria-live="polite">Loading preview...</div>;
  }

  if (previewState.status === "error") {
    return (
      <div className="unsupported-preview" aria-live="polite">
        {previewState.message}
      </div>
    );
  }

  if (previewType === "image") {
    return (
      <div className="preview-surface">
        <img
          alt={file.display_name}
          onError={() =>
            setPreviewState({ status: "error", message: "Image preview could not be displayed." })
          }
          src={previewState.objectUrl}
        />
      </div>
    );
  }

  return <iframe className="pdf-preview" src={previewState.objectUrl} title={file.display_name} />;
}
