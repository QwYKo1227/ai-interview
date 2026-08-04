from pathlib import Path


FRONTEND = Path(__file__).parents[2] / "frontend" / "src" / "pages"


def test_offer_status_change_has_no_email_delivery_entry():
    source = (FRONTEND / "Offers" / "List.tsx").read_text(encoding="utf-8")

    assert "变更Offer状态" in source
    assert "批量标记待确认" in source
    assert "Offer待确认" in source
    assert "MailOutlined" not in source
    assert "批量发送" not in source
    assert "/mark-pending-confirmation" in source
    assert "/send" not in source
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
