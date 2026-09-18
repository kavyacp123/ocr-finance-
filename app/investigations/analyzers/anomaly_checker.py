"""
Anomaly Checker for Investigations
==================================

WHY:   Correlates statistical spend outliers (Z-scores) with observed spend anomalies.
"""

from typing import Any, Dict, List
from sqlalchemy.orm import Session

from app.database.models import AnomalyFlagModel
from app.investigations.schemas import (
    InvestigationFinding,
    FindingStatus,
    FindingSeverity,
)


class AnomalyChecker:
    @staticmethod
    def check(
        db: Session,
        organization_id: str,
        vendor_id: str,
        target_invoice_ids: List[str],
    ) -> (List[InvestigationFinding], List[Dict[str, Any]]):
        findings: List[InvestigationFinding] = []
        raw_anomalies: List[Dict[str, Any]] = []

        if not vendor_id:
            return findings, raw_anomalies

        flags = (
            db.query(AnomalyFlagModel)
            .filter(
                AnomalyFlagModel.organization_id == organization_id,
                AnomalyFlagModel.vendor_id == vendor_id,
            )
            .all()
        )

        for f in flags:
            raw_anomalies.append({
                "flag_id": f.id,
                "entity_id": f.entity_id,
                "anomaly_type": f.anomaly_type,
                "observed_value": str(f.observed_value),
                "z_score": str(f.z_score) if f.z_score else None,
                "status": f.status,
            })

            # Check if this anomaly occurred on a target period invoice
            is_target_inv = f.entity_id in target_invoice_ids
            status = FindingStatus.CONFIRMED if is_target_inv else FindingStatus.SUPPORTED

            findings.append(
                InvestigationFinding(
                    finding_id=f"f_anom_{len(findings)+1}",
                    finding_type="STATISTICAL_ANOMALY",
                    title=f"Statistical anomaly: {f.anomaly_type} on {f.entity_id}",
                    description=(
                        f"Invoice {f.entity_id} was flagged as a statistical outlier with observed amount "
                        f"₹{f.observed_value} (Z-score: {f.z_score})."
                    ),
                    impact_amount=str(f.observed_value),
                    severity=FindingSeverity.HIGH,
                    confidence=0.95,
                    calculation={"z_score": str(f.z_score), "observed_value": str(f.observed_value)},
                    status=status,
                )
            )

        return findings, raw_anomalies
