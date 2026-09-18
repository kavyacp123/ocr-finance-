import statistics
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import InvoiceModel, AnomalyFlagModel
from app.utils.logging import logger


class AnomalyDetector:
    """
    Statistical Anomaly Detector for Invoices (MVP).
    Uses rolling sample mean and std-deviation (Z-score) per vendor.
    Flags an invoice if |z_score| > ANALYTICS_ANOMALY_ZSCORE_THRESHOLD.
    Requires at least ANALYTICS_ANOMALY_MIN_SAMPLE_SIZE previous invoices.
    """

    def check_invoice(self, invoice: InvoiceModel, db: Session) -> Optional[AnomalyFlagModel]:
        if not invoice.vendor_id or invoice.total_amount is None:
            return None

        org_id = invoice.organization_id
        current_amount = float(invoice.total_amount)

        # Query historical invoice amounts for this vendor (excluding current invoice)
        history = (
            db.query(InvoiceModel.total_amount)
            .filter(
                InvoiceModel.organization_id == org_id,
                InvoiceModel.vendor_id == invoice.vendor_id,
                InvoiceModel.id != invoice.id,
                InvoiceModel.total_amount.isnot(None),
            )
            .all()
        )

        amounts = [float(row[0]) for row in history if row[0] is not None]
        min_samples = settings.ANALYTICS_ANOMALY_MIN_SAMPLE_SIZE

        if len(amounts) < min_samples:
            return None

        mean = statistics.mean(amounts)
        std = statistics.stdev(amounts) if len(amounts) > 1 else 0.0

        if std == 0.0:
            return None

        z_score = (current_amount - mean) / std

        if abs(z_score) > settings.ANALYTICS_ANOMALY_ZSCORE_THRESHOLD:
            anomaly_type = "HIGH_AMOUNT" if z_score > 0 else "LOW_AMOUNT"
            flag = AnomalyFlagModel(
                organization_id=org_id,
                entity_type="INVOICE",
                entity_id=invoice.id,
                vendor_id=invoice.vendor_id,
                anomaly_type=anomaly_type,
                observed_value=Decimal(str(round(current_amount, 2))),
                expected_mean=Decimal(str(round(mean, 2))),
                expected_std=Decimal(str(round(std, 2))),
                z_score=Decimal(str(round(z_score, 2))),
                sample_size=len(amounts),
                status="OPEN",
            )
            db.add(flag)
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to record anomaly flag for invoice {invoice.id}: {e}")
            return flag

        return None
