import re
import difflib
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.finance.schemas import EntityMatchResult
from app.finance.normalizer import normalize_vendor_name, normalize_tax_id
from app.database.models import VendorModel, VendorAliasModel, PossibleEntityMatchModel
from app.utils.logging import logger


def token_sort_similarity(s1: str, s2: str) -> float:
    """
    Calculates token-sort similarity ratio between two strings using standard library difflib.
    Sorts tokens alphabetically to be invariant to word order (e.g. 'AWS India' vs 'India AWS').
    """
    if not s1 or not s2:
        return 0.0
    t1 = " ".join(sorted(s1.split()))
    t2 = " ".join(sorted(s2.split()))
    return difflib.SequenceMatcher(None, t1, t2).ratio()


def token_set_similarity(s1: str, s2: str) -> float:
    """
    Calculates token-set similarity: measures overlap of word sets.
    Handles subset containment (e.g. 'Amazon' vs 'Amazon Web Services').
    """
    if not s1 or not s2:
        return 0.0
    set1 = set(s1.split())
    set2 = set(s2.split())
    if not set1 or not set2:
        return 0.0

    intersection = set1.intersection(set2)
    if not intersection:
        return 0.0

    # If one string is a subset of the other, give high weight
    if set1.issubset(set2) or set2.issubset(set1):
        ratio = len(intersection) / max(len(set1), len(set2))
        return 0.70 + (0.30 * ratio)

    # General Jaccard overlap
    return len(intersection) / len(set1.union(set2))


class EntityResolver:
    """
    Vendor Entity Resolution Engine.
    Executes hierarchical priority matching:
    1. Strong Identifiers: Tax ID (GSTIN/TIN/PAN) -> Confident Auto-Match (conf=1.0)
    2. Bank Coordinates: Account Number + IFSC -> Confident Auto-Match (conf=0.95)
    3. Normalized Name & Aliases: Exact string match -> Confident Auto-Match (conf=0.92)
    4. Fuzzy String Similarity:
       - Score >= ENTITY_AUTO_MERGE_THRESHOLD (0.88): Auto-Merge & Register Alias (conf=0.86)
       - Score between 0.65 and 0.87: AMBIGUOUS! Do not merge. Create separate vendor
         and log a PossibleEntityMatch review item (status=PENDING_REVIEW)
       - Score < 0.65: Create New Distinct Canonical Vendor
    """

    def __init__(
        self,
        auto_merge_threshold: float = settings.ENTITY_AUTO_MERGE_THRESHOLD,
        possible_match_threshold: float = settings.ENTITY_POSSIBLE_MATCH_THRESHOLD,
    ):
        self.auto_merge_threshold = auto_merge_threshold
        self.possible_match_threshold = possible_match_threshold

    def resolve_or_create_vendor(
        self,
        db: Session,
        organization_id: str,
        vendor_name_raw: Optional[str],
        vendor_tax_id: Optional[str] = None,
        bank_account: Optional[str] = None,
        ifsc_swift: Optional[str] = None,
        document_id: Optional[str] = None,
        address: Optional[str] = None,
    ) -> EntityMatchResult:
        """
        Resolves an observed vendor identity to a canonical VendorModel.
        Creates a new vendor if no match is found, or enqueues a possible match.
        """
        raw_legal, norm_name = normalize_vendor_name(vendor_name_raw)
        norm_tax = normalize_tax_id(vendor_tax_id)
        clean_bank = re.sub(r'\D', '', bank_account) if bank_account else None
        clean_ifsc = ifsc_swift.strip().upper() if ifsc_swift else None

        if not norm_name and not norm_tax:
            # Fallback for documents completely missing vendor name
            raw_legal = "UNKNOWN_VENDOR"
            norm_name = "unknown vendor"

        # ── Step 1: Strong Identifier Check (Tax ID / GSTIN) ─────────────────
        if norm_tax:
            tax_match = db.query(VendorModel).filter(
                VendorModel.organization_id == organization_id,
                VendorModel.tax_id == norm_tax,
            ).first()
            if tax_match:
                logger.info(f"ENTITY_RESOLVER: Matched vendor '{tax_match.canonical_name}' via TAX_ID '{norm_tax}' (conf=1.0)")
                # Record alias if new name encountered
                self._maybe_add_alias(db, tax_match, raw_legal, norm_name, organization_id, document_id)
                return EntityMatchResult(
                    canonical_vendor_id=tax_match.id,
                    canonical_name=tax_match.canonical_name,
                    normalized_name=tax_match.normalized_name,
                    match_type="TAX_ID",
                    confidence=1.0,
                    is_new_vendor=False,
                )

        # ── Step 2: Bank Coordinates Check ───────────────────────────────────
        if clean_bank and len(clean_bank) >= 9:
            bank_query = db.query(VendorModel).filter(
                VendorModel.organization_id == organization_id,
                VendorModel.bank_account == clean_bank,
            )
            if clean_ifsc:
                bank_query = bank_query.filter(VendorModel.ifsc_swift == clean_ifsc)
            bank_match = bank_query.first()
            if bank_match:
                logger.info(f"ENTITY_RESOLVER: Matched vendor '{bank_match.canonical_name}' via BANK_ACCOUNT '{clean_bank}' (conf=0.95)")
                self._maybe_add_alias(db, bank_match, raw_legal, norm_name, organization_id, document_id)
                return EntityMatchResult(
                    canonical_vendor_id=bank_match.id,
                    canonical_name=bank_match.canonical_name,
                    normalized_name=bank_match.normalized_name,
                    match_type="BANK_ACCOUNT",
                    confidence=0.95,
                    is_new_vendor=False,
                )

        # ── Step 3: Exact Normalized Name Check ──────────────────────────────
        name_match = db.query(VendorModel).filter(
            VendorModel.organization_id == organization_id,
            VendorModel.normalized_name == norm_name,
        ).first()
        if name_match:
            logger.info(f"ENTITY_RESOLVER: Matched vendor '{name_match.canonical_name}' via EXACT NORMALIZED_NAME (conf=0.92)")
            self._update_missing_details(name_match, norm_tax, clean_bank, clean_ifsc, address)
            return EntityMatchResult(
                canonical_vendor_id=name_match.id,
                canonical_name=name_match.canonical_name,
                normalized_name=name_match.normalized_name,
                match_type="NORMALIZED_NAME",
                confidence=0.92,
                is_new_vendor=False,
            )

        # ── Step 4: Registered Alias Check ───────────────────────────────────
        alias_match = db.query(VendorAliasModel).filter(
            VendorAliasModel.organization_id == organization_id,
            VendorAliasModel.normalized_alias == norm_name,
        ).first()
        if alias_match and alias_match.vendor:
            logger.info(f"ENTITY_RESOLVER: Matched vendor '{alias_match.vendor.canonical_name}' via ALIAS '{alias_match.alias_name}' (conf=0.92)")
            self._update_missing_details(alias_match.vendor, norm_tax, clean_bank, clean_ifsc, address)
            return EntityMatchResult(
                canonical_vendor_id=alias_match.vendor.id,
                canonical_name=alias_match.vendor.canonical_name,
                normalized_name=alias_match.vendor.normalized_name,
                match_type="ALIAS",
                confidence=0.92,
                is_new_vendor=False,
                matched_alias=alias_match.alias_name,
            )

        # ── Step 5: Fuzzy String Similarity Check ────────────────────────────
        existing_vendors = db.query(VendorModel).filter(
            VendorModel.organization_id == organization_id
        ).all()

        best_vendor: Optional[VendorModel] = None
        best_score = 0.0
        best_matched_alias: Optional[str] = None

        for vendor in existing_vendors:
            # Score against canonical normalized name
            score1 = token_sort_similarity(norm_name, vendor.normalized_name)
            score2 = token_set_similarity(norm_name, vendor.normalized_name)
            curr_best = max(score1, score2)
            matched_str = vendor.canonical_name

            # Score against all existing aliases for this vendor
            for alias in vendor.aliases:
                ascore1 = token_sort_similarity(norm_name, alias.normalized_alias)
                ascore2 = token_set_similarity(norm_name, alias.normalized_alias)
                alias_max = max(ascore1, ascore2)
                if alias_max > curr_best:
                    curr_best = alias_max
                    matched_str = alias.alias_name

            if curr_best > best_score:
                best_score = curr_best
                best_vendor = vendor
                best_matched_alias = matched_str

        # ── Case A: High Confidence Match (>= auto_merge_threshold) ──────────
        if best_vendor and best_score >= self.auto_merge_threshold:
            logger.info(f"ENTITY_RESOLVER: Fuzzy matched '{raw_legal}' to '{best_vendor.canonical_name}' (score={best_score:.2f})")
            self._maybe_add_alias(db, best_vendor, raw_legal, norm_name, organization_id, document_id)
            self._update_missing_details(best_vendor, norm_tax, clean_bank, clean_ifsc, address)
            return EntityMatchResult(
                canonical_vendor_id=best_vendor.id,
                canonical_name=best_vendor.canonical_name,
                normalized_name=best_vendor.normalized_name,
                match_type="FUZZY_SIMILARITY",
                confidence=round(best_score, 2),
                is_new_vendor=False,
                matched_alias=best_matched_alias,
            )

        # ── Case B: Ambiguous Match (possible_match_threshold <= score < auto_merge_threshold)
        # NEVER AUTO-MERGE! Create a distinct vendor and enqueue human review item.
        needs_review = False
        if best_vendor and best_score >= self.possible_match_threshold:
            needs_review = True
            logger.warning(
                f"ENTITY_RESOLVER: Ambiguous match between '{raw_legal}' and '{best_vendor.canonical_name}' "
                f"(score={best_score:.2f}). Kept separate for manual review."
            )

        # Create new canonical vendor record
        new_vendor = VendorModel(
            organization_id=organization_id,
            canonical_name=raw_legal,
            normalized_name=norm_name,
            tax_id=norm_tax,
            bank_account=clean_bank,
            ifsc_swift=clean_ifsc,
            address=address,
        )
        db.add(new_vendor)
        db.flush()  # Assigns new_vendor.id

        # Also register the initial alias
        init_alias = VendorAliasModel(
            vendor_id=new_vendor.id,
            organization_id=organization_id,
            alias_name=raw_legal,
            normalized_alias=norm_name,
            source_document_id=document_id,
        )
        db.add(init_alias)

        # If ambiguous, log a review item in possible_entity_matches
        if needs_review and best_vendor:
            match_issue = PossibleEntityMatchModel(
                organization_id=organization_id,
                matched_vendor_id=best_vendor.id,
                candidate_name=raw_legal,
                match_score=round(best_score, 3),
                match_reason=f"Fuzzy similarity score {best_score:.2f} with '{best_vendor.canonical_name}'",
                status="PENDING_REVIEW",
                source_document_id=document_id,
            )
            db.add(match_issue)

        logger.info(f"ENTITY_RESOLVER: Created new vendor '{raw_legal}' (id={new_vendor.id}, needs_review={needs_review})")
        return EntityMatchResult(
            canonical_vendor_id=new_vendor.id,
            canonical_name=new_vendor.canonical_name,
            normalized_name=new_vendor.normalized_name,
            match_type="NEW_VENDOR",
            confidence=1.0,
            is_new_vendor=True,
            needs_review=needs_review,
        )

    def _maybe_add_alias(
        self,
        db: Session,
        vendor: VendorModel,
        raw_name: str,
        norm_name: str,
        organization_id: str,
        document_id: Optional[str],
    ) -> None:
        """Registers a new alias if this name variant is not already known."""
        if not norm_name or norm_name == vendor.normalized_name:
            return
        exists = db.query(VendorAliasModel).filter(
            VendorAliasModel.vendor_id == vendor.id,
            VendorAliasModel.normalized_alias == norm_name,
        ).first()
        if not exists:
            new_alias = VendorAliasModel(
                vendor_id=vendor.id,
                organization_id=organization_id,
                alias_name=raw_name,
                normalized_alias=norm_name,
                source_document_id=document_id,
            )
            db.add(new_alias)
            logger.debug(f"ENTITY_RESOLVER: Added new alias '{raw_name}' to vendor '{vendor.canonical_name}'")

    def _update_missing_details(
        self,
        vendor: VendorModel,
        tax_id: Optional[str],
        bank_account: Optional[str],
        ifsc_swift: Optional[str],
        address: Optional[str],
    ) -> None:
        """Enriches existing vendor record with newly observed fields if missing."""
        if not vendor.tax_id and tax_id:
            vendor.tax_id = tax_id
        if not vendor.bank_account and bank_account:
            vendor.bank_account = bank_account
        if not vendor.ifsc_swift and ifsc_swift:
            vendor.ifsc_swift = ifsc_swift
        if not vendor.address and address:
            vendor.address = address
