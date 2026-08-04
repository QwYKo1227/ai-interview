from pathlib import Path


FRONTEND = Path(__file__).parents[2] / "frontend" / "src" / "pages"


def test_offer_send_is_an_internal_confirmation_without_public_delivery():
    source = (FRONTEND / "Offers" / "List.tsx").read_text(encoding="utf-8")

    assert "确认Offer已发出" in source
    assert "Offer待确认" in source
    assert "showOfferLink" not in source
    assert "result.token" not in source
    assert "send_email" not in source
    assert "localStorage.setItem" not in source


def test_batch_review_links_keep_reviewer_identity_and_partial_results():
    source = (FRONTEND / "Resumes" / "Detail.tsx").read_text(encoding="utf-8")

    assert "Promise.allSettled" in source
    assert "reviewerId" in source
    assert "reviewerName" in source
    assert "successfulLinks" in source
    assert "failedReviewers" in source
    assert "showReviewLinks(successfulLinks, failedReviewers)" in source
    assert "localStorage.setItem" not in source
    assert "console.log(created?.public_token" not in source
