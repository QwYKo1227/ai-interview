"""
面试路由单元测试
测试 POST /interviews, GET /interviews, GET /interviews/{id},
POST /interviews/{id}/start, POST /interviews/{id}/cancel,
POST /interviews/{id}/confirm, GET /interviews/{id}/submission-status 等
"""

import pytest
from uuid import uuid4
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from fastapi import status
from sqlalchemy.orm import Session

from app.models.models import (
    Interview, InterviewStatus, InterviewResult, InterviewPanel,
    User, UserRole
)


class TestCreateInterviewRoute:
    """测试 POST /interviews 创建面试路由"""

    def test_create_interview_success(self, client: TestClient, auth_headers: dict,
                                       test_resume, test_position, test_interviewer, db: Session):
        """测试成功创建面试"""
        # 确保 test_interviewer fixture 被使用，这样 interview 表会被创建
        # 同时确保面试官在数据库中
        db.add(test_interviewer)
        db.commit()

        response = client.post(
            "/api/interviews",
            json={
                "resume_id": str(test_resume.id),
                "position_id": str(test_position.id),
                "interviewer": "主面试官",
                "interview_time": "2024-12-15T10:00:00Z",
                "interview_location": "上海办公室",
                "meeting_link": "https://meeting.example.com/interview",
                "panel_members": []
            },
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["resume_id"] == str(test_resume.id)
        assert data["status"] == "scheduled"

    def test_create_interview_unauthorized(self, client: TestClient,
                                            test_resume, test_position):
        """测试未授权创建面试"""
        response = client.post(
            "/api/interviews",
            json={
                "resume_id": str(test_resume.id),
                "position_id": str(test_position.id)
            }
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_interview_forbidden_for_interviewer(self, client: TestClient,
                                                         interviewer_auth_headers: dict,
                                                         test_resume, test_position,
                                                         test_interviewer: User, db: Session):
        """测试面试官无权创建面试"""
        # 确保面试官在数据库中
        db.add(test_interviewer)
        db.commit()

        response = client.post(
            "/api/interviews",
            json={
                "resume_id": str(test_resume.id),
                "position_id": str(test_position.id),
                "interview_time": "2024-12-15T10:00:00Z",
                "interview_location": "上海办公室",
                "meeting_link": "https://meeting.example.com/interview"
            },
            headers=interviewer_auth_headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestGetInterviewsRoute:
    """测试 GET /interviews 获取面试列表路由"""

    def test_get_interviews_success(self, client: TestClient, auth_headers: dict,
                                    test_interview: Interview):
        """测试成功获取面试列表"""
        response = client.get("/api/interviews", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) >= 1


    def test_realtime_session_uses_ephemeral_token_and_hides_upstream_url(
        self,
        client: TestClient,
        interviewer_auth_headers: dict,
        test_interview: Interview,
        test_interviewer: User,
        db: Session,
        monkeypatch,
    ):
        from app.routes import interviews

        session_id = uuid4()
        test_interview.lifecycle_state = "in_progress"
        test_interview.recording_state = "recording"
        test_interview.recording_session_id = session_id
        test_interview.recording_owner_id = test_interviewer.id
        db.commit()
        monkeypatch.setattr(interviews, "get_transcription_config", lambda _db: {"provider": "openai_compatible"})
        monkeypatch.setattr(
            interviews,
            "create_realtime_session",
            lambda _config: {
                "token": "ephemeral-token",
                "expires_at": "2026-07-29T12:00:00+00:00",
                "ws_url": "ws://private-asr/v1/audio/transcriptions/stream",
            },
        )

        response = client.post(
            f"/api/interviews/{test_interview.id}/recording/realtime-session",
            headers=interviewer_auth_headers,
            json={"session_id": str(session_id)},
        )

        assert response.status_code == 200
        assert response.json() == {
            "token": "ephemeral-token",
            "expires_at": "2026-07-29T12:00:00+00:00",
            "ws_path": "/asr-stream",
        }

    def test_get_interviews_with_status_filter(self, client: TestClient, auth_headers: dict,
                                                test_interview: Interview):
        """测试按状态过滤面试列表"""
        response = client.get(
            "/api/interviews?status=scheduled",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert all(i["status"] == "scheduled" for i in data)

    def test_get_interviews_unauthorized(self, client: TestClient):
        """测试未授权获取面试列表"""
        response = client.get("/api/interviews")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_interviews_for_interviewer(self, client: TestClient, interviewer_auth_headers: dict,
                                            test_interview: Interview, test_interviewer: User, db: Session):
        """测试面试官只能看到自己参与的面试"""
        # 确保面试官在数据库中
        db.add(test_interviewer)
        db.commit()

        response = client.get("/api/interviews", headers=interviewer_auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # 面试官只能看到自己是 panel_members 的面试
        for interview in data:
            assert str(test_interviewer.id) in (interview.get("panel_members") or [])


class TestGetInterviewRoute:
    """测试 GET /interviews/{id} 获取面试详情路由"""

    def test_get_interview_success(self, client: TestClient, auth_headers: dict,
                                   test_interview: Interview):
        """测试成功获取面试详情"""
        response = client.get(
            f"/api/interviews/{test_interview.id}",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(test_interview.id)

    def test_get_interview_not_found(self, client: TestClient, auth_headers: dict):
        """测试获取不存在的面试"""
        fake_id = uuid4()
        response = client.get(
            f"/api/interviews/{fake_id}",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_interview_includes_relations(self, client: TestClient, auth_headers: dict,
                                               test_interview: Interview):
        """测试获取面试详情包含关联数据"""
        response = client.get(
            f"/api/interviews/{test_interview.id}",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # 检查关联数据是否加载
        assert "resume" in data
        assert "position" in data

    def test_get_interview_includes_transcripts(self, client: TestClient, auth_headers: dict,
                                                test_interview: Interview, db: Session):
        test_interview.transcripts = {
            "full_interview": "Complete interview transcript",
            "0": "Answer to the first question",
        }
        db.commit()

        response = client.get(
            f"/api/interviews/{test_interview.id}",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["transcripts"] == {
            "full_interview": "Complete interview transcript",
            "0": "Answer to the first question",
        }


class TestStartInterviewRoute:
    """测试 POST /interviews/{id}/start 开始面试路由"""

    def test_start_interview_success(self, client: TestClient, auth_headers: dict,
                                     test_interview: Interview):
        """测试成功开始面试"""
        assert test_interview.status == InterviewStatus.SCHEDULED

        response = client.post(
            f"/api/interviews/{test_interview.id}/start",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "in_progress"

    def test_start_interview_not_found(self, client: TestClient, auth_headers: dict):
        """测试开始不存在的面试"""
        fake_id = uuid4()
        response = client.post(
            f"/api/interviews/{fake_id}/start",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_start_interview_wrong_status(self, client: TestClient, auth_headers: dict,
                                           test_interview_in_progress: Interview):
        """测试面试状态不正确时无法开始"""
        response = client.post(
            f"/api/interviews/{test_interview_in_progress.id}/start",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestCancelInterviewRoute:
    """测试 POST /interviews/{id}/cancel 取消面试路由"""

    def test_cancel_interview_success(self, client: TestClient, auth_headers: dict,
                                      test_interview: Interview):
        """测试成功取消面试"""
        response = client.post(
            f"/api/interviews/{test_interview.id}/cancel?reason=Schedule%20changed&notify=false",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "cancelled"

    def test_cancel_interview_with_reason(self, client: TestClient, auth_headers: dict,
                                          test_interview: Interview):
        """测试带原因取消面试"""
        response = client.post(
            f"/api/interviews/{test_interview.id}/cancel?reason=候选人临时有事&notify=false",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK

    def test_cancel_succeeds_when_notification_delivery_fails(
        self,
        client: TestClient,
        auth_headers: dict,
        test_interview: Interview,
        db: Session,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "app.services.mail_service.get_mail_service",
            lambda _db: (_ for _ in ()).throw(RuntimeError("mail unavailable")),
        )

        response = client.post(
            f"/api/interviews/{test_interview.id}/cancel?reason=Schedule%20changed",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["notification_sent"] is False
        db.refresh(test_interview)
        assert test_interview.status == InterviewStatus.CANCELLED
        assert test_interview.lifecycle_state == "cancelled"

    def test_cancel_interview_not_found(self, client: TestClient, auth_headers: dict):
        """测试取消不存在的面试"""
        fake_id = uuid4()
        response = client.post(
            f"/api/interviews/{fake_id}/cancel?reason=Schedule%20changed&notify=false",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestForceEndInterviewRoute:
    def test_hr_can_force_end_without_recording_session(
        self,
        client: TestClient,
        auth_headers: dict,
        test_interview: Interview,
        db: Session,
    ):
        test_interview.lifecycle_state = "in_progress"
        test_interview.recording_state = "idle"
        test_interview.status = InterviewStatus.IN_PROGRESS
        db.commit()

        response = client.post(
            f"/api/interviews/{test_interview.id}/force-end",
            headers=auth_headers,
            json={"reason": "候选人提前离开"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["lifecycle_state"] == "ended"
        assert response.json()["recording_state"] == "failed"
        assert response.json()["status"] == "completed"

    def test_interviewer_cannot_force_end(
        self,
        client: TestClient,
        interviewer_auth_headers: dict,
        test_interview: Interview,
        db: Session,
    ):
        test_interview.lifecycle_state = "in_progress"
        test_interview.status = InterviewStatus.IN_PROGRESS
        db.commit()

        response = client.post(
            f"/api/interviews/{test_interview.id}/force-end",
            headers=interviewer_auth_headers,
            json={"reason": "Not authorized"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_force_end_requires_reason(
        self,
        client: TestClient,
        auth_headers: dict,
        test_interview: Interview,
        db: Session,
    ):
        test_interview.lifecycle_state = "in_progress"
        test_interview.status = InterviewStatus.IN_PROGRESS
        db.commit()

        response = client.post(
            f"/api/interviews/{test_interview.id}/force-end",
            headers=auth_headers,
            json={"reason": "  "},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestConfirmInterviewRoute:
    """测试 POST /interviews/{id}/confirm 确认面试结果路由"""

    def test_confirm_interview_passed(self, client: TestClient, auth_headers: dict,
                                      test_interview: Interview, test_interview_panel: InterviewPanel, db: Session):
        """测试确认面试通过"""
        test_interview.status = InterviewStatus.COMPLETED
        test_interview.result = InterviewResult.PENDING
        test_interview.lifecycle_state = "ended"
        test_interview_panel.human_review_submitted_at = datetime.now(timezone.utc)
        db.commit()

        response = client.post(
            f"/api/interviews/{test_interview.id}/confirm",
            json={"result": "passed"},
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["result"] == "passed"

    def test_confirm_interview_rejected(self, client: TestClient, auth_headers: dict,
                                        test_interview: Interview, test_interview_panel: InterviewPanel, db: Session):
        """测试确认面试未通过"""
        test_interview.status = InterviewStatus.COMPLETED
        test_interview.lifecycle_state = "ended"
        test_interview_panel.human_review_submitted_at = datetime.now(timezone.utc)
        db.commit()

        response = client.post(
            f"/api/interviews/{test_interview.id}/confirm",
            json={"result": "rejected"},
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["result"] == "rejected"

    def test_confirm_interview_not_found(self, client: TestClient, auth_headers: dict):
        """测试确认不存在面试的结果"""
        fake_id = uuid4()
        response = client.post(
            f"/api/interviews/{fake_id}/confirm",
            json={"result": "passed"},
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestGetSubmissionStatusRoute:
    """测试 GET /interviews/{id}/submission-status 获取提交状态路由"""

    def test_get_submission_status_success(self, client: TestClient, auth_headers: dict,
                                           test_interview: Interview):
        """测试成功获取提交状态"""
        response = client.get(
            f"/api/interviews/{test_interview.id}/submission-status",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "interview_id" in data
        assert "total_members" in data
        assert "submitted_count" in data
        assert "members" in data

    def test_get_submission_status_not_found(self, client: TestClient, auth_headers: dict):
        """测试获取不存在面试的提交状态"""
        fake_id = uuid4()
        response = client.get(
            f"/api/interviews/{fake_id}/submission-status",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpdateInterviewRoute:
    """测试 PUT /interviews/{id} 更新面试路由"""

    def test_update_interview_success(self, client: TestClient, auth_headers: dict,
                                      test_interview: Interview):
        """测试成功更新面试"""
        response = client.put(
            f"/api/interviews/{test_interview.id}",
            json={
                "interviewer": "新面试官",
                "interview_time": "2024-12-20T14:00:00Z"
            },
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["interviewer"] == "新面试官"

    def test_update_interview_not_found(self, client: TestClient, auth_headers: dict):
        """测试更新不存在的面试"""
        fake_id = uuid4()
        response = client.put(
            f"/api/interviews/{fake_id}",
            json={"interviewer": "新面试官"},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteInterviewRoute:
    """测试 DELETE /interviews/{id} 删除面试路由"""

    def test_delete_interview_success(self, client: TestClient, admin_auth_headers: dict,
                                      test_interview: Interview, test_admin: User, db: Session):
        """测试成功删除面试（管理员权限）"""
        # 确保管理员在数据库中
        db.add(test_admin)
        db.commit()

        response = client.delete(
            f"/api/interviews/{test_interview.id}",
            headers=admin_auth_headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_interview_unauthorized(self, client: TestClient,
                                           test_interview: Interview):
        """测试未授权删除面试"""
        response = client.delete(f"/api/interviews/{test_interview.id}")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_interview_forbidden_for_hr(self, client: TestClient, auth_headers: dict,
                                               test_interview: Interview):
        """测试HR也可以删除面试（根据当前实现，HR和ADMIN都可以删除）"""
        # 注意：当前实现允许 HR 和 ADMIN 都可以删除面试
        # 如果需要限制只有 ADMIN 可以删除，需要修改路由权限
        response = client.delete(
            f"/api/interviews/{test_interview.id}",
            headers=auth_headers
        )

        # 根据当前实现，HR 可以删除面试
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_interview_not_found(self, client: TestClient, admin_auth_headers: dict,
                                         test_admin: User, db: Session):
        """测试删除不存在的面试"""
        db.add(test_admin)
        db.commit()

        fake_id = uuid4()
        response = client.delete(
            f"/api/interviews/{fake_id}",
            headers=admin_auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestSubmitPanelScoreRoute:
    """测试 POST /interviews/{id}/panel-score 提交面试官评分路由"""

    def test_submit_panel_score_success(self, client: TestClient, interviewer_auth_headers: dict,
                                        test_interview: Interview, test_interviewer: User, db: Session):
        """测试成功提交面试官评分"""
        # 确保面试官在数据库中
        db.add(test_interviewer)
        db.commit()

        response = client.post(
            f"/api/interviews/{test_interview.id}/panel-score",
            json={
                "scores": {"0": 8, "1": 9},
                "comments": {"0": "不错", "1": "很好"}
            },
            headers=interviewer_auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_submitted"] is True

    def test_submit_panel_score_unauthorized(self, client: TestClient, test_interview: Interview):
        """测试未授权提交评分"""
        response = client.post(
            f"/api/interviews/{test_interview.id}/panel-score",
            json={"scores": {"0": 8}}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestUpdateQuestionsRoute:
    """测试 PUT /interviews/{id}/questions 更新面试问题路由"""

    def test_update_questions_success(self, client: TestClient, auth_headers: dict,
                                      test_interview: Interview):
        """测试成功更新面试问题"""
        new_questions = [
            {"title": "新问题1", "content": "问题内容1", "reference_answer": "答案1"},
            {"title": "新问题2", "content": "问题内容2", "reference_answer": "答案2"}
        ]

        response = client.put(
            f"/api/interviews/{test_interview.id}/questions",
            json=new_questions,
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["questions"]) == 2

    def test_update_questions_not_found(self, client: TestClient, auth_headers: dict):
        """测试更新不存在面试的问题"""
        fake_id = uuid4()
        response = client.put(
            f"/api/interviews/{fake_id}/questions",
            json=[],
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestExportInterviewRoute:
    """测试 GET /interviews/{id}/export 导出面试结果路由"""

    def test_export_interview_success(self, client: TestClient, auth_headers: dict,
                                      test_interview: Interview, db: Session):
        """测试成功导出面试结果"""
        test_interview.status = InterviewStatus.COMPLETED
        test_interview.result = InterviewResult.PASSED
        test_interview.evaluation = "候选人表现优秀"
        db.commit()

        response = client.get(
            f"/api/interviews/{test_interview.id}/export",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert "面试评估报告" in response.text

    def test_export_interview_not_found(self, client: TestClient, auth_headers: dict):
        """测试导出不存在面试的结果"""
        fake_id = uuid4()
        response = client.get(
            f"/api/interviews/{fake_id}/export",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAggregateScoresRoute:
    """测试 POST /interviews/{id}/aggregate 汇总评分路由"""

    def test_aggregate_scores_success(self, client: TestClient, auth_headers: dict,
                                      test_interview: Interview, test_interviewer: User,
                                      db: Session):
        """测试成功汇总评分"""
        # 创建已提交的面试官评分
        panel = InterviewPanel(
            id=uuid4(),
            tenant_id=test_interview.tenant_id,
            interview_id=test_interview.id,
            interviewer_id=test_interviewer.id,
            scores={"0": 8, "1": 9},
            comments={"0": "不错", "1": "很好"},
            total_score=8,
            is_submitted=True
        )
        db.add(panel)
        db.commit()

        response = client.post(
            f"/api/interviews/{test_interview.id}/aggregate",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "scores" in data

    def test_aggregate_scores_not_found(self, client: TestClient, auth_headers: dict):
        """测试汇总不存在面试的评分"""
        fake_id = uuid4()
        response = client.post(
            f"/api/interviews/{fake_id}/aggregate",
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestPermissionControl:
    """测试权限控制"""

    def test_hr_can_create_interview(self, client: TestClient, auth_headers: dict,
                                     test_resume, test_position):
        """测试HR可以创建面试"""
        response = client.post(
            "/api/interviews",
            json={
                "resume_id": str(test_resume.id),
                "position_id": str(test_position.id),
                "interview_time": "2024-12-15T10:00:00Z",
                "interview_location": "上海办公室",
                "meeting_link": "https://meeting.example.com/interview"
            },
            headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK

    def test_interviewer_cannot_create_interview(self, client: TestClient,
                                                  interviewer_auth_headers: dict,
                                                  test_resume, test_position,
                                                  test_interviewer: User, db: Session):
        """测试面试官不能创建面试"""
        db.add(test_interviewer)
        db.commit()

        response = client.post(
            "/api/interviews",
            json={
                "resume_id": str(test_resume.id),
                "position_id": str(test_position.id)
            },
            headers=interviewer_auth_headers
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_delete_interview(self, client: TestClient, admin_auth_headers: dict,
                                         test_interview: Interview, test_admin: User, db: Session):
        """测试管理员可以删除面试"""
        db.add(test_admin)
        db.commit()

        response = client.delete(
            f"/api/interviews/{test_interview.id}",
            headers=admin_auth_headers
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_hr_cannot_delete_interview(self, client: TestClient, auth_headers: dict,
                                        test_interview: Interview):
        """测试HR可以删除面试（根据当前实现）"""
        # 注意：当前实现允许 HR 和 ADMIN 都可以删除面试
        response = client.delete(
            f"/api/interviews/{test_interview.id}",
            headers=auth_headers
        )

        # 根据当前实现，HR 可以删除面试
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestSpeakerLabelsRoute:
    def test_supports_more_than_two_speakers_without_changing_transcript(
        self,
        client: TestClient,
        auth_headers: dict,
        test_interview: Interview,
        db: Session,
    ):
        original_data = {
            "text": "one two three",
            "segments": [
                {"start": 0, "end": 1, "speaker": "speaker_0", "text": "one"},
                {"start": 1, "end": 2, "speaker": "speaker_1", "text": "two"},
                {"start": 2, "end": 3, "speaker": "speaker_2", "text": "three"},
            ],
        }
        test_interview.lifecycle_state = "ended"
        test_interview.transcripts = {"full_interview_data": original_data}
        db.commit()

        response = client.post(
            f"/api/interviews/{test_interview.id}/transcript/speaker-labels",
            json={
                "labels": {
                    "speaker_0": "候选人",
                    "speaker_1": "面试官张三",
                    "speaker_2": "面试官李四",
                }
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["transcripts"]["speaker_labels"]["speaker_2"] == "面试官李四"
        assert data["transcripts"]["full_interview_data"] == original_data


class TestInterviewerDisplayNames:
    def test_result_and_frozen_notes_include_interviewer_name(
        self,
        client: TestClient,
        auth_headers: dict,
        test_interview: Interview,
        test_interview_panel: InterviewPanel,
        test_interviewer: User,
        db: Session,
    ):
        test_interviewer.full_name = "面试官王老师"
        test_interview.lifecycle_state = "ended"
        test_interview.panel_members = [str(test_interviewer.id)]
        test_interview_panel.live_notes = "候选人解释了架构取舍。"
        db.commit()

        detail = client.get(f"/api/interviews/{test_interview.id}", headers=auth_headers)
        notes = client.get(f"/api/interviews/{test_interview.id}/notes", headers=auth_headers)

        assert detail.status_code == status.HTTP_200_OK
        assert detail.json()["panels"][0]["interviewer_name"] == "面试官王老师"
        assert notes.status_code == status.HTTP_200_OK
        assert notes.json()[0]["interviewer_name"] == "面试官王老师"
