"""
Duplicate Invoice Checker for Investigations
============================================

WHY:   A common cause of spend spikes is duplicate invoice submission.
       Identifies duplicate candidate invoices in the target period.
"""

from decimal import Decimal
from typing import Any, Dict, List
from sqlalchemy.orm import Session

from app.database.models import DuplicateCandidateModel, InvoiceModel
from app.investigations.schemas import (
    InvestigationFinding,
    FindingStatus,
    FindingSeverity,
    DriverType,
)


class DuplicateChecker:
    @staticmethod
    def check(
        db: Session,
        organization_id: str,
        target_invoice_ids: List[str],
    ) -> List[InvestigationFinding]:
        findings: List[InvestigationFinding] = []
        if not target_invoice_ids:
            return findings

        dups = (
            db.query(DuplicateCandidateModel)
            .filter(
                DuplicateCandidateModel.organization_id == organization_id,
                DuplicateCandidateModel.primary_entity_id.in_(target_invoice_ids),
                DuplicateCandidateModel.status.in_(["OPEN", "CONFIRMED"]),
            )
            .all()
        )

        for d in dups:
            inv = db.query(InvoiceModel).filter(InvoiceModel.id == d.primary_entity_id).first()
            amount = str(inv.total_amount) if inv and inv.total_amount else "0.00"
            inv_num = inv.invoice_number if inv else d.primary_entity_id

            findings.append(
                InvestigationFinding(
                    finding_id=f"f_dup_{len(findings)+1}",
                    finding_type=DriverType.DUPLICATE_INVOICE.value,
                    title=f"Potential duplicate invoice '{inv_num}' detected",
                    description=(
                        f"Invoice '{inv_num}' was flagged as a duplicate of '{d.duplicate_of_entity_id}' "
                        f"(similarity: {d.similarity_score}). Impact amount: ₹{amount}."
                    ),
                    impact_amount=amount,
                    severity=FindingSeverity.CRITICAL,
                    confidence=float(d.similarity_score or 1.0),
                    calculation={"duplicate_of": d.duplicate_of_entity_id, "amount": amount},
                    status=FindingStatus.CONFIRMED if d.status == "CONFIRMED" else FindingStatus.POSSIBLE,
                )
            )

        return findings
