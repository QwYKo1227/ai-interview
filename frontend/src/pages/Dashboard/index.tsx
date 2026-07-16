import React, { useEffect, useState } from 'react';
import { Card, Row, Col, List, Avatar, Typography, Spin, message, Table, Tag, Progress, Statistic, Tabs, Select, Empty } from 'antd';
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Legend, LineChart, Line, PieChart, Pie, Cell, FunnelChart, Funnel, LabelList
} from 'recharts';
import { 
  UserOutlined, FileTextOutlined, TeamOutlined, BankOutlined,
  ArrowUpOutlined, ClockCircleOutlined, ArrowDownOutlined,
  CheckCircleOutlined, CloseCircleOutlined, SyncOutlined,
  TrophyOutlined, RiseOutlined, FallOutlined
} from '@ant-design/icons';
import request from '../../utils/request';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const { Title, Text } = Typography;
const { TabPane } = Tabs;
const { Option } = Select;

interface TrendData {
  date: string;
  count: number;
}

interface DashboardStats {
  active_positions: number;
  pending_resumes: number;
  today_interviews: number;
  total_questions: number;
  trends: {
    active_positions: number;
    pending_resumes: number;
    today_interviews: number;
    total_questions: number;
  };
}

interface Activity {
  id: string;
  title: string;
  time: string;
  status: string;
  avatar_color: string;
  type: string;
}

interface FunnelStage {
  stage: string;
  stage_name: string;
  count: number;
  percentage: number;
}

interface RecruitmentFunnel {
  stages: FunnelStage[];
  total_resumes: number;
  conversion_rate: number;
}

interface PositionAnalytics {
  id: string;
  title: string;
  department: string;
  status: string;
  total_resumes: number;
  pending_screening: number;
  pending_interview: number;
  interview_completed: number;
  offer_sent: number;
  hired: number;
  rejected: number;
  avg_match_score: number | null;
  avg_processing_days: number | null;
  conversion_rate: number;
}

interface InterviewerStats {
  id: string;
  name: string;
  total_interviews: number;
  completed_interviews: number;
  pending_interviews: number;
  completion_rate: number;
  avg_score: number | null;
  score_std: number | null;
  consistency_rating: string;
}

interface TimelineDataPoint {
  date: string;
  resumes_received: number;
  interviews_scheduled: number;
  interviews_completed: number;
  offers_sent: number;
  hires: number;
}

interface OverviewMetrics {
  total_positions: number;
  active_positions: number;
  total_resumes: number;
  pending_resumes: number;
  total_interviews: number;
  completed_interviews: number;
  total_offers: number;
  accepted_offers: number;
  avg_time_to_hire: number | null;
  avg_match_score: number | null;
  interview_pass_rate: number;
  offer_accept_rate: number;
}

const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16'];

const Dashboard: React.FC = () => {
  const [statsData, setStatsData] = useState<DashboardStats | null>(null);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [funnel, setFunnel] = useState<RecruitmentFunnel | null>(null);
  const [positions, setPositions] = useState<PositionAnalytics[]>([]);
  const [interviewers, setInterviewers] = useState<InterviewerStats[]>([]);
  const [timeline, setTimeline] = useState<TimelineDataPoint[]>([]);
  const [overview, setOverview] = useState<OverviewMetrics | null>(null);
  const [timelineDays, setTimelineDays] = useState(30);

  useEffect(() => {
    fetchAllData();
  }, []);

  useEffect(() => {
    fetchTimelineData(timelineDays);
  }, [timelineDays]);

  const fetchAllData = async () => {
    setLoading(true);
    try {
      const [statsRes, funnelRes, positionsRes, interviewersRes, overviewRes] = await Promise.all([
        request.get('/dashboard/stats'),
        request.get('/dashboard/funnel'),
        request.get('/dashboard/positions'),
        request.get('/dashboard/interviewers'),
        request.get('/dashboard/overview')
      ]);
      
      setStatsData(statsRes.stats);
      setActivities(statsRes.recent_activities);
      setFunnel(funnelRes);
      setPositions(positionsRes.positions);
      setInterviewers(interviewersRes.interviewers);
      setOverview(overviewRes.metrics);
    } catch (error) {
      console.error(error);
      message.error('获取仪表盘数据失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchTimelineData = async (days: number) => {
    try {
      const res = await request.get(`/dashboard/timeline?days=${days}`);
      setTimeline(res.timeline);
    } catch (error) {
      console.error(error);
    }
  };

  const stats = [
    {
      title: "招聘中岗位",
      value: statsData?.active_positions || 0,
      icon: <UserOutlined style={{ fontSize: '20px', color: '#3B82F6' }} />,
      color: '#EFF6FF',
      trend: statsData?.trends.active_positions || 0
    },
    {
      title: "待筛选简历",
      value: statsData?.pending_resumes || 0,
      icon: <FileTextOutlined style={{ fontSize: '20px', color: '#EF4444' }} />,
      color: '#FEF2F2',
      trend: statsData?.trends.pending_resumes || 0
    },
    {
      title: "今日面试",
      value: statsData?.today_interviews || 0,
      icon: <TeamOutlined style={{ fontSize: '20px', color: '#10B981' }} />,
      color: '#ECFDF5',
      trend: statsData?.trends.today_interviews || 0
    },
    {
      title: "面试题库",
      value: statsData?.total_questions || 0,
      icon: <BankOutlined style={{ fontSize: '20px', color: '#8B5CF6' }} />,
      color: '#F5F3FF',
      trend: statsData?.trends.total_questions || 0
    }
  ];

  const defaultTrends = Array.from({ length: 7 }, (_, i) => ({
    date: dayjs().subtract(6 - i, 'day').format('YYYY-MM-DD'),
    count: 0
  }));

  const positionColumns = [
    {
      title: '岗位名称',
      dataIndex: 'title',
      key: 'title',
      render: (text: string, record: PositionAnalytics) => (
        <div>
          <Text strong>{text}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>{record.department}</Text>
        </div>
      )
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const colorMap: Record<string, string> = {
          'open': 'blue',
          'published': 'green',
          'closed': 'default'
        };
        const textMap: Record<string, string> = {
          'open': '开放中',
          'published': '已发布',
          'closed': '已关闭'
        };
        return <Tag color={colorMap[status] || 'default'}>{textMap[status] || status}</Tag>;
      }
    },
    {
      title: '简历数',
      dataIndex: 'total_resumes',
      key: 'total_resumes',
      sorter: (a: PositionAnalytics, b: PositionAnalytics) => a.total_resumes - b.total_resumes
    },
    {
      title: '待初筛',
      dataIndex: 'pending_screening',
      key: 'pending_screening',
      render: (val: number, record: PositionAnalytics) => (
        <Text type={val > 0 ? 'warning' : 'secondary'}>{val}</Text>
      )
    },
    {
      title: '待面试',
      dataIndex: 'pending_interview',
      key: 'pending_interview',
      render: (val: number) => (
        <Text type={val > 0 ? 'warning' : 'secondary'}>{val}</Text>
      )
    },
    {
      title: '已录用',
      dataIndex: 'hired',
      key: 'hired',
      render: (val: number) => (
        <Text type="success" strong>{val}</Text>
      )
    },
    {
      title: '转化率',
      dataIndex: 'conversion_rate',
      key: 'conversion_rate',
      render: (rate: number) => (
        <Progress 
          percent={rate} 
          size="small" 
          format={(percent) => `${percent?.toFixed(1)}%`}
          strokeColor={rate >= 20 ? '#10B981' : rate >= 10 ? '#F59E0B' : '#EF4444'}
        />
      )
    }
  ];

  const interviewerColumns = [
    {
      title: '面试官',
      dataIndex: 'name',
      key: 'name',
      render: (text: string) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#3B82F6' }} />
          <Text strong>{text}</Text>
        </div>
      )
    },
    {
      title: '总面试数',
      dataIndex: 'total_interviews',
      key: 'total_interviews',
      sorter: (a: InterviewerStats, b: InterviewerStats) => a.total_interviews - b.total_interviews
    },
    {
      title: '已完成',
      dataIndex: 'completed_interviews',
      key: 'completed_interviews'
    },
    {
      title: '完成率',
      dataIndex: 'completion_rate',
      key: 'completion_rate',
      render: (rate: number) => (
        <Progress 
          percent={rate} 
          size="small" 
          format={(percent) => `${percent?.toFixed(1)}%`}
          strokeColor={rate >= 80 ? '#10B981' : rate >= 50 ? '#F59E0B' : '#EF4444'}
        />
      )
    },
    {
      title: '平均评分',
      dataIndex: 'avg_score',
      key: 'avg_score',
      render: (score: number | null) => score ? <Text strong>{score.toFixed(1)}</Text> : <Text type="secondary">-</Text>
    },
    {
      title: '评分一致性',
      dataIndex: 'consistency_rating',
      key: 'consistency_rating',
      render: (rating: string) => {
        const colorMap: Record<string, string> = {
          '非常一致': 'success',
          '较为一致': 'warning',
          '波动较大': 'error',
          '数据不足': 'default'
        };
        return <Tag color={colorMap[rating] || 'default'}>{rating}</Tag>;
      }
    }
  ];

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', minHeight: '400px' }}>
        <Spin size="large" tip="正在加载数据..." />
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 32 }}>
        <Title level={2} style={{ margin: 0, fontWeight: 700 }}>数据分析</Title>
        <Text type="secondary">招聘数据概览与深度分析</Text>
      </div>

      <Row gutter={[24, 24]}>
        {stats.map((stat, index) => (
          <Col xs={24} sm={12} lg={6} key={index}>
            <Card bordered={false} hoverable style={{ height: '100%', border: '1px solid #E2E8F0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <Text type="secondary" style={{ fontSize: '13px', fontWeight: 500 }}>{stat.title}</Text>
                  <div style={{ fontSize: '32px', fontWeight: 700, margin: '8px 0', lineHeight: 1, color: '#0F172A' }}>
                    {stat.value}
                  </div>
                  <div style={{ 
                    fontSize: '13px', 
                    fontWeight: 500,
                    display: 'flex', 
                    alignItems: 'center',
                    color: stat.trend > 0 ? '#10B981' : (stat.trend < 0 ? '#EF4444' : '#64748B')
                  }}>
                    {stat.trend > 0 ? <ArrowUpOutlined style={{ marginRight: 4 }} /> : (stat.trend < 0 ? <ArrowDownOutlined style={{ marginRight: 4 }} /> : null)}
                    {stat.trend !== 0 ? `${Math.abs(stat.trend)} 本周新增` : '无变化'}
                  </div>
                </div>
                <div style={{ 
                  width: '48px',
                  height: '48px',
                  borderRadius: '12px', 
                  background: stat.color,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  {stat.icon}
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[24, 24]} style={{ marginTop: 24 }}>
        <Col xs={24} lg={8}>
          <Card 
            title={<span style={{ fontSize: 16, fontWeight: 600 }}>核心指标</span>} 
            bordered={false} 
            style={{ height: '100%', borderRadius: '12px', border: '1px solid #E2E8F0' }}
          >
            <Row gutter={[16, 16]}>
              <Col span={12}>
                <Statistic 
                  title="面试通过率" 
                  value={overview?.interview_pass_rate || 0} 
                  suffix="%" 
                  valueStyle={{ color: overview?.interview_pass_rate && overview.interview_pass_rate >= 50 ? '#10B981' : '#EF4444' }}
                />
              </Col>
              <Col span={12}>
                <Statistic 
                  title="Offer接受率" 
                  value={overview?.offer_accept_rate || 0} 
                  suffix="%" 
                  valueStyle={{ color: overview?.offer_accept_rate && overview.offer_accept_rate >= 70 ? '#10B981' : '#F59E0B' }}
                />
              </Col>
              <Col span={12}>
                <Statistic 
                  title="平均招聘周期" 
                  value={overview?.avg_time_to_hire || '-'} 
                  suffix={overview?.avg_time_to_hire ? '天' : ''} 
                />
              </Col>
              <Col span={12}>
                <Statistic 
                  title="平均匹配分" 
                  value={overview?.avg_match_score || '-'} 
                  valueStyle={{ color: overview?.avg_match_score && overview.avg_match_score >= 70 ? '#10B981' : '#F59E0B' }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card 
            title={<span style={{ fontSize: 16, fontWeight: 600 }}>招聘漏斗</span>} 
            bordered={false} 
            style={{ height: '100%', borderRadius: '12px', border: '1px solid #E2E8F0' }}
          >
            {funnel && funnel.stages.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {funnel.stages.map((stage, index) => (
                  <div key={stage.stage} style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                    <div style={{ width: 80, textAlign: 'right' }}>
                      <Text type="secondary">{stage.stage_name}</Text>
                    </div>
                    <div style={{ flex: 1 }}>
                      <Progress 
                        percent={stage.percentage} 
                        strokeColor={COLORS[index % COLORS.length]}
                        format={() => `${stage.count}人`}
                      />
                    </div>
                  </div>
                ))}
                <div style={{ marginTop: 16, padding: '12px 16px', background: '#F8FAFC', borderRadius: 8 }}>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Text type="secondary">总简历数：</Text>
                      <Text strong>{funnel.total_resumes}</Text>
                    </Col>
                    <Col span={12}>
                      <Text type="secondary">整体转化率：</Text>
                      <Text strong style={{ color: '#10B981' }}>{funnel.conversion_rate}%</Text>
                    </Col>
                  </Row>
                </div>
              </div>
            ) : (
              <Empty description="暂无数据" />
            )}
          </Card>
        </Col>
      </Row>

      <Card 
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 16, fontWeight: 600 }}>时间趋势分析</span>
            <Select value={timelineDays} onChange={setTimelineDays} style={{ width: 120 }}>
              <Option value={7}>近7天</Option>
              <Option value={14}>近14天</Option>
              <Option value={30}>近30天</Option>
              <Option value={60}>近60天</Option>
              <Option value={90}>近90天</Option>
            </Select>
          </div>
        }
        bordered={false} 
        style={{ marginTop: 24, borderRadius: '12px', border: '1px solid #E2E8F0' }}
      >
        <div style={{ height: 350, width: '100%' }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={timeline}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
              <XAxis 
                dataKey="date" 
                tick={{ fill: '#64748B', fontSize: 12 }} 
                axisLine={false}
                tickLine={false}
                tickFormatter={(value) => dayjs(value).format('MM-DD')}
              />
              <YAxis 
                tick={{ fill: '#64748B', fontSize: 12 }} 
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip 
                contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)' }}
                labelFormatter={(label) => dayjs(label).format('YYYY年MM月DD日')}
              />
              <Legend />
              <Line type="monotone" dataKey="resumes_received" name="简历接收" stroke="#3B82F6" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="interviews_scheduled" name="面试安排" stroke="#F59E0B" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="interviews_completed" name="面试完成" stroke="#10B981" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="hires" name="入职" stroke="#8B5CF6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Tabs defaultActiveKey="positions" style={{ marginTop: 24 }}>
        <TabPane tab="岗位分析" key="positions">
          <Card bordered={false} style={{ borderRadius: '12px', border: '1px solid #E2E8F0' }}>
            <Table 
              dataSource={positions} 
              columns={positionColumns} 
              rowKey="id"
              pagination={{ pageSize: 10 }}
              locale={{ emptyText: '暂无岗位数据' }}
            />
          </Card>
        </TabPane>
        <TabPane tab="面试官分析" key="interviewers">
          <Card bordered={false} style={{ borderRadius: '12px', border: '1px solid #E2E8F0' }}>
            <Table 
              dataSource={interviewers} 
              columns={interviewerColumns} 
              rowKey="id"
              pagination={{ pageSize: 10 }}
              locale={{ emptyText: '暂无面试官数据' }}
            />
          </Card>
        </TabPane>
        <TabPane tab="最新动态" key="activities">
          <Card bordered={false} style={{ borderRadius: '12px', border: '1px solid #E2E8F0' }}>
            <List
              itemLayout="horizontal"
              dataSource={activities}
              locale={{ emptyText: '暂无动态' }}
              renderItem={item => (
                <List.Item style={{ padding: '16px 0', borderBottom: '1px solid #F1F5F9' }}>
                  <List.Item.Meta
                    avatar={
                      <Avatar 
                        icon={<UserOutlined />} 
                        style={{ 
                          backgroundColor: item.avatar_color, 
                          color: '#fff',
                          boxShadow: '0 2px 4px rgba(0,0,0,0.1)' 
                        }} 
                      />
                    }
                    title={<span style={{ fontWeight: 500, color: '#0F172A' }}>{item.title}</span>}
                    description={
                      <div style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                        <ClockCircleOutlined style={{ color: '#94A3B8' }} /> 
                        <span style={{ color: '#64748B' }}>{dayjs(item.time).fromNow()}</span>
                        <Tag style={{ marginLeft: 8 }} color={item.avatar_color}>{item.status}</Tag>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </TabPane>
      </Tabs>
    </div>
  );
};

export default Dashboard;
