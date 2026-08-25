export type SortBy = "name" | "created_at" | "updated_at" | "file_size";
export type SortDirection = "asc" | "desc";

export type StoredFile = {
  type: "file";
  id: number;
  folder_id: number | null;
  original_filename: string;
  display_name: string;
  stored_filename: string;
  mime_type: string;
  file_size: number;
  created_at: string;
  updated_at: string;
};

export type FolderNode = {
  type: "folder";
  id: number;
  parent_folder_id: number | null;
  name: string;
  created_at: string;
  updated_at: string;
  folders: FolderNode[];
  files: StoredFile[];
};

export type FileManagerTree = {
  type: "root";
  name: "My Files";
  folders: FolderNode[];
  files: StoredFile[];
};

export type SearchResult = {
  id: number;
  type: "file" | "folder";
  name: string;
  parent_path: string[];
  expand_folder_ids: number[];
  parent_folder_id: number | null;
  folder_id: number | null;
  mime_type: string | null;
  file_size: number | null;
  updated_at: string;
};

export type SearchResponse = {
  query: string;
  results: SearchResult[];
};

export type SelectedItem =
  | { type: "root" }
  | { type: "folder"; id: number }
  | { type: "file"; id: number };

export type UploadBatchResponse = {
  uploaded: Array<{ filename: string; file: StoredFile }>;
  failed: Array<{ filename: string; error: string }>;
};

export type StatementDetection = {
  id: number;
  file_id: number;
  document_type: string;
  institution: string;
  product_name: string | null;
  account_type: string;
  account_last_four: string | null;
  statement_start_date: string | null;
  statement_end_date: string | null;
  detected_document_type: string | null;
  detected_institution: string | null;
  detected_product_name: string | null;
  detected_account_type: string | null;
  detected_account_last_four: string | null;
  detected_statement_start_date: string | null;
  detected_statement_end_date: string | null;
  original_document_type: string | null;
  original_institution: string | null;
  original_product_name: string | null;
  original_account_type: string | null;
  original_account_last_four: string | null;
  original_statement_start_date: string | null;
  original_statement_end_date: string | null;
  original_detected_at: string | null;
  metadata_source: string;
  user_corrected: boolean;
  manual_updated_at: string | null;
  detection_confidence: number;
  detection_status: string;
  detection_reason: string | null;
  detected_at: string | null;
  created_at: string;
  updated_at: string;
};

export type StatementLookupResponse = {
  statement: StatementDetection | null;
};

export type StatementUpdate = {
  document_type?: string;
  institution?: string;
  product_name?: string | null;
  account_type?: string;
  account_last_four?: string | null;
  statement_start_date?: string | null;
  statement_end_date?: string | null;
};

export type TransactionDirection = "INFLOW" | "OUTFLOW" | "UNKNOWN";

export type TransactionTypeValue =
  | "EXPENSE"
  | "INCOME"
  | "TRANSFER"
  | "CREDIT_CARD_PAYMENT"
  | "REFUND"
  | "ATM_CASH_WITHDRAWAL"
  | "CHECK"
  | "BANK_FEE"
  | "INTEREST"
  | "OTHER"
  | "UNKNOWN";

export type CategoryMainValue =
  | "AUTO_EXPENSE"
  | "BUSINESS_USE_OF_HOME"
  | "PROFIT_LOSS_BUSINESS"
  | "PERSONAL_INTERNAL";

export type CategorySubcategoryValue =
  | "AUTO_GAS"
  | "AUTO_INSURANCE"
  | "AUTO_MAINTENANCE"
  | "AUTO_PARKING"
  | "AUTO_TIRES"
  | "AUTO_TOLLS"
  | "AUTO_CAR_PAYMENT"
  | "HOME_INSURANCE"
  | "HOME_RENT"
  | "HOME_REPAIRS_MAINTENANCE"
  | "HOME_UTILITIES"
  | "HOME_TELECOM_INTERNET"
  | "HOME_OTHER_EXPENSE"
  | "BUSINESS_MATERIALS"
  | "BUSINESS_ADVERTISING"
  | "BUSINESS_INTEREST_OTHER"
  | "BUSINESS_LEGAL_PROFESSIONAL"
  | "BUSINESS_OFFICE_EXPENSE"
  | "BUSINESS_OTHER_SUPPLIES"
  | "BUSINESS_TRAVEL"
  | "BUSINESS_TOTAL_MEALS"
  | "BUSINESS_TRANSPORTATION"
  | "BUSINESS_GOVERNMENT"
  | "BUSINESS_DONATIONS"
  | "BUSINESS_BANK_MEMBERSHIP"
  | "BUSINESS_MEDICAL"
  | "BUSINESS_EDUCATION_LEARNING"
  | "PERSONAL_OTHER_ITEMS"
  | "PERSONAL"
  | "UNCATEGORIZED";

export type ReviewStatusValue = "PENDING" | "NEEDS_REVIEW" | "REVIEWED";

export type StatementTransaction = {
  id: number;
  statement_id: number;
  extraction_id: number | null;
  transaction_date: string;
  transaction_detail: string;
  amount: string | number;
  direction: TransactionDirection | string;
  source_page: number | null;
  source_order: number;
  extraction_confidence: number;
  needs_review: boolean;
  user_edited: boolean;
  user_added: boolean;
  excluded: boolean;
  source: string;
  original_transaction_date: string | null;
  original_transaction_detail: string | null;
  original_amount: string | number | null;
  original_direction: string | null;
  original_source_page: number | null;
  original_source_order: number | null;
  normalized_name: string | null;
  normalization_confidence: number;
  normalization_source: string;
  normalization_status: string;
  normalized_at: string | null;
  original_normalized_name: string | null;
  original_normalization_confidence: number | null;
  original_normalization_source: string | null;
  original_normalization_status: string | null;
  user_edited_normalization: boolean;
  normalization_rule_id: number | null;
  transaction_type: TransactionTypeValue | string;
  type_confidence: number;
  type_source: string;
  type_status: string;
  type_updated_at: string | null;
  suggested_include: string;
  original_transaction_type: TransactionTypeValue | string | null;
  original_type_confidence: number | null;
  original_type_source: string | null;
  original_type_status: string | null;
  original_suggested_include: string | null;
  user_edited_type: boolean;
  type_rule_id: number | null;
  main_category: CategoryMainValue | string | null;
  subcategory: CategorySubcategoryValue | string | null;
  category_confidence: number;
  category_source: string;
  category_status: string;
  category_updated_at: string | null;
  original_main_category: CategoryMainValue | string | null;
  original_subcategory: CategorySubcategoryValue | string | null;
  original_category_confidence: number | null;
  original_category_source: string | null;
  original_category_status: string | null;
  user_edited_category: boolean;
  category_rule_id: number | null;
  include_in_expenses: boolean | null;
  inclusion_initialized: boolean;
  inclusion_source: string;
  inclusion_updated_at: string | null;
  review_status: ReviewStatusValue | string;
  review_source: string;
  review_updated_at: string | null;
  created_at: string;
  updated_at: string;
};

export type TransactionExtraction = {
  id: number;
  statement_id: number;
  parser_name: string;
  parser_version: string;
  status: string;
  transaction_count: number;
  review_count: number;
  message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type TransactionListResponse = {
  latest_extraction: TransactionExtraction | null;
  transactions: StatementTransaction[];
};

export type TransactionExtractionRunResponse = {
  extraction: TransactionExtraction;
  transactions: StatementTransaction[];
};

export type TransactionNormalizationRunResponse = {
  transactions: StatementTransaction[];
};

export type TransactionTypeClassificationRunResponse = {
  transactions: StatementTransaction[];
};

export type TransactionCategorizationRunResponse = {
  transactions: StatementTransaction[];
};

export type TransactionTypeBulkUpdateResponse = {
  transactions: StatementTransaction[];
  skipped_transaction_ids: number[];
};

export type TransactionCategoryBulkUpdateResponse = {
  transactions: StatementTransaction[];
  skipped_transaction_ids: number[];
};

export type TransactionInclusionBulkUpdateResponse = {
  transactions: StatementTransaction[];
  skipped_transaction_ids: number[];
};

export type TransactionPayload = {
  transaction_date?: string;
  transaction_detail?: string;
  amount?: string;
  direction?: TransactionDirection;
};

export type TransactionNormalizationPayload = {
  normalized_name: string;
  use_for_future?: boolean;
};

export type TransactionTypePayload = {
  transaction_type: TransactionTypeValue;
  use_for_future?: boolean;
};

export type TransactionTypeBulkPayload = {
  transaction_ids: number[];
  transaction_type: TransactionTypeValue;
  overwrite_user_edits?: boolean;
};

export type TransactionCategoryPayload = {
  main_category: CategoryMainValue;
  subcategory: CategorySubcategoryValue;
  use_for_future?: boolean;
};

export type TransactionCategoryBulkPayload = {
  transaction_ids: number[];
  main_category: CategoryMainValue;
  subcategory: CategorySubcategoryValue;
  overwrite_user_edits?: boolean;
};

export type TransactionInclusionPayload = {
  include_in_expenses: boolean;
};

export type TransactionInclusionBulkPayload = {
  transaction_ids: number[];
  include_in_expenses: boolean;
};

export type TransactionReviewPayload = {
  review_status: ReviewStatusValue;
};

export type CategoryCatalogResponse = {
  categories: Array<{
    id: CategoryMainValue | string;
    label: string;
    subcategories: Array<{ id: CategorySubcategoryValue | string; label: string }>;
  }>;
};
