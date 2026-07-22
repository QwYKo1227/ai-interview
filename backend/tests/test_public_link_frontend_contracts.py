from pathlib import Path


FRONTEND = Path(__file__).parents[2] / "frontend" / "src" / "pages"


def test_manual_offer_send_preserves_one_time_link_contract():
    source = (FRONTEND / "Offers" / "List.tsx").read_text(encoding="utf-8")

    success_check = source.index("if (!result?.success)")
    email_check = source.index("if (values.send_email && !result?.email_sent)")
    link_delivery = source.index("showOfferLink(result.token")

    assert success_check < email_check < link_delivery
    assert "localStorage.setItem" not in source
    assert "console.log(result.token" not in source


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
