from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.config.database import get_db
from app.schemas.dashboard import (
    DashboardData, DashboardStats, Activity, TrendData,
    RecruitmentFunnel, PositionAnalyticsResponse, InterviewerAnalyticsResponse,
    TimelineAnalyticsResponse, OverviewResponse
)
from app.services.dashboard_service import (
    get_dashboard_stats, get_recent_activities, get_interview_trends,
    get_recruitment_funnel, get_position_analytics, get_interviewer_analytics,
    get_timeline_analytics, get_overview
)
from app.models.models import User
from app.routes.auth import get_current_user

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    responses={404: {"description": "Not found"}},
)

@router.get("/stats", response_model=DashboardData)
def read_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stats = get_dashboard_stats(db)
    activities = get_recent_activities(db)
    trends = get_interview_trends(db)

    return {
        "stats": stats,
        "recent_activities": activities,
        "interview_trends": trends
    }

@router.get("/overview", response_model=OverviewResponse)
def read_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_overview(db)

@router.get("/funnel", response_model=RecruitmentFunnel)
def read_funnel(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_recruitment_funnel(db)

@router.get("/positions", response_model=PositionAnalyticsResponse)
def read_position_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_position_analytics(db)

@router.get("/interviewers", response_model=InterviewerAnalyticsResponse)
def read_interviewer_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_interviewer_analytics(db)

@router.get("/timeline", response_model=TimelineAnalyticsResponse)
def read_timeline_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    days: int = Query(default=30, ge=7, le=365, description="Number of days to analyze")
):
    return get_timeline_analytics(db, days)
