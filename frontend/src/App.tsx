import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import "./App.css";
import {
  analyzeStatementFile,
  bulkUpdateTransactionReview,
  bulkUpdateTransactionCategories,
  bulkUpdateTransactionInclusion,
  createTransactionForStatement,
  createFolder,
  deleteFolder,
  deleteStoredFile,
  excludeTransaction,
  fileDownloadUrl,
  filePreviewUrl,
  getAttention,
  getAttentionCount,
  getFileManagerTree,
  getStatementForFile,
  getTransactionsForStatement,
  searchFileManager,
  updateFolder,
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
  StoredFile,
  CategoryMainValue,
  CategorySubcategoryValue,
  TransactionDirection,
  TransactionExtraction,
  TransactionCategoryBulkPayload,
  TransactionCategoryPayload,
  TransactionInclusionBulkPayload,
  TransactionInclusionPayload,
  TransactionNormalizationPayload,
  TransactionPayload,
  TransactionReviewBulkPayload,
  TransactionTypeValue,
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
};

type TransactionDialogState = { mode: "add" } | null;

type NormalizationFilter = "all" | "normalized" | "needs_review" | "user_edited" | "unresolved";

type CategoryFilter =
  | "all"
  | "auto"
  | "home"
  | "business"
  | "personal"
  | "uncategorized"
  | "needs_review"
  | "not_applicable";

type InclusionFilter = "all" | "included" | "excluded" | "needs_review" | "reviewed";

type CategoryFormValues = {
  main_category: CategoryMainValue;
  subcategory: CategorySubcategoryValue;
  use_for_future: boolean;
};

type BulkCategoryFormValues = {
  main_category: CategoryMainValue;
  subcategory: CategorySubcategoryValue;
  overwrite_user_edits: boolean;
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
  PERSONAL_INTERNAL: "PERSONAL / INTERNAL",
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
  BUSINESS_OTHER_SUPPLIES: "Other Supplies",
  BUSINESS_TRAVEL: "Travel",
  BUSINESS_TOTAL_MEALS: "Total Meals",
  BUSINESS_TRANSPORTATION: "Transportation",
  BUSINESS_GOVERNMENT: "Government",
  BUSINESS_DONATIONS: "Donations",
  BUSINESS_BANK_MEMBERSHIP: "Bank Membership",
  BUSINESS_MEDICAL: "Medical",
  BUSINESS_EDUCATION_LEARNING: "Education & Learning",
  PERSONAL_OTHER_ITEMS: "Other Personal Items",
  PERSONAL: "Personal",
  UNCATEGORIZED: "Uncategorized",
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

const categoryOptions: Array<{ value: CategoryMainValue; label: string; subcategories: Array<{ value: CategorySubcategoryValue; label: string }> }> = [
  {
    value: "AUTO_EXPENSE",
    label: "AUTO EXPENSE",
    subcategories: [
      { value: "AUTO_GAS", label: "Gas" },
      { value: "AUTO_INSURANCE", label: "Insurance" },
      { value: "AUTO_MAINTENANCE", label: "Car Maintenance" },
      { value: "AUTO_PARKING", label: "Parking Fee" },
      { value: "AUTO_TIRES", label: "Tires" },
      { value: "AUTO_TOLLS", label: "Tolls" },
      { value: "AUTO_CAR_PAYMENT", label: "Car Payment" },
    ],
  },
  {
    value: "BUSINESS_USE_OF_HOME",
    label: "BUSINESS USE OF HOME",
    subcategories: [
      { value: "HOME_INSURANCE", label: "Insurance" },
      { value: "HOME_RENT", label: "Rent" },
      { value: "HOME_REPAIRS_MAINTENANCE", label: "Repairs and Maintenance" },
      { value: "HOME_UTILITIES", label: "Utilities" },
      { value: "HOME_TELECOM_INTERNET", label: "Telecom/Internet" },
      { value: "HOME_OTHER_EXPENSE", label: "Other Expense" },
    ],
  },
  {
    value: "PROFIT_LOSS_BUSINESS",
    label: "PROFIT OR LOSS FROM BUSINESS",
    subcategories: [
      { value: "BUSINESS_MATERIALS", label: "Materials" },
      { value: "BUSINESS_ADVERTISING", label: "Advertising" },
      { value: "BUSINESS_INTEREST_OTHER", label: "Interest - Other" },
      { value: "BUSINESS_LEGAL_PROFESSIONAL", label: "Legal and Professional Services" },
      { value: "BUSINESS_OFFICE_EXPENSE", label: "Office Expense" },
      { value: "BUSINESS_OTHER_SUPPLIES", label: "Other Supplies" },
      { value: "BUSINESS_TRAVEL", label: "Travel" },
      { value: "BUSINESS_TOTAL_MEALS", label: "Total Meals" },
      { value: "BUSINESS_TRANSPORTATION", label: "Transportation" },
      { value: "BUSINESS_GOVERNMENT", label: "Government" },
      { value: "BUSINESS_DONATIONS", label: "Donations" },
      { value: "BUSINESS_BANK_MEMBERSHIP", label: "Bank Membership" },
      { value: "BUSINESS_MEDICAL", label: "Medical" },
      { value: "BUSINESS_EDUCATION_LEARNING", label: "Education & Learning" },
    ],
  },
  {
    value: "PERSONAL_INTERNAL",
    label: "PERSONAL / INTERNAL",
    subcategories: [
      { value: "PERSONAL_OTHER_ITEMS", label: "Other Personal Items" },
      { value: "PERSONAL", label: "Personal" },
      { value: "UNCATEGORIZED", label: "Uncategorized" },
    ],
  },
];

const categoryFilterOptions: Array<{ value: CategoryFilter; label: string }> = [
  { value: "all", label: "All Categories" },
  { value: "auto", label: "Auto Expense" },
  { value: "home", label: "Business Use of Home" },
  { value: "business", label: "Profit or Loss From Business" },
  { value: "personal", label: "Personal / Internal" },
  { value: "uncategorized", label: "Uncategorized" },
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
  return categoryOptions.some((option) => option.value === value);
}

function isCategorySubcategoryValue(value: string | null | undefined): value is CategorySubcategoryValue {
  return categoryOptions.some((option) => option.subcategories.some((subcategory) => subcategory.value === value));
}

function subcategoryOptionsFor(mainCategory: CategoryMainValue): Array<{ value: CategorySubcategoryValue; label: string }> {
  return categoryOptions.find((option) => option.value === mainCategory)?.subcategories ?? [];
}

function defaultSubcategoryFor(mainCategory: CategoryMainValue): CategorySubcategoryValue {
  return subcategoryOptionsFor(mainCategory)[0]?.value ?? "UNCATEGORIZED";
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
    return "Uncategorized";
  }
  return `${labelFor(categoryLabels, mainCategory)} / ${labelFor(subcategoryLabels, subcategory)}`;
}

function transactionMatchesCategoryFilter(transaction: StatementTransaction, filter: CategoryFilter): boolean {
  const mainCategory = categoryMainValue(transaction);
  const subcategory = categorySubcategoryValue(transaction);
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
  if (filter === "personal") {
    return mainCategory === "PERSONAL_INTERNAL";
  }
  if (filter === "uncategorized") {
    return subcategory === "UNCATEGORIZED" || status === "NOT_CATEGORIZED";
  }
  if (filter === "needs_review") {
    return status === "NEEDS_REVIEW";
  }
  return status === "NOT_APPLICABLE";
}

function validateCategoryForm(values: CategoryFormValues): string {
  if (!isCategoryMainValue(values.main_category)) {
    return "Main category is required.";
  }
  if (!subcategoryOptionsFor(values.main_category).some((option) => option.value === values.subcategory)) {
    return "Subcategory is not valid for the selected main category.";
  }
  return "";
}

function bulkCategoryPayloadFromValues(
  selectedTransactionIds: number[],
  values: BulkCategoryFormValues,
): TransactionCategoryBulkPayload {
  return {
    transaction_ids: selectedTransactionIds,
    main_category: values.main_category,
    subcategory: values.subcategory,
    overwrite_user_edits: values.overwrite_user_edits,
  };
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
    categoryStatus(transaction) === "NOT_CATEGORIZED" ||
    categorySubcategoryValue(transaction) === "UNCATEGORIZED"
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

function inlineEditValuesFromTransaction(transaction: StatementTransaction): InlineTransactionEditValues {
  const mainCategory = categoryMainValue(transaction) ?? "PERSONAL_INTERNAL";
  const subcategory = categorySubcategoryValue(transaction);
  const validSubcategories = subcategoryOptionsFor(mainCategory);
  return {
    ...transactionToFormValues(transaction),
    normalized_name: transaction.normalized_name ?? "",
    main_category: mainCategory,
    subcategory: subcategory && validSubcategories.some((option) => option.value === subcategory)
      ? subcategory
      : defaultSubcategoryFor(mainCategory),
  };
}

function validateInlineTransactionEdit(
  values: InlineTransactionEditValues,
  transaction: StatementTransaction,
): string {
  const transactionValidation = validateTransactionForm(values);
  if (transactionValidation) {
    return transactionValidation;
  }
  const initialValues = inlineEditValuesFromTransaction(transaction);
  if (values.normalized_name !== initialValues.normalized_name && !values.normalized_name.trim()) {
    return "Name is required.";
  }
  return validateCategoryForm({ ...values, use_for_future: false });
}

function inlineTransactionEditIsDirty(
  transaction: StatementTransaction,
  values: InlineTransactionEditValues,
): boolean {
  const initialValues = inlineEditValuesFromTransaction(transaction);
  return (
    values.transaction_date !== initialValues.transaction_date ||
    values.transaction_detail !== initialValues.transaction_detail ||
    moneyToCents(values.amount) !== moneyToCents(initialValues.amount) ||
    values.direction !== initialValues.direction ||
    values.normalized_name !== initialValues.normalized_name ||
    values.main_category !== initialValues.main_category ||
    values.subcategory !== initialValues.subcategory
  );
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
  const [selected, setSelected] = useState<SelectedItem>({ type: "root" });
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
    void refreshAttention();
  }, [refreshAttention]);

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
    setSelected({ type: "folder", id: folderId });
  }

  function selectFile(fileId: number) {
    setAttentionFocusTarget(null);
    setSelected({ type: "file", id: fileId });
  }

  function selectRoot() {
    setAttentionFocusTarget(null);
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
            <button onClick={handleCreateFolder} type="button">
              New Folder
            </button>
            <button onClick={() => fileInputRef.current?.click()} type="button">
              Upload
            </button>
          </div>
        </div>
      </header>

      <section className="manager-toolbar" aria-label="File manager controls">
        <div className="search-box">
          <label htmlFor="file-search">Search</label>
          <div className="search-input-wrap">
            <input
              aria-controls="file-search-results"
              aria-expanded={isSearchOpen}
              autoComplete="off"
              id="file-search"
              onChange={(event) => setSearch(event.target.value)}
              onFocus={() => {
                if (search.trim()) {
                  setIsSearchOpen(true);
                }
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setIsSearchOpen(false);
                }
              }}
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
                      {result.type === "file" && result.file_size !== null ? (
                        <span className="search-result-row__meta">{formatBytes(result.file_size)}</span>
                      ) : null}
                    </button>
                  ))
                : null}
            </div>
          ) : null}
        </div>
        <label>
          <span>Sort</span>
          <select onChange={(event) => setSortBy(event.target.value as SortBy)} value={sortBy}>
            {sortOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Direction</span>
          <select
            onChange={(event) => setSortDirection(event.target.value as SortDirection)}
            value={sortDirection}
          >
            <option value="asc">Ascending</option>
            <option value="desc">Descending</option>
          </select>
        </label>
        <button onClick={() => void loadTree()} type="button">
          Refresh
        </button>
      </section>

      <nav className="breadcrumbs" aria-label="Breadcrumbs">
        <button onClick={selectRoot} type="button">
          My Files
        </button>
        {breadcrumbs.map((folder) => (
          <span key={folder.id}>
            <span className="breadcrumb-separator">/</span>
            <button onClick={() => selectFolder(folder.id)} type="button">
              {folder.name}
            </button>
          </span>
        ))}
        {selectedFile ? (
          <span>
            <span className="breadcrumb-separator">/</span>
            <button onClick={() => selectFile(selectedFile.id)} type="button">
              {selectedFile.display_name}
            </button>
          </span>
        ) : null}
      </nav>

      <section className="manager-layout" aria-label="File manager">
        <aside className="tree-pane" aria-label="Folders and files">
          <div className="pane-header">
            <h2>My Files</h2>
            <span>{isLoading ? "Loading" : `${tree.folders.length + tree.files.length} root items`}</span>
          </div>
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
        </aside>

        <section className="details-pane" aria-label="Selected item details">
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

          <p className={`notice ${error ? "notice--error" : ""}`}>{error || notice}</p>

          {selectedFile ? (
            <FileDetails
              attentionTarget={attentionFocusTarget?.fileId === selectedFile.id ? attentionFocusTarget : null}
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
        </section>
      </section>

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
  file,
  locationPath,
  onAttentionRefresh,
  onAttentionTargetConsumed,
  onTreeRefresh,
}: {
  attentionTarget: AttentionFocusTarget | null;
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

  async function handleBulkUpdateTransactionCategories(payload: TransactionCategoryBulkPayload): Promise<number[]> {
    if (!statement) {
      return [];
    }
    setTransactionError("");
    const response = await bulkUpdateTransactionCategories(payload);
    await refreshTransactions(statement.id);
    await onAttentionRefresh();
    return response.skipped_transaction_ids;
  }

  async function handleBulkUpdateTransactionInclusion(payload: TransactionInclusionBulkPayload): Promise<number[]> {
    setTransactionError("");
    const response = await bulkUpdateTransactionInclusion(payload);
    setTransactions((current) => mergeUpdatedTransactions(current, response.transactions));
    await onAttentionRefresh();
    return response.skipped_transaction_ids;
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

  return (
    <div className="details-content">
      <dl className="metadata-grid">
        <div>
          <dt>Filename</dt>
          <dd>{file.display_name}</dd>
        </div>
        <div>
          <dt>File Type</dt>
          <dd>{file.mime_type}</dd>
        </div>
        <div>
          <dt>File Size</dt>
          <dd>{formatBytes(file.file_size)}</dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>{locationPath}</dd>
        </div>
        <div>
          <dt>Uploaded</dt>
          <dd>{formatDate(file.created_at)}</dd>
        </div>
        <div>
          <dt>Modified</dt>
          <dd>{formatDate(file.updated_at)}</dd>
        </div>
      </dl>

      <div className="preview-header">
        <h3>Preview</h3>
        <a className="download-link" href={fileDownloadUrl(file.id)}>
          Download
        </a>
      </div>

      <PreviewPane file={file} />
      {isPdf || statement ? (
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
          onAnalyze={handleAnalyzeStatement}
          onSave={handleSaveStatement}
          onAttentionTargetConsumed={onAttentionTargetConsumed}
          statement={statement}
        />
      ) : null}
      {statement ? (
        <TransactionPanel
          error={transactionError}
          isAnalyzing={isAnalyzing}
          isLoading={isTransactionsLoading}
          latestExtraction={latestExtraction}
          onAdd={handleCreateTransaction}
          onBulkEditCategories={handleBulkUpdateTransactionCategories}
          onEdit={handleUpdateTransaction}
          onEditNormalization={handleUpdateTransactionNormalization}
          onEditCategory={handleUpdateTransactionCategory}
          onEditInclusion={handleUpdateTransactionInclusion}
          onExclude={handleExcludeTransaction}
          onBulkEditInclusion={handleBulkUpdateTransactionInclusion}
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
    </div>
  );
}

function StatementPanel({
  analysisNotice,
  analysisSteps,
  attentionTarget,
  error,
  isAnalyzing,
  isLoading,
  onAnalyze,
  onAttentionTargetConsumed,
  onSave,
  statement,
}: {
  analysisNotice: string;
  analysisSteps: AnalysisStep[];
  attentionTarget: AttentionFocusTarget | null;
  error: string;
  isAnalyzing: boolean;
  isLoading: boolean;
  onAnalyze: () => void;
  onAttentionTargetConsumed: () => void;
  onSave: (payload: StatementUpdate) => Promise<void>;
  statement: StatementDetection | null;
}) {
  const [editValues, setEditValues] = useState<StatementEditValues | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [editError, setEditError] = useState("");
  const [activeAttentionField, setActiveAttentionField] = useState<string | null>(null);
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

  return (
    <section className="statement-panel" aria-label="Statement information">
      <div className="statement-panel__header">
        <div>
          <h3>{isEditing ? "Edit Statement Details" : "Statement Information"}</h3>
          <p>{subtitle}</p>
        </div>
        <div className="statement-actions">
          {statement && !isEditing ? (
            <button disabled={isBusy} onClick={startEditing} type="button">
              Edit Details
            </button>
          ) : null}
          <button disabled={isBusy} onClick={onAnalyze} type="button">
            {isAnalyzing ? "Analyzing..." : buttonText}
          </button>
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

      {statement && !isEditing ? (
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
  error,
  isAnalyzing,
  isLoading,
  latestExtraction,
  onAdd,
  onBulkEditCategories,
  onBulkEditInclusion,
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
  error: string;
  isAnalyzing: boolean;
  isLoading: boolean;
  latestExtraction: TransactionExtraction | null;
  onAdd: (payload: Required<TransactionPayload>) => Promise<void>;
  onBulkEditCategories: (payload: TransactionCategoryBulkPayload) => Promise<number[]>;
  onBulkEditInclusion: (payload: TransactionInclusionBulkPayload) => Promise<number[]>;
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
  const [selectedTransactionIds, setSelectedTransactionIds] = useState<Set<number>>(new Set());
  const [bulkCategoryFormValues, setBulkCategoryFormValues] = useState<BulkCategoryFormValues>({
    main_category: "PERSONAL_INTERNAL",
    subcategory: "UNCATEGORIZED",
    overwrite_user_edits: false,
  });
  const [bulkCategoryError, setBulkCategoryError] = useState("");
  const [bulkCategoryNotice, setBulkCategoryNotice] = useState("");
  const [isSavingBulkCategory, setIsSavingBulkCategory] = useState(false);
  const [isSavingBulkInclusion, setIsSavingBulkInclusion] = useState(false);
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
  const bulkHeaderCheckboxRef = useRef<HTMLInputElement>(null);
  const inclusionHeaderCheckboxRef = useRef<HTMLInputElement>(null);
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
  const selectedIds = useMemo(() => Array.from(selectedTransactionIds), [selectedTransactionIds]);
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
  const visibleTransactionIds = useMemo(
    () => sortedTransactions.map((transaction) => transaction.id),
    [sortedTransactions],
  );
  const allVisibleBulkSelected =
    visibleTransactionIds.length > 0 && visibleTransactionIds.every((transactionId) => selectedTransactionIds.has(transactionId));
  const visibleIncludedCount = sortedTransactions.filter(transactionIncluded).length;
  const allVisibleIncluded = sortedTransactions.length > 0 && visibleIncludedCount === sortedTransactions.length;
  const someVisibleIncluded = visibleIncludedCount > 0 && visibleIncludedCount < sortedTransactions.length;
  const editingTransaction = useMemo(
    () => transactions.find((transaction) => transaction.id === editingTransactionId) ?? null,
    [editingTransactionId, transactions],
  );
  const hasUnsavedInlineEdit = useCallback(() => {
    if (!editingTransaction || !inlineEditValues) {
      return false;
    }
    return inlineTransactionEditIsDirty(editingTransaction, inlineEditValues);
  }, [editingTransaction, inlineEditValues]);
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
      setInlineEditValues(inlineEditValuesFromTransaction(transaction));
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
    [editingTransactionId, hasUnsavedInlineEdit],
  );

  useEffect(() => {
    if (bulkHeaderCheckboxRef.current) {
      bulkHeaderCheckboxRef.current.indeterminate =
        visibleTransactionIds.some((transactionId) => selectedTransactionIds.has(transactionId)) && !allVisibleBulkSelected;
    }
  }, [allVisibleBulkSelected, selectedTransactionIds, visibleTransactionIds]);

  useEffect(() => {
    if (inclusionHeaderCheckboxRef.current) {
      inclusionHeaderCheckboxRef.current.indeterminate = someVisibleIncluded;
    }
  }, [someVisibleIncluded]);

  useEffect(() => {
    setSelectedTransactionIds((current) => {
      const availableIds = new Set(transactions.map((transaction) => transaction.id));
      const next = new Set([...current].filter((transactionId) => availableIds.has(transactionId)));
      return next.size === current.size ? current : next;
    });
  }, [transactions]);

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
          subcategory: defaultSubcategoryFor(value),
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

    const validationMessage = validateInlineTransactionEdit(inlineEditValues, transaction);
    if (validationMessage) {
      setInlineEditError(validationMessage);
      return;
    }

    const initialValues = inlineEditValuesFromTransaction(transaction);
    const corePayload = transactionPayloadChanges(transaction, inlineEditValues);
    const normalizedNameChanged = inlineEditValues.normalized_name !== initialValues.normalized_name;
    const categoryChanged =
      inlineEditValues.main_category !== initialValues.main_category ||
      inlineEditValues.subcategory !== initialValues.subcategory;

    if (
      !hasPayloadChanges(corePayload) &&
      !normalizedNameChanged &&
      !categoryChanged
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
      if (categoryChanged) {
        await onEditCategory(transaction.id, {
          main_category: inlineEditValues.main_category,
          subcategory: inlineEditValues.subcategory,
          use_for_future: false,
        });
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

  function updateBulkCategoryFormValue(field: "main_category", value: CategoryMainValue): void;
  function updateBulkCategoryFormValue(field: "subcategory", value: CategorySubcategoryValue): void;
  function updateBulkCategoryFormValue(field: "overwrite_user_edits", value: boolean): void;
  function updateBulkCategoryFormValue(
    field: keyof BulkCategoryFormValues,
    value: CategoryMainValue | CategorySubcategoryValue | boolean,
  ) {
    if (field === "main_category" && typeof value === "string" && isCategoryMainValue(value)) {
      setBulkCategoryFormValues((current) => ({
        ...current,
        main_category: value,
        subcategory: defaultSubcategoryFor(value),
      }));
    }
    if (field === "subcategory" && typeof value === "string" && isCategorySubcategoryValue(value)) {
      setBulkCategoryFormValues((current) => ({ ...current, subcategory: value }));
    }
    if (field === "overwrite_user_edits" && typeof value === "boolean") {
      setBulkCategoryFormValues((current) => ({ ...current, overwrite_user_edits: value }));
    }
  }

  function toggleTransactionSelection(transactionId: number, checked: boolean) {
    setSelectedTransactionIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(transactionId);
      } else {
        next.delete(transactionId);
      }
      return next;
    });
    setBulkCategoryError("");
    setBulkCategoryNotice("");
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

  async function handleBulkInclusion(transactionIds: number[], include: boolean, scopeLabel: string) {
    if (transactionIds.length === 0) {
      setInclusionError("No transactions match this action.");
      setInclusionNotice("");
      return;
    }
    setIsSavingBulkInclusion(true);
    setInclusionError("");
    setInclusionNotice("");
    try {
      const skippedIds = await onBulkEditInclusion({
        transaction_ids: transactionIds,
        include_in_expenses: include,
      });
      const changedCount = transactionIds.length - skippedIds.length;
      setInclusionNotice(
        `${include ? "Included" : "Excluded"} ${changedCount} ${scopeLabel} transaction${changedCount === 1 ? "" : "s"}.`,
      );
    } catch (caught) {
      setInclusionError(caught instanceof Error ? caught.message : "Could not save transaction selections.");
    } finally {
      setIsSavingBulkInclusion(false);
    }
  }

  function handleAllTransactionsInclusion(include: boolean) {
    const action = include ? "Select" : "Deselect";
    const confirmed = window.confirm(
      `${action} all ${transactions.length} transactions?\n\nThis will replace your current transaction selections.`,
    );
    if (!confirmed) {
      return;
    }
    void handleBulkInclusion(transactions.map((transaction) => transaction.id), include, "total");
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

  function attentionCellClass(field: string, extraClass = ""): string {
    return [
      extraClass,
      activeAttentionFocus?.targetField === field ? "transaction-cell--attention" : "",
    ].filter(Boolean).join(" ");
  }

  function toggleVisibleTransactions(checked: boolean) {
    setSelectedTransactionIds((current) => {
      const next = new Set(current);
      visibleTransactionIds.forEach((transactionId) => {
        if (checked) {
          next.add(transactionId);
        } else {
          next.delete(transactionId);
        }
      });
      return next;
    });
    setBulkCategoryError("");
    setBulkCategoryNotice("");
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

  async function handleSubmitBulkCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedIds.length === 0) {
      setBulkCategoryError("Select at least one transaction.");
      setBulkCategoryNotice("");
      return;
    }

    const formErrorMessage = validateCategoryForm({ ...bulkCategoryFormValues, use_for_future: false });
    if (formErrorMessage) {
      setBulkCategoryError(formErrorMessage);
      setBulkCategoryNotice("");
      return;
    }

    setIsSavingBulkCategory(true);
    setBulkCategoryError("");
    setBulkCategoryNotice("");
    try {
      const skippedIds = await onBulkEditCategories(bulkCategoryPayloadFromValues(selectedIds, bulkCategoryFormValues));
      setSelectedTransactionIds(new Set());
      if (skippedIds.length > 0) {
        setBulkCategoryNotice(
          `${skippedIds.length} protected or unavailable transaction${skippedIds.length === 1 ? "" : "s"} skipped.`,
        );
      }
    } catch (caught) {
      setBulkCategoryError(caught instanceof Error ? caught.message : "Categories could not be saved.");
    } finally {
      setIsSavingBulkCategory(false);
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
            {transactions.length} transactions extracted
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

      {transactions.length > 0 ? (
        <div className="transaction-bulk-grid">
          <div className="transaction-bulk-bar">
            <span>{includedCount} included</span>
            <button
              disabled={isSavingBulkInclusion || visibleTransactionIds.length === 0}
              onClick={() => void handleBulkInclusion(visibleTransactionIds, true, "visible")}
              type="button"
            >
              Select All Visible
            </button>
            <button
              disabled={isSavingBulkInclusion || visibleTransactionIds.length === 0}
              onClick={() => void handleBulkInclusion(visibleTransactionIds, false, "visible")}
              type="button"
            >
              Deselect All Visible
            </button>
            <button
              disabled={isSavingBulkInclusion || transactions.length === 0}
              onClick={() => handleAllTransactionsInclusion(true)}
              type="button"
            >
              Select All Transactions
            </button>
            <button
              disabled={isSavingBulkInclusion || transactions.length === 0}
              onClick={() => handleAllTransactionsInclusion(false)}
              type="button"
            >
              Deselect All Transactions
            </button>
            <button
              disabled={isSavingBulkInclusion || selectedIds.length === 0}
              onClick={() => void handleBulkInclusion(selectedIds, true, "bulk-selected")}
              type="button"
            >
              Bulk Include
            </button>
            <button
              disabled={isSavingBulkInclusion || selectedIds.length === 0}
              onClick={() => void handleBulkInclusion(selectedIds, false, "bulk-selected")}
              type="button"
            >
              Bulk Exclude
            </button>
          </div>
          <form className="transaction-bulk-bar" onSubmit={(event) => void handleSubmitBulkCategory(event)}>
            <span>{selectedIds.length} bulk selected</span>
            <label>
              <span>Set Category</span>
              <select
                value={bulkCategoryFormValues.main_category}
                onChange={(event) =>
                  updateBulkCategoryFormValue("main_category", event.target.value as CategoryMainValue)
                }
              >
                {categoryOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Set Subcategory</span>
              <select
                value={bulkCategoryFormValues.subcategory}
                onChange={(event) =>
                  updateBulkCategoryFormValue("subcategory", event.target.value as CategorySubcategoryValue)
                }
              >
                {subcategoryOptionsFor(bulkCategoryFormValues.main_category).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="checkbox-label transaction-bulk-bar__checkbox">
              <input
                checked={bulkCategoryFormValues.overwrite_user_edits}
                type="checkbox"
                onChange={(event) => updateBulkCategoryFormValue("overwrite_user_edits", event.target.checked)}
              />
              <span>Overwrite category edits</span>
            </label>
            <button disabled={isActionBusy || isSavingBulkCategory || selectedIds.length === 0} type="submit">
              {isSavingBulkCategory ? "Saving..." : "Set Category"}
            </button>
            <button
              disabled={isSavingBulkCategory || selectedIds.length === 0}
              onClick={() => {
                setSelectedTransactionIds(new Set());
                setBulkCategoryError("");
                setBulkCategoryNotice("");
              }}
              type="button"
            >
              Clear
            </button>
            {bulkCategoryError ? <span className="transaction-bulk-bar__error">{bulkCategoryError}</span> : null}
            {bulkCategoryNotice ? <span className="transaction-bulk-bar__notice">{bulkCategoryNotice}</span> : null}
          </form>
        </div>
      ) : null}

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
                  <label className="transaction-checkbox-heading">
                    <span>Include in Expenses</span>
                    <input
                      ref={inclusionHeaderCheckboxRef}
                      aria-label="Include visible transactions in expense summary"
                      checked={allVisibleIncluded}
                      className="transaction-table__select"
                      disabled={visibleTransactionIds.length === 0 || isSavingBulkInclusion}
                      onChange={(event) => void handleBulkInclusion(visibleTransactionIds, event.target.checked, "visible")}
                      type="checkbox"
                    />
                  </label>
                </th>
                <th className="transaction-select-cell">
                  <label className="transaction-checkbox-heading">
                    <span>Bulk Select</span>
                    <input
                      ref={bulkHeaderCheckboxRef}
                      aria-label="Select visible transactions for bulk edits"
                      checked={allVisibleBulkSelected}
                      className="transaction-table__select"
                      disabled={visibleTransactionIds.length === 0}
                      onChange={(event) => toggleVisibleTransactions(event.target.checked)}
                      type="checkbox"
                    />
                  </label>
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
                const isBulkSelected = selectedTransactionIds.has(transaction.id);
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
                    <td className="transaction-select-cell">
                      <input
                        aria-label={`Select transaction ${transaction.source_order} for bulk edits`}
                        checked={isBulkSelected}
                        className="transaction-table__select"
                        onChange={(event) => toggleTransactionSelection(transaction.id, event.target.checked)}
                        type="checkbox"
                      />
                    </td>
                    <td className={attentionCellClass("transaction_date")}>
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
                    <td className={attentionCellClass("normalized_name")}>
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
                    <td className={attentionCellClass("main_category")}>
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
                              : "Uncategorized"}
                        </span>
                      )}
                      <span className="transaction-category-meta">
                        {labelFor(categoryStatusLabels, currentCategoryStatus)} -{" "}
                        {formatConfidence(categoryConfidence(transaction))}
                      </span>
                      {transaction.user_edited_category ? (
                        <span className="transaction-badge">Category edited</span>
                      ) : null}
                      {currentCategorySource === "LEARNED_RULE" ? <span className="transaction-badge">Rule</span> : null}
                      {needsCategoryReview ? <span className="transaction-badge">Category review</span> : null}
                    </td>
                    <td className={attentionCellClass("subcategory")}>
                      {editValues ? (
                        <select
                          className="transaction-inline-input"
                          data-attention-field="subcategory"
                          value={editValues.subcategory}
                          onChange={(event) =>
                            updateInlineEditValue("subcategory", event.target.value as CategorySubcategoryValue)
                          }
                        >
                          {subcategoryOptionsFor(editValues.main_category).map((option) => (
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
                    <td className={attentionCellClass("transaction_detail")}>
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
                    <td className={attentionCellClass("direction")}>
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
                    <td className={attentionCellClass("amount", "transaction-table__amount")}>
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

function PreviewPane({ file }: { file: StoredFile }) {
  const previewType = fileCanPreview(file);
  const [previewState, setPreviewState] = useState<PreviewState>(
    previewType === "unsupported" ? { status: "unsupported" } : { status: "loading" },
  );

  useEffect(() => {
    if (previewType === "unsupported") {
      setPreviewState({ status: "unsupported" });
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
