from fastapi import status
from fastapi.testclient import TestClient


def test_offer_routes_forbid_interviewer(
    client: TestClient, interviewer_auth_headers: dict
):
    response = client.get("/api/offers", headers=interviewer_auth_headers)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_offer_template_routes_forbid_interviewer(
    client: TestClient, interviewer_auth_headers: dict
):
    response = client.get("/api/offer-templates", headers=interviewer_auth_headers)

    assert response.status_code == status.HTTP_403_FORBIDDEN
