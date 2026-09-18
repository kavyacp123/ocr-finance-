from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.config import settings
from app.database.models import DocumentLinkModel
from app.utils.logging import logger


class DocumentLinkRepository:
    """
    Data access repository for document links (Invoice <-> PO <-> Payment).
    Scoped to organization_id for multi-tenant isolation.
    """

    def __init__(self, db: Session):
        self.db = db

    def create_or_update_link(
        self,
        link_type: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: Optional[str],
        match_type: str,
        confidence: float,
        status: str,
        discrepancy_details: Optional[str] = None,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> DocumentLinkModel:
        # Check if link already exists between these specific entities
        existing = self.db.query(DocumentLinkModel).filter(
            DocumentLinkModel.organization_id == organization_id,
            DocumentLinkModel.link_type == link_type,
            DocumentLinkModel.source_type == source_type,
            DocumentLinkModel.source_id == source_id,
        ).first()

        if existing:
            existing.target_type = target_type
            existing.target_id = target_id
            existing.match_type = match_type
            existing.confidence = confidence
            existing.status = status
            existing.discrepancy_details = discrepancy_details
            self.db.commit()
            self.db.refresh(existing)
            logger.info(f"REPO: Updated link {existing.id} ({link_type}: {source_id} -> {target_id}, status={status})")
            return existing

        new_link = DocumentLinkModel(
            organization_id=organization_id,
            link_type=link_type,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            match_type=match_type,
            confidence=confidence,
            status=status,
            discrepancy_details=discrepancy_details,
        )
        self.db.add(new_link)
        self.db.commit()
        self.db.refresh(new_link)
        logger.info(f"REPO: Created link {new_link.id} ({link_type}: {source_id} -> {target_id}, status={status})")
        return new_link

    def get_links_for_source(
        self,
        source_type: str,
        source_id: str,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> List[DocumentLinkModel]:
        return self.db.query(DocumentLinkModel).filter(
            DocumentLinkModel.organization_id == organization_id,
            DocumentLinkModel.source_type == source_type,
            DocumentLinkModel.source_id == source_id,
        ).all()

    def get_links_for_target(
        self,
        target_type: str,
        target_id: str,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> List[DocumentLinkModel]:
        return self.db.query(DocumentLinkModel).filter(
            DocumentLinkModel.organization_id == organization_id,
            DocumentLinkModel.target_type == target_type,
            DocumentLinkModel.target_id == target_id,
        ).all()

    def list_unresolved_links(
        self,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        link_type: Optional[str] = None,
    ) -> List[DocumentLinkModel]:
        query = self.db.query(DocumentLinkModel).filter(
            DocumentLinkModel.organization_id == organization_id,
            DocumentLinkModel.status == "UNRESOLVED",
        )
        if link_type:
            query = query.filter(DocumentLinkModel.link_type == link_type)
        return query.all()

    def list_links(
        self,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        link_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[DocumentLinkModel], int]:
        query = self.db.query(DocumentLinkModel).filter(
            DocumentLinkModel.organization_id == organization_id
        )
        if link_type:
            query = query.filter(DocumentLinkModel.link_type == link_type)
        if status:
            query = query.filter(DocumentLinkModel.status == status)
        total_count = query.count()
        links = query.order_by(desc(DocumentLinkModel.created_at)).offset(offset).limit(limit).all()
        return links, total_count
