from uuid import UUID
from datetime import datetime
import logging

from app.config.tenant_session import tenant_session
from app.models.models import CodingSubmission, CodingSubmissionStatus, CodingTest
from app.services.ai_service import generate_coding_test_evaluation

logger = logging.getLogger(__name__)


def generate_coding_evaluation_background(tenant_id: UUID, submission_id: UUID):
    with tenant_session(tenant_id) as db:
        sub = db.query(CodingSubmission).filter(CodingSubmission.id == submission_id).first()
        if not sub:
            logger.warning(
                "Coding evaluation resource not found",
                extra={"tenant_id": str(tenant_id), "resource_id": str(submission_id)},
            )
            return
        test = db.query(CodingTest).filter(CodingTest.id == sub.coding_test_id).first()
        if not test:
            return

        evaluation = generate_coding_test_evaluation(
            title=test.title,
            description=test.description,
            language=sub.language,
            code=sub.code,
            run_result=sub.run_result or {},
            db=db,
        )

        sub.ai_evaluation = evaluation.get("evaluation")
        sub.status = CodingSubmissionStatus.EVALUATED
        sub.evaluated_at = datetime.utcnow()
        db.commit()

