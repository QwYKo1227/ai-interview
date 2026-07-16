import React from 'react';
import { createBrowserRouter, Navigate, useLocation } from 'react-router-dom';
import AppLayout from '../components/Layout';
import Login from '../pages/Login/index';
import Dashboard from '../pages/Dashboard';
import PositionsList from '../pages/Positions/List';
import PositionForm from '../pages/Positions/Form';
import QuestionBanksList from '../pages/QuestionBanks/List';
import QuestionBankUpload from '../pages/QuestionBanks/Upload';
import ResumesList from '../pages/Resumes/List';
import ResumeUpload from '../pages/Resumes/Upload';
import ResumeDetail from '../pages/Resumes/Detail';
import InterviewsList from '../pages/Interviews/List';
import InterviewScore from '../pages/Interviews/Score';
import InterviewResultPage from '../pages/Interviews/Result';
import PublicJobDetail from '../pages/Public/JobDetail';
import PublicCodingTest from '../pages/Public/CodingTest';
import CodingTestsList from '../pages/CodingTests/List';
import OffersList from '../pages/Offers/List';
import OfferTemplates from '../pages/Offers/Templates';
import OfferConfirm from '../pages/Offers/Confirm';
import UsersList from '../pages/Settings/Users';
import ProfileSettings from '../pages/Settings/Profile';
import SystemSettingsPage from '../pages/Settings/System';
import PublicReview from '../pages/Public/Review';
import WorkflowsList from '../pages/Workflows/List';
import WorkflowEditor from '../pages/Workflows/Editor';
import { useAuth } from '../contexts/AuthContext';
import { Spin } from 'antd';

const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}><Spin size="large" /></div>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
};

const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/public/jobs/:id',
    element: <PublicJobDetail />,
  },
  {
    path: '/public/coding-tests/:token',
    element: <PublicCodingTest />,
  },
  {
    path: '/offer-confirm/:token',
    element: <OfferConfirm />,
  },
  {
    path: '/public/review/:resumeId/:reviewerId',
    element: <PublicReview />,
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      {
        path: '/',
        element: <Navigate to="/dashboard" replace />,
      },
      {
        path: 'dashboard',
        element: <Dashboard />,
      },
      {
        path: 'positions',
        element: <PositionsList />,
      },
      {
        path: 'positions/new',
        element: <PositionForm />,
      },
      {
        path: 'positions/:id',
        element: <PositionForm />,
      },
      {
        path: 'question-banks',
        element: <QuestionBanksList />,
      },
      {
        path: 'question-banks/upload',
        element: <QuestionBankUpload />,
      },
      {
        path: 'resumes',
        element: <ResumesList />,
      },
      {
        path: 'resumes/upload',
        element: <ResumeUpload />,
      },
      {
        path: 'resumes/:id',
        element: <ResumeDetail />,
      },
      {
        path: 'interviews',
        element: <InterviewsList />,
      },
      {
        path: 'interviews/:id/score',
        element: <InterviewScore />,
      },
      {
        path: 'interviews/:id/result',
        element: <InterviewResultPage />,
      },
      {
        path: 'coding-tests',
        element: <CodingTestsList />,
      },
      {
        path: 'offers',
        element: <OffersList />,
      },
      {
        path: 'offers/templates',
        element: <OfferTemplates />,
      },
      {
        path: 'settings/users',
        element: <UsersList />,
      },
      {
        path: 'settings/profile',
        element: <ProfileSettings />,
      },
      {
        path: 'settings/system',
        element: <SystemSettingsPage />,
      },
      {
        path: 'workflows',
        element: <WorkflowsList />,
      },
      {
        path: 'workflows/:id',
        element: <WorkflowEditor />,
      },
    ],
  },
]);

export default router;