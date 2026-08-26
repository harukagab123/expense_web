from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse as FastAPIFileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.file import StoredFile
from app.models.folder import Folder
from app.schemas.file_manager import (
    FileManagerTree,
    FileResponse,
    FileUpdate,
    FolderCreate,
    FolderResponse,
    FolderUpdate,
    SearchResponse,
    UploadBatchResponse,
    UploadFailure,
    UploadSuccess,
)
from app.schemas.analysis import StatementAnalysisResponse
from app.schemas.statement import StatementLookupResponse, StatementResponse, StatementUpdate
from app.schemas.transaction import (
    CategoryCatalogResponse,
    TransactionCreate,
    TransactionCategorizationRunResponse,
    TransactionCategoryBulkUpdate,
    TransactionCategoryBulkUpdateResponse,
    TransactionCategoryUpdate,
    TransactionExtractionRunResponse,
    TransactionListResponse,
    TransactionNormalizationRunResponse,
    TransactionNormalizationUpdate,
    TransactionResponse,
    TransactionInclusionBulkUpdate,
    TransactionInclusionBulkUpdateResponse,
    TransactionInclusionUpdate,
    TransactionReviewBulkUpdate,
    TransactionReviewBulkUpdateResponse,
    TransactionReviewUpdate,
    TransactionTypeBulkUpdate,
    TransactionTypeBulkUpdateResponse,
    TransactionTypeClassificationRunResponse,
    TransactionTypeUpdate,
    TransactionUpdate,
)
from app.services.file_manager import (
    build_tree,
    create_folder,
    delete_file,
    delete_folder,
    ensure_preview_supported,
    ensure_source_file_available,
    get_file_or_404,
    resolve_storage_path,
    search_items,
    update_file,
    update_folder,
    upload_one_file,
)
from app.services.statement_detection.service import (
    detect_statement_for_file,
    get_statement_for_file,
    update_statement_for_file,
)
from app.services.statement_analysis import analyze_statement_file
from app.services.transaction_categorization.service import (
    bulk_update_transaction_categories,
    categorize_transactions_for_statement,
    update_transaction_category,
)
from app.services.transaction_extraction.service import (
    create_manual_transaction,
    exclude_transaction,
    extract_transactions_for_statement,
    list_transactions_for_statement,
    update_transaction as update_transaction_service,
)
from app.services.transaction_review.service import (
    bulk_update_transaction_review,
    bulk_update_transaction_inclusion,
    update_transaction_inclusion,
    update_transaction_review,
)
from app.services.transaction_normalization.service import (
    normalize_transactions_for_statement,
    update_transaction_normalization,
)
from app.services.transaction_type_detection.service import (
    bulk_update_transaction_types,
    classify_transaction_types_for_statement,
    update_transaction_type,
)

router = APIRouter(tags=["file-manager"])


@router.get("/file-manager/tree", response_model=FileManagerTree)
def read_file_manager_tree(
    sort_by: str = "name",
    sort_direction: str = "asc",
    search: str = "",
    db: Session = Depends(get_db),
) -> FileManagerTree:
    folders, files = build_tree(db, sort_by=sort_by, sort_direction=sort_direction, search=search)
    return FileManagerTree(folders=folders, files=files)


@router.get("/file-manager/search", response_model=SearchResponse)
def search_file_manager(query: str = "", db: Session = Depends(get_db)) -> SearchResponse:
    clean_query = query.strip()
    return SearchResponse(query=clean_query, results=search_items(db, clean_query))


@router.get("/categories/catalog", response_model=CategoryCatalogResponse)
def read_category_catalog_endpoint() -> CategoryCatalogResponse:
    return CategoryCatalogResponse.from_catalog()


@router.get("/folders", response_model=list[FolderResponse])
def list_folders(db: Session = Depends(get_db)) -> list[FolderResponse]:
    return list(db.execute(select(Folder).order_by(Folder.name)).scalars().all())


@router.post("/folders", response_model=FolderResponse, status_code=201)
def create_folder_endpoint(payload: FolderCreate, db: Session = Depends(get_db)) -> FolderResponse:
    return create_folder(db, payload.name, payload.parent_folder_id)


@router.patch("/folders/{folder_id}", response_model=FolderResponse)
def update_folder_endpoint(
    folder_id: int,
    payload: FolderUpdate,
    db: Session = Depends(get_db),
) -> FolderResponse:
    kwargs = {}
    if "name" in payload.__fields_set__:
        kwargs["name"] = payload.name
    if "parent_folder_id" in payload.__fields_set__:
        kwargs["parent_folder_id"] = payload.parent_folder_id
    return update_folder(db, folder_id, **kwargs)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder_endpoint(folder_id: int, db: Session = Depends(get_db)) -> Response:
    delete_folder(db, folder_id)
    return Response(status_code=204)


@router.get("/files", response_model=list[FileResponse])
def list_files(folder_id: int | None = None, db: Session = Depends(get_db)) -> list[FileResponse]:
    statement = select(StoredFile).where(StoredFile.source_file_available.is_(True)).order_by(StoredFile.display_name)
    if folder_id is None:
        statement = statement.where(StoredFile.folder_id.is_(None))
    else:
        statement = statement.where(StoredFile.folder_id == folder_id)
    return list(db.execute(statement).scalars().all())


@router.post("/files", response_model=UploadBatchResponse)
async def upload_files_endpoint(
    files: list[UploadFile] = File(...),
    folder_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
) -> UploadBatchResponse:
    uploaded: list[UploadSuccess] = []
    failed: list[UploadFailure] = []

    for upload in files:
        filename = upload.filename or "unnamed"
        try:
            stored_file = await upload_one_file(db, upload, folder_id)
            uploaded.append(UploadSuccess(filename=filename, file=FileResponse.from_orm(stored_file)))
        except HTTPException as exc:
            db.rollback()
            failed.append(UploadFailure(filename=filename, error=str(exc.detail)))
        finally:
            await upload.close()

    return UploadBatchResponse(uploaded=uploaded, failed=failed)


@router.patch("/files/{file_id}", response_model=FileResponse)
def update_file_endpoint(
    file_id: int,
    payload: FileUpdate,
    db: Session = Depends(get_db),
) -> FileResponse:
    kwargs = {}
    if "display_name" in payload.__fields_set__:
        kwargs["display_name"] = payload.display_name
    if "folder_id" in payload.__fields_set__:
        kwargs["folder_id"] = payload.folder_id
    return update_file(db, file_id, **kwargs)


@router.delete("/files/{file_id}", status_code=204)
def delete_file_endpoint(file_id: int, db: Session = Depends(get_db)) -> Response:
    delete_file(db, file_id)
    return Response(status_code=204)


@router.get("/files/{file_id}/statement", response_model=StatementLookupResponse)
def read_file_statement_endpoint(file_id: int, db: Session = Depends(get_db)) -> StatementLookupResponse:
    statement = get_statement_for_file(db, file_id)
    return StatementLookupResponse(
        statement=StatementResponse.from_orm(statement) if statement is not None else None,
    )


@router.post("/files/{file_id}/detect-statement", response_model=StatementResponse)
def detect_file_statement_endpoint(file_id: int, db: Session = Depends(get_db)) -> StatementResponse:
    statement = detect_statement_for_file(db, file_id)
    return StatementResponse.from_orm(statement)


@router.post("/files/{file_id}/analyze", response_model=StatementAnalysisResponse)
def analyze_file_statement_endpoint(file_id: int, db: Session = Depends(get_db)) -> StatementAnalysisResponse:
    return analyze_statement_file(db, file_id)


@router.patch("/files/{file_id}/statement", response_model=StatementResponse)
def update_file_statement_endpoint(
    file_id: int,
    payload: StatementUpdate,
    db: Session = Depends(get_db),
) -> StatementResponse:
    statement = update_statement_for_file(db, file_id, payload)
    return StatementResponse.from_orm(statement)


@router.post("/statements/{statement_id}/extract-transactions", response_model=TransactionExtractionRunResponse)
def extract_statement_transactions_endpoint(
    statement_id: int,
    db: Session = Depends(get_db),
) -> TransactionExtractionRunResponse:
    extraction, transactions = extract_transactions_for_statement(db, statement_id)
    return TransactionExtractionRunResponse(
        extraction=extraction,
        transactions=transactions,
    )


@router.get("/statements/{statement_id}/transactions", response_model=TransactionListResponse)
def list_statement_transactions_endpoint(
    statement_id: int,
    include_excluded: bool = False,
    db: Session = Depends(get_db),
) -> TransactionListResponse:
    latest_extraction, transactions = list_transactions_for_statement(
        db,
        statement_id,
        include_excluded=include_excluded,
    )
    return TransactionListResponse(
        latest_extraction=latest_extraction,
        transactions=transactions,
    )


@router.post("/statements/{statement_id}/transactions", response_model=TransactionResponse, status_code=201)
def create_statement_transaction_endpoint(
    statement_id: int,
    payload: TransactionCreate,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return create_manual_transaction(db, statement_id, payload)


@router.post("/statements/{statement_id}/normalize-transactions", response_model=TransactionNormalizationRunResponse)
def normalize_statement_transactions_endpoint(
    statement_id: int,
    db: Session = Depends(get_db),
) -> TransactionNormalizationRunResponse:
    transactions = normalize_transactions_for_statement(db, statement_id)
    return TransactionNormalizationRunResponse(transactions=transactions)


@router.post("/statements/{statement_id}/classify-transaction-types", response_model=TransactionTypeClassificationRunResponse)
def classify_statement_transaction_types_endpoint(
    statement_id: int,
    db: Session = Depends(get_db),
) -> TransactionTypeClassificationRunResponse:
    transactions = classify_transaction_types_for_statement(db, statement_id)
    return TransactionTypeClassificationRunResponse(transactions=transactions)


@router.post("/statements/{statement_id}/categorize-transactions", response_model=TransactionCategorizationRunResponse)
def categorize_statement_transactions_endpoint(
    statement_id: int,
    db: Session = Depends(get_db),
) -> TransactionCategorizationRunResponse:
    transactions = categorize_transactions_for_statement(db, statement_id)
    return TransactionCategorizationRunResponse(transactions=transactions)


@router.patch("/transactions/bulk-type", response_model=TransactionTypeBulkUpdateResponse)
def bulk_update_transaction_types_endpoint(
    payload: TransactionTypeBulkUpdate,
    db: Session = Depends(get_db),
) -> TransactionTypeBulkUpdateResponse:
    transactions, skipped_transaction_ids = bulk_update_transaction_types(db, payload)
    return TransactionTypeBulkUpdateResponse(
        transactions=transactions,
        skipped_transaction_ids=skipped_transaction_ids,
    )


@router.patch("/transactions/bulk-category", response_model=TransactionCategoryBulkUpdateResponse)
def bulk_update_transaction_categories_endpoint(
    payload: TransactionCategoryBulkUpdate,
    db: Session = Depends(get_db),
) -> TransactionCategoryBulkUpdateResponse:
    transactions, skipped_transaction_ids = bulk_update_transaction_categories(db, payload)
    return TransactionCategoryBulkUpdateResponse(
        transactions=transactions,
        skipped_transaction_ids=skipped_transaction_ids,
    )


@router.patch("/transactions/bulk-inclusion", response_model=TransactionInclusionBulkUpdateResponse)
def bulk_update_transaction_inclusion_endpoint(
    payload: TransactionInclusionBulkUpdate,
    db: Session = Depends(get_db),
) -> TransactionInclusionBulkUpdateResponse:
    transactions, skipped_transaction_ids = bulk_update_transaction_inclusion(db, payload)
    return TransactionInclusionBulkUpdateResponse(
        transactions=transactions,
        skipped_transaction_ids=skipped_transaction_ids,
    )


@router.patch("/transactions/bulk-review", response_model=TransactionReviewBulkUpdateResponse)
def bulk_update_transaction_review_endpoint(
    payload: TransactionReviewBulkUpdate,
    db: Session = Depends(get_db),
) -> TransactionReviewBulkUpdateResponse:
    transactions, skipped_transaction_ids = bulk_update_transaction_review(db, payload)
    return TransactionReviewBulkUpdateResponse(
        transactions=transactions,
        skipped_transaction_ids=skipped_transaction_ids,
    )


@router.patch("/transactions/{transaction_id}", response_model=TransactionResponse)
def update_transaction_endpoint(
    transaction_id: int,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return update_transaction_service(db, transaction_id, payload)


@router.patch("/transactions/{transaction_id}/normalization", response_model=TransactionResponse)
def update_transaction_normalization_endpoint(
    transaction_id: int,
    payload: TransactionNormalizationUpdate,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return update_transaction_normalization(db, transaction_id, payload)


@router.patch("/transactions/{transaction_id}/type", response_model=TransactionResponse)
def update_transaction_type_endpoint(
    transaction_id: int,
    payload: TransactionTypeUpdate,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return update_transaction_type(db, transaction_id, payload)


@router.patch("/transactions/{transaction_id}/category", response_model=TransactionResponse)
def update_transaction_category_endpoint(
    transaction_id: int,
    payload: TransactionCategoryUpdate,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return update_transaction_category(db, transaction_id, payload)


@router.patch("/transactions/{transaction_id}/inclusion", response_model=TransactionResponse)
def update_transaction_inclusion_endpoint(
    transaction_id: int,
    payload: TransactionInclusionUpdate,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return update_transaction_inclusion(db, transaction_id, payload)


@router.patch("/transactions/{transaction_id}/review", response_model=TransactionResponse)
def update_transaction_review_endpoint(
    transaction_id: int,
    payload: TransactionReviewUpdate,
    db: Session = Depends(get_db),
) -> TransactionResponse:
    return update_transaction_review(db, transaction_id, payload)


@router.delete("/transactions/{transaction_id}", response_model=TransactionResponse)
def exclude_transaction_endpoint(transaction_id: int, db: Session = Depends(get_db)) -> TransactionResponse:
    return exclude_transaction(db, transaction_id)


@router.get("/files/{file_id}/download")
def download_file_endpoint(file_id: int, db: Session = Depends(get_db)) -> FastAPIFileResponse:
    stored_file = get_file_or_404(db, file_id)
    ensure_source_file_available(stored_file)
    file_path = resolve_storage_path(stored_file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing.")
    return FastAPIFileResponse(
        path=file_path,
        media_type=stored_file.mime_type,
        filename=stored_file.display_name,
    )


@router.get("/files/{file_id}/preview")
def preview_file_endpoint(file_id: int, db: Session = Depends(get_db)) -> FastAPIFileResponse:
    stored_file = get_file_or_404(db, file_id)
    ensure_source_file_available(stored_file)
    ensure_preview_supported(stored_file)
    file_path = resolve_storage_path(stored_file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing.")
    return FastAPIFileResponse(
        path=file_path,
        media_type=stored_file.mime_type,
        filename=stored_file.display_name,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(stored_file.display_name)}"},
    )
