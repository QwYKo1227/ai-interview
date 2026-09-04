import React, { useCallback, useEffect, useState } from 'react';
import { Card, Table, Button, Tag, Space, message, Typography, Empty, Spin, Tabs, Input } from 'antd';
import { EyeOutlined, SearchOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
import request from '../../utils/request';
import { PAGE_SIZE_OPTIONS, useDebouncedQueryValue, useListPageState, useListScrollRestoration, useNavigateFromList } from '../../hooks/useListPageState';

const { Title, Text } = Typography;

interface AssignedReview {
  review_id: string;
  resume_id: string;
  candidate_name: string;
  position_title: string;
  match_score: number;
  status: string;
  is_completed: boolean;
  overall_score?: number;
  recommendation?: 'recommend' | 'not_recommend' | 'pending';
  created_at: string;
  completed_at?: string;
}

interface ReviewListResponse {
  items: AssignedReview[];
  total: number;
  pending_total: number;
  completed_total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

const MyReviews: React.FC = () => {
  const { user } = useAuth();
  const navigateFromList = useNavigateFromList();
  const { page, pageSize, searchParams, setPagination, setQuery } = useListPageState();
  useListScrollRestoration();
  const [loading, setLoading] = useState(false);
  const [reviews, setReviews] = useState<AssignedReview[]>([]);
  const activeTab = searchParams.get('tab') === 'completed' ? 'completed' : 'pending';
  const search = searchParams.get('search') || '';
  const [searchDraft, setSearchDraft] = useDebouncedQueryValue('search', search, setQuery);
  const [total, setTotal] = useState(0);
  const [pendingTotal, setPendingTotal] = useState(0);
  const [completedTotal, setCompletedTotal] = useState(0);

  const fetchReviews = useCallback(async () => {
    if (!user?.id) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({
        completed: String(activeTab === 'completed'),
        page: String(page),
        page_size: String(pageSize),
      });
      if (search) params.set('search', search);
      const res = await request.get(`/resumes/my-reviews?${params.toString()}`) as ReviewListResponse;
      setReviews(res.items);
      setTotal(res.total);
      setPendingTotal(res.pending_total);
      setCompletedTotal(res.completed_total);
    } catch {
      message.error('获取评审列表失败');
    } finally {
      setLoading(false);
    }
  }, [activeTab, page, pageSize, search, user?.id]);

  useEffect(() => {
    fetchReviews();
  }, [fetchReviews]);

  const recommendationTag = (value?: AssignedReview['recommendation']) => {
    if (!value) return '-';
    const labels = {
      recommend: { text: '推荐', color: 'green' },
      not_recommend: { text: '不推荐', color: 'red' },
      pending: { text: '待定', color: 'gold' },
    };
    const item = labels[value];
    return <Tag color={item.color}>{item.text}</Tag>;
  };

  const columns = [
    {
      title: '候选人',
      dataIndex: 'candidate_name',
      key: 'candidate_name',
      render: (text: string) => <span style={{ fontWeight: 500 }}>{text || '未知'}</span>,
    },
    {
      title: '应聘岗位',
      dataIndex: 'position_title',
      key: 'position_title',
    },
    {
      title: 'AI匹配度',
      dataIndex: 'match_score',
      key: 'match_score',
      render: (score: number) => (
        <Tag color={score >= 80 ? 'green' : score >= 60 ? 'orange' : 'red'}>
          {score}%
        </Tag>
      ),
    },
    {
      title: '指派时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => new Date(date).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: AssignedReview) => (
        <Space>
          <Button
            type={record.is_completed ? 'default' : 'primary'}
            icon={<EyeOutlined />}
            onClick={() => navigateFromList(`/resumes/${record.resume_id}?review_id=${record.review_id}`)}
          >
            {record.is_completed ? '查看' : '查看并评审'}
          </Button>
        </Space>
      ),
    },
  ];

  const completedColumns = [
    ...columns.slice(0, 2),
    {
      title: '我的结论',
      dataIndex: 'recommendation',
      key: 'recommendation',
      render: recommendationTag,
    },
    {
      title: '综合评分',
      dataIndex: 'overall_score',
      key: 'overall_score',
      render: (score?: number) => score ? `${score}/10` : '-',
    },
    {
      title: '完成时间',
      dataIndex: 'completed_at',
      key: 'completed_at',
      render: (date?: string) => date ? new Date(date).toLocaleString('zh-CN') : '-',
    },
    columns[columns.length - 1],
  ];

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0 }}>我的评审</Title>
        <Text type="secondary">查看待处理任务和您已提交的评审记录</Text>
      </div>

      <Card>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索候选人或岗位"
          style={{ width: 320, marginBottom: 16 }}
          value={searchDraft}
          onChange={(event) => setSearchDraft(event.target.value)}
          onPressEnter={(event) => {
            setQuery({ search: event.currentTarget.value.trim() || undefined, page: undefined });
          }}
          onClear={() => {
            setQuery({ search: undefined, page: undefined });
          }}
        />
        <Tabs
          activeKey={activeTab}
          onChange={(key) => {
            setQuery({ tab: key === 'completed' ? key : undefined, page: undefined });
          }}
          items={[
            { key: 'pending', label: `待我评审 (${pendingTotal})` },
            { key: 'completed', label: `我已评审 (${completedTotal})` },
          ]}
        />
        {reviews.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={activeTab === 'pending' ? '暂无待评审的简历' : '暂无已评审的简历'} />
        ) : (
          <Table
            columns={activeTab === 'pending' ? columns : completedColumns}
            dataSource={reviews}
            rowKey="review_id"
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: PAGE_SIZE_OPTIONS,
              onChange: setPagination,
            }}
          />
        )}
      </Card>
    </div>
  );
};

export default MyReviews;
