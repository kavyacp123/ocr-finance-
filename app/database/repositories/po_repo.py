import json
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from decimal import Decimal

from app.config import settings
from app.finance.schemas import PurchaseOrderData
from app.database.models import PurchaseOrderModel, PurchaseOrderLineItemModel
from app.utils.logging import logger


class PurchaseOrderRepository:
    """
    Data access repository for Purchase Orders and PO line items.
    Scoped to organization_id for multi-tenant isolation.
    Uses short, atomic transactions.
    """

    def __init__(self, db: Session):
        self.db = db

    def persist_purchase_order(
        self,
        po: PurchaseOrderData,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> PurchaseOrderModel:
        """
        Persists canonical purchase order, line items, and raw snapshot in a short transaction.
        """
        doc_id = po.document_id

        po_record = PurchaseOrderModel(
            document_id=doc_id,
            organization_id=organization_id,
            vendor_id=po.vendor_id,
            po_number=po.po_number.value if po.po_number else "UNKNOWN_PO",
            po_date=po.po_date.value if po.po_date else None,
            expected_delivery_date=po.expected_delivery_date.value if po.expected_delivery_date else None,
            vendor_name_raw=po.vendor_name_raw.value if po.vendor_name_raw else None,
            vendor_name_normalized=po.vendor_name_normalized,
            vendor_tax_id=po.vendor_tax_id.value if po.vendor_tax_id else None,
            buyer_name_raw=po.buyer_name_raw.value if po.buyer_name_raw else None,
            buyer_name_normalized=po.buyer_name_normalized,
            buyer_tax_id=po.buyer_tax_id.value if po.buyer_tax_id else None,
            currency=po.currency.value if po.currency else "INR",
            subtotal=po.subtotal.value if po.subtotal else None,
            tax_amount=po.tax_amount.value if po.tax_amount else None,
            total_amount=po.total_amount.value if po.total_amount else None,
            status=po.status or "OPEN",
            payment_terms=po.payment_terms.value if po.payment_terms else None,
            shipping_address=po.shipping_address.value if po.shipping_address else None,
            billing_address=po.billing_address.value if po.billing_address else None,
            confidence=Decimal(str(round(po.confidence, 3))),
            is_valid=po.validation.is_valid,
            raw_data_json=po.model_dump_json(),
        )
        self.db.add(po_record)
        self.db.flush()

        # Add line items
        for item in po.line_items:
            bbox_json = json.dumps(item.source.bbox) if item.source else None
            item_record = PurchaseOrderLineItemModel(
                purchase_order_id=po_record.id,
                organization_id=organization_id,
                line_number=item.line_number,
                description=item.description,
                product_code=item.product_code,
                quantity=item.quantity,
                unit=item.unit,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                tax_amount=item.tax_amount,
                total=item.total,
                source_bbox_json=bbox_json,
            )
            self.db.add(item_record)

        self.db.commit()
        self.db.refresh(po_record)
        logger.info(f"REPO: Persisted PO {po_record.po_number} (id={po_record.id}, total={po_record.total_amount})")
        return po_record

    def get_po_by_id(
        self, po_id: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> Optional[PurchaseOrderModel]:
        return self.db.query(PurchaseOrderModel).filter(
            PurchaseOrderModel.id == po_id,
            PurchaseOrderModel.organization_id == organization_id,
        ).first()

    def get_po_by_number(
        self, po_number: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> Optional[PurchaseOrderModel]:
        return self.db.query(PurchaseOrderModel).filter(
            PurchaseOrderModel.po_number == po_number.strip(),
            PurchaseOrderModel.organization_id == organization_id,
        ).first()

    def list_purchase_orders(
        self,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        vendor_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[PurchaseOrderModel], int]:
        query = self.db.query(PurchaseOrderModel).filter(
            PurchaseOrderModel.organization_id == organization_id
        )
        if vendor_id:
            query = query.filter(PurchaseOrderModel.vendor_id == vendor_id)
        if status:
            query = query.filter(PurchaseOrderModel.status == status)

        total_count = query.count()
        pos = query.order_by(desc(PurchaseOrderModel.created_at)).offset(offset).limit(limit).all()
        return pos, total_count
