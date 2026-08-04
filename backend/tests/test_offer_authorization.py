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


def test_interviewer_only_sees_offers_for_positions_they_manage(
    client: TestClient, db, interviewer_auth_headers: dict, test_interviewer,
    test_position, test_resume, test_user
):
    offer = _sent_offer(db, test_position, test_resume, test_user)

    response = client.get("/api/offers", headers=interviewer_auth_headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["items"] == []

    test_position.hiring_manager_id = test_interviewer.id
    db.commit()
    response = client.get("/api/offers", headers=interviewer_auth_headers)
    assert response.status_code == status.HTTP_200_OK
    assert [item["id"] for item in response.json()["items"]] == [str(offer.id)]
    assert response.json()["items"][0]["can_decide"] is True


def test_hiring_manager_can_decide_and_correct_with_an_audit_trail(
    client: TestClient, db, interviewer_auth_headers: dict, test_interviewer,
    test_position, test_resume, test_user
):
    test_position.hiring_manager_id = test_interviewer.id
    offer = _sent_offer(db, test_position, test_resume, test_user)

    accepted = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=interviewer_auth_headers,
        json={"decision": "accepted"},
    )
    assert accepted.status_code == status.HTTP_200_OK
    db.refresh(offer)
    db.refresh(test_resume)
    assert offer.status == OfferStatus.ACCEPTED
    assert test_resume.status == ResumeStatus.OFFER_ACCEPTED

    missing_reason = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=interviewer_auth_headers,
        json={"decision": "rejected", "rejection_reason": "salary"},
    )
    assert missing_reason.status_code == status.HTTP_400_BAD_REQUEST

    corrected = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=interviewer_auth_headers,
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


def test_non_manager_hr_cannot_decide_but_admin_can_cover_unassigned_position(
    client: TestClient, db, auth_headers: dict, admin_auth_headers: dict,
    test_position, test_resume, test_user
):
    offer = _sent_offer(db, test_position, test_resume, test_user)

    denied = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=auth_headers,
        json={"decision": "accepted"},
    )
    assert denied.status_code == status.HTTP_403_FORBIDDEN

    accepted = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=admin_auth_headers,
        json={"decision": "accepted"},
    )
    assert accepted.status_code == status.HTTP_200_OK


def test_admin_cannot_override_an_assigned_manager_and_status_cannot_be_edited(
    client: TestClient, db, admin_auth_headers: dict, auth_headers: dict,
    test_interviewer, test_position, test_resume, test_user
):
    test_position.hiring_manager_id = test_interviewer.id
    offer = _sent_offer(db, test_position, test_resume, test_user)

    denied = client.post(
        f"/api/offers/{offer.id}/decision",
        headers=admin_auth_headers,
        json={"decision": "accepted"},
    )
    assert denied.status_code == status.HTTP_403_FORBIDDEN

    bypass = client.put(
        f"/api/offers/{offer.id}",
        headers=auth_headers,
        json={"status": "accepted"},
    )
    assert bypass.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_offer_template_routes_forbid_interviewer(
    client: TestClient, interviewer_auth_headers: dict
):
    response = client.get("/api/offer-templates", headers=interviewer_auth_headers)

    assert response.status_code == status.HTTP_403_FORBIDDEN
