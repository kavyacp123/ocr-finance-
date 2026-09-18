from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.config import settings
from app.finance.schemas import PaymentRecord
from app.database.models import PaymentModel
from app.utils.logging import logger


class PaymentRepository:
    """
    Data access repository for payments.
    Scoped to organization_id for multi-tenant isolation.
    Uses short, atomic transactions.
    """

    def __init__(self, db: Session):
        self.db = db

    def create_payment(
        self,
        payment_data: PaymentRecord,
        document_id: Optional[str] = None,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> PaymentModel:
        pay = PaymentModel(
            document_id=document_id,
            organization_id=organization_id,
            vendor_id=payment_data.vendor_id,
            payment_reference=payment_data.payment_reference.strip(),
            payment_date=payment_data.payment_date,
            amount=payment_data.amount,
            currency=payment_data.currency,
            payment_method=payment_data.payment_method,
            payer_name=payment_data.payer_name,
            payee_name=payment_data.payee_name,
            bank_account=payment_data.bank_account,
            ifsc_swift=payment_data.ifsc_swift,
            status=payment_data.status or "COMPLETED",
        )
        self.db.add(pay)
        self.db.commit()
        self.db.refresh(pay)
        logger.info(f"REPO: Recorded payment '{pay.payment_reference}' (id={pay.id}, amount={pay.amount})")
        return pay

    def get_payment_by_id(
        self, payment_id: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> Optional[PaymentModel]:
        return self.db.query(PaymentModel).filter(
            PaymentModel.id == payment_id,
            PaymentModel.organization_id == organization_id,
        ).first()

    def list_payments(
        self,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[PaymentModel], int]:
        query = self.db.query(PaymentModel).filter(
            PaymentModel.organization_id == organization_id
        )
        total_count = query.count()
        payments = query.order_by(desc(PaymentModel.created_at)).offset(offset).limit(limit).all()
        return payments, total_count
