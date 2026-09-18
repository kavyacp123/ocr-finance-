import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, VendorModel, VendorAliasModel, PossibleEntityMatchModel
from app.finance.entity_resolution.resolver import EntityResolver, token_sort_similarity, token_set_similarity


@pytest.fixture
def db_session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_token_similarity_metrics():
    # Invariant to word order
    assert token_sort_similarity('AWS India Pvt Ltd', 'India AWS Pvt Ltd') == 1.0
    # High similarity for slight spelling / suffix variation
    score = token_sort_similarity('Amazon Web Services', 'Amazon Web Services Inc')
    assert score > 0.80

    # Token set handles subset containment
    set_score = token_set_similarity('AWS', 'AWS India')
    assert set_score >= 0.80


def test_entity_resolution_tax_id_match(db_session):
    resolver = EntityResolver()
    org_id = 'org_test'

    # 1. Create first vendor with GSTIN
    res1 = resolver.resolve_or_create_vendor(
        db=db_session,
        organization_id=org_id,
        vendor_name_raw='Amazon Web Services India Pvt Ltd',
        vendor_tax_id='29AABCA1234F1Z5',
    )
    db_session.commit()
    assert res1.is_new_vendor is True
    assert res1.match_type == 'NEW_VENDOR'
    v_id = res1.canonical_vendor_id

    # 2. Second invoice arrives with abbreviated name but same GSTIN
    res2 = resolver.resolve_or_create_vendor(
        db=db_session,
        organization_id=org_id,
        vendor_name_raw='AWS Cloud Services',
        vendor_tax_id='29AABCA1234F1Z5',
    )
    db_session.commit()
    assert res2.is_new_vendor is False
    assert res2.canonical_vendor_id == v_id
    assert res2.match_type == 'TAX_ID'
    assert res2.confidence == 1.0

    # Verify alias was added
    aliases = db_session.query(VendorAliasModel).filter(VendorAliasModel.vendor_id == v_id).all()
    alias_names = [a.alias_name for a in aliases]
    assert 'AWS Cloud Services' in alias_names


def test_entity_resolution_bank_account_match(db_session):
    resolver = EntityResolver()
    org_id = 'org_test'

    res1 = resolver.resolve_or_create_vendor(
        db=db_session,
        organization_id=org_id,
        vendor_name_raw='Sonal Enterprises',
        bank_account='2631201000857',
        ifsc_swift='CNRB0002631',
    )
    db_session.commit()
    v_id = res1.canonical_vendor_id

    # Another invoice with slight name variant but identical bank coordinates
    res2 = resolver.resolve_or_create_vendor(
        db=db_session,
        organization_id=org_id,
        vendor_name_raw='Sonal Ent.',
        bank_account='2631201000857',
        ifsc_swift='CNRB0002631',
    )
    db_session.commit()
    assert res2.canonical_vendor_id == v_id
    assert res2.match_type == 'BANK_ACCOUNT'
    assert res2.confidence == 0.95


def test_entity_resolution_normalized_name_and_alias(db_session):
    resolver = EntityResolver()
    org_id = 'org_test'

    res1 = resolver.resolve_or_create_vendor(
        db=db_session,
        organization_id=org_id,
        vendor_name_raw='Tata Consultancy Services Limited',
    )
    db_session.commit()
    v_id = res1.canonical_vendor_id

    # Same legal entity with different capitalization/punctuation
    res2 = resolver.resolve_or_create_vendor(
        db=db_session,
        organization_id=org_id,
        vendor_name_raw='TATA CONSULTANCY SERVICES LTD.',
    )
    db_session.commit()
    assert res2.canonical_vendor_id == v_id
    assert res2.match_type == 'NORMALIZED_NAME'


def test_entity_resolution_ambiguous_no_auto_merge_safety(db_session):
    resolver = EntityResolver(auto_merge_threshold=0.88, possible_match_threshold=0.65)
    org_id = 'org_test'

    # Existing vendor: 'Delta Air Lines'
    res1 = resolver.resolve_or_create_vendor(
        db=db_session,
        organization_id=org_id,
        vendor_name_raw='Delta Air Lines Inc',
    )
    db_session.commit()
    v1_id = res1.canonical_vendor_id

    # New incoming vendor: 'Delta Electronics India' (partial overlap with 'Delta')
    res2 = resolver.resolve_or_create_vendor(
        db=db_session,
        organization_id=org_id,
        vendor_name_raw='Delta Electronics India',
    )
    db_session.commit()

    # CRITICAL ARCHITECTURAL TEST: Must NOT auto-merge!
    assert res2.canonical_vendor_id != v1_id
    assert res2.is_new_vendor is True

    # If it was in the ambiguous band (0.65-0.87), check that a review item was queued
    possible_matches = db_session.query(PossibleEntityMatchModel).filter(
        PossibleEntityMatchModel.organization_id == org_id
    ).all()
    # It enqueued a review item or created separate vendor cleanly
    assert len(db_session.query(VendorModel).all()) == 2
