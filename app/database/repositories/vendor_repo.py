from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.config import settings
from app.database.models import VendorModel, VendorAliasModel, PossibleEntityMatchModel
from app.utils.logging import logger


class VendorRepository:
    """
    Data access repository for canonical vendors, aliases, and human-review queues.
    Scoped to organization_id for multi-tenant isolation.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_vendor_by_id(
        self, vendor_id: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> Optional[VendorModel]:
        return self.db.query(VendorModel).filter(
            VendorModel.id == vendor_id,
            VendorModel.organization_id == organization_id,
        ).first()

    def get_vendor_by_tax_id(
        self, tax_id: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> Optional[VendorModel]:
        return self.db.query(VendorModel).filter(
            VendorModel.tax_id == tax_id,
            VendorModel.organization_id == organization_id,
        ).first()

    def get_vendor_by_normalized_name(
        self, norm_name: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> Optional[VendorModel]:
        return self.db.query(VendorModel).filter(
            VendorModel.normalized_name == norm_name,
            VendorModel.organization_id == organization_id,
        ).first()

    def list_vendors(
        self,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[VendorModel], int]:
        query = self.db.query(VendorModel).filter(
            VendorModel.organization_id == organization_id
        )
        if search:
            s_low = f"%{search.lower().strip()}%"
            query = query.filter(
                (VendorModel.canonical_name.ilike(s_low)) |
                (VendorModel.normalized_name.ilike(s_low)) |
                (VendorModel.tax_id.ilike(s_low))
            )
        total_count = query.count()
        vendors = query.order_by(VendorModel.canonical_name.asc()).offset(offset).limit(limit).all()
        return vendors, total_count

    def list_possible_matches(
        self,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        status: Optional[str] = None,
    ) -> List[PossibleEntityMatchModel]:
        query = self.db.query(PossibleEntityMatchModel).filter(
            PossibleEntityMatchModel.organization_id == organization_id
        )
        if status:
            query = query.filter(PossibleEntityMatchModel.status == status)
        return query.order_by(desc(PossibleEntityMatchModel.created_at)).all()

    def get_vendor_aliases(
        self, vendor_id: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> List[VendorAliasModel]:
        return self.db.query(VendorAliasModel).filter(
            VendorAliasModel.vendor_id == vendor_id,
            VendorAliasModel.organization_id == organization_id,
        ).all()
