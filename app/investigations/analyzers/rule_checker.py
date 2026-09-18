"""
Rule Checker for Investigations
===============================

WHY:   Detects whether business rule violations (PO amount mismatch, missing PO)
       explain or accompany the spending anomaly.
"""

from typing import Any, Dict, List
from sqlalchemy.orm import Session

from app.database.models import RuleViolationModel
from app.investigations.schemas import (
    InvestigationFinding,
    FindingStatus,
    FindingSeverity,
    DriverType,
)


class RuleChecker:
    @staticmethod
    def check(
        db: Session,
        organization_id: str,
        target_invoice_ids: List[str],
    ) -> (List[InvestigationFinding], List[Dict[str, Any]]):
        findings: List[InvestigationFinding] = []
        raw_violations: List[Dict[str, Any]] = []

        if not target_invoice_ids:
            return findings, raw_violations

        violations = (
            db.query(RuleViolationModel)
            .filter(
                RuleViolationModel.organization_id == organization_id,
                RuleViolationModel.entity_id.in_(target_invoice_ids),
                RuleViolationModel.status == "OPEN",
            )
            .all()
        )

        for v in violations:
            raw_violations.append({
                "rule_id": v.rule_id,
                "rule_name": v.rule_name,
                "severity": v.severity,
                "entity_id": v.entity_id,
                "details": v.details_json,
            })

            sev = FindingSeverity.CRITICAL if v.severity == "CRITICAL" else FindingSeverity.HIGH
            driver_type = DriverType.PO_MISMATCH.value if "MISMATCH" in v.rule_id else "RULE_VIOLATION"

            findings.append(
                InvestigationFinding(
                    finding_id=f"f_rule_{len(findings)+1}",
                    finding_type=driver_type,
                    title=f"Rule violation: {v.rule_name}",
                    description=f"Invoice {v.entity_id} triggered rule violation '{v.rule_id}'.",
                    severity=sev,
                    confidence=1.0,
                    status=FindingStatus.CONFIRMED,
                )
            )

        return findings, raw_violations
