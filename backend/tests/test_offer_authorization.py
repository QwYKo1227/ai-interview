from fastapi import status
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

from app.models.models import Offer, OfferDecisionAudit, OfferStatus, ResumeStatus


def _sent_offer(db, position, resume, creator):
    offer = Offer(
        tenant_id=position.tenant_id,
        resume_id=resume.id,
        position_id=position.id,
        candidate_name=resume.candidate_name,
        candidate_email=resume.email,
        position_title=position.title,
        status=OfferStatus.SENT,
        sent_at=datetime.utcnow(),
        valid_until=datetime.utcnow() - timedelta(days=1),
        created_by=creator.id,
    )
    resume.status = ResumeStatus.OFFER_PENDING
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def test_pending_confirmation_status_route_replaces_legacy_send_route(
    client: TestClient, db, auth_headers: dict, test_position, test_resume, test_user
):
    offer = Offer(
        tenant_id=test_position.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        candidate_name=test_resume.candidate_name,
        candidate_email=test_resume.email,
        position_title=test_position.title,
        status=OfferStatus.DRAFT,
        created_by=test_user.id,
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)

    legacy = client.post(f"/api/offers/{offer.id}/send", headers=auth_headers)
    assert legacy.status_code == status.HTTP_404_NOT_FOUND

    response = client.post(
        f"/api/offers/{offer.id}/mark-pending-confirmation",
        headers=auth_headers,
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"success": True, "status": "sent"}
    db.refresh(offer)
    db.refresh(test_resume)
    assert offer.status == OfferStatus.SENT
    assert test_resume.status == ResumeStatus.OFFER_PENDING


def test_interviewer_cannot_access_offer_management(
    client: TestClient, db, interviewer_auth_headers: dict, test_interviewer,
    test_position, test_resume, test_user
):
    offer = _sent_offer(db, test_position, test_resume, test_user)

    response = client.get("/api/offers", headers=interviewer_auth_headers)
    assert response.status_code == status.HTTP_403_FORBIDDEN

    test_position.hiring_manager_id = test_interviewer.id
    db.commit()
    response = client.get("/api/offers", headers=interviewer_auth_headers)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_offer_management_timestamps_are_explicit_utc(
    client: TestClient, db, auth_headers: dict, test_position, test_resume, test_user
):
    _sent_offer(db, test_position, test_resume, test_user)

    response = client.get("/api/offers", headers=auth_headers)

    assert response.status_code == status.HTTP_200_OK
    offer = response.json()["items"][0]
    assert offer["created_at"].endswith(("Z", "+00:00"))
    assert offer["sent_at"].endswith(("Z", "+00:00"))

def test_hiring_manager_can_decide_and_correct_with_an_audit_trail(
    client: TestClient, db, auth_headers: dict, test_interviewer,
    test_position, test_resume, test_user
):
    offer = _sent_offer(db, test_position, test_resume, test_user)

    accepted = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert accepted.status_code == status.HTTP_200_OK
    db.refresh(offer)
    db.refresh(test_resume)
    assert offer.status == OfferStatus.ACCEPTED
    assert test_resume.status == ResumeStatus.OFFER_ACCEPTED

    missing_reason = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=auth_headers,
        json={"decision": "rejected", "rejection_reason": "salary"},
    )
    assert missing_reason.status_code == status.HTTP_400_BAD_REQUEST

    corrected = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=auth_headers,
        json={
            "decision": "rejected",
            "rejection_reason": "other",
            "rejection_detail": "候选人调整了职业计划",
            "correction_reason": "候选人撤回了此前的接受决定",
        },
    )
    assert corrected.status_code == status.HTTP_200_OK
    db.refresh(offer)
    db.refresh(test_resume)
    assert offer.status == OfferStatus.REJECTED
    assert test_resume.status == ResumeStatus.OFFER_REJECTED
    audits = db.query(OfferDecisionAudit).filter_by(offer_id=offer.id).all()
    assert [(row.previous_status, row.new_status) for row in audits] == [
        ("sent", "accepted"),
        ("accepted", "rejected"),
    ]


def test_non_owner_hr_cannot_decide_but_admin_can(
    client: TestClient, db, auth_headers: dict, admin_auth_headers: dict,
    test_position, test_resume, test_user, test_admin
):
    test_position.hiring_manager_id = test_admin.id
    db.commit()
    offer = _sent_offer(db, test_position, test_resume, test_user)

    denied = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert denied.status_code == status.HTTP_404_NOT_FOUND

    accepted = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=admin_auth_headers,
        json={"decision": "accepted"},
    )
    assert accepted.status_code == status.HTTP_200_OK


def test_admin_can_override_an_assigned_manager_and_status_cannot_be_edited(
    client: TestClient, db, admin_auth_headers: dict, auth_headers: dict,
    test_interviewer, test_position, test_resume, test_user
):
    offer = _sent_offer(db, test_position, test_resume, test_user)

    denied = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=admin_auth_headers,
        json={"decision": "accepted"},
    )
    assert denied.status_code == status.HTTP_200_OK

    bypass = client.put(
        f"/api/offers/{offer.id}",
        headers=auth_headers,
        json={"status": "accepted"},
    )
    assert bypass.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_owner_can_edit_pending_offer_and_clear_optional_fields(
    client: TestClient, db, auth_headers: dict,
    test_position, test_resume, test_user
):
    offer = Offer(
        tenant_id=test_position.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        candidate_name=test_resume.candidate_name,
        candidate_email=test_resume.email,
        position_title=test_position.title,
        department="原部门",
        notes="待清空",
        status=OfferStatus.PENDING,
        created_by=test_user.id,
    )
    db.add(offer)
    db.commit()

    response = client.put(
        f"/api/offers/{offer.id}",
        headers=auth_headers,
        json={
            "position_title": "高级研发工程师",
            "department": "研发中心",
            "salary_monthly": 30000,
            "notes": None,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["position_title"] == "高级研发工程师"
    assert response.json()["department"] == "研发中心"
    assert response.json()["salary_monthly"] == "30000.0"
    assert response.json()["notes"] is None
    db.refresh(offer)
    assert offer.notes is None


def test_accepted_offer_can_be_edited(
    client: TestClient, db, auth_headers: dict,
    test_position, test_resume, test_user
):
    offer = _sent_offer(db, test_position, test_resume, test_user)
    offer.status = OfferStatus.ACCEPTED
    db.commit()

    response = client.put(
        f"/api/offers/{offer.id}",
        headers=auth_headers,
        json={"salary_monthly": 30000},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["salary_monthly"] == "30000.0"


def test_offer_template_routes_forbid_interviewer(
    client: TestClient, interviewer_auth_headers: dict
):
    response = client.get("/api/offer-templates", headers=interviewer_auth_headers)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_owner_can_delete_draft_offer(
    client: TestClient, db, auth_headers: dict, test_position, test_resume, test_user
):
    offer = Offer(
        tenant_id=test_position.tenant_id,
        resume_id=test_resume.id,
        position_id=test_position.id,
        candidate_name=test_resume.candidate_name,
        candidate_email=test_resume.email,
        position_title=test_position.title,
        status=OfferStatus.DRAFT,
        created_by=test_user.id,
    )
    db.add(offer)
    db.commit()
    offer_id = offer.id

    response = client.delete(f"/api/offers/{offer_id}", headers=auth_headers)

    assert response.status_code == status.HTTP_200_OK
    assert db.query(Offer).filter(Offer.id == offer_id).first() is None
