import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  InputNumber,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  AuditOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import request from '../../utils/request';
import { useAuth } from '../../contexts/AuthContext';
import './performance.css';

const { Text, Title } = Typography;

type HcScore = {
  slot_id: string;
  slot_number: number;
  candidate_name?: string;
  result_stage: string;
  result_coefficient: number;
  target_days: number;
  actual_days: number;
  deducted_days: number;
  effective_held_days: number;
  time_coefficient: number;
  task_points: number;
  score: number;
  status: string;
};

type PositionScore = {
  position_id: string;
  title: string;
  category: string;
  priority: number;
  hc_count: number;
  onboarded_count: number;
  excluded_count: number;
  task_points: number;
  score: number;
  achievement_rate?: number;
  highest_result_stage: string;
  slots: HcScore[];
};

type HandoffCredit = {
  position_id: string;
  position_title: string;
  transferred_at: string;
  milestone_at: string;
  task_points: number;
  score: number;
  slots: HcScore[];
};

type PersonScore = {
  user_id: string;
  name: string;
  email: string;
  is_active: boolean;
  hc_count: number;
  excluded_count: number;
  onboarded_count: number;
  task_points: number;
  score: number;
  achievement_rate?: number;
  positions: PositionScore[];
  handoff_credits: HandoffCredit[];
};

type Overview = {
  period: string;
  as_of: string;
  status: 'trial' | 'live' | 'settled';
  settlement_version?: number;
  people: PersonScore[];
};

type LeaderboardEntry = {
  rank: number;
  name: string;
  achievement_rate: number;
  is_current_user: boolean;
};

type Leaderboard = {
  period: string;
  as_of: string;
  status: 'trial' | 'live' | 'settled';
  settlement_version?: number;
  entries: LeaderboardEntry[];
};

type Config = {
  effective_year: number;
  effective_quarter: number;
  target_days: Record<string, number>;
  time_coefficients: Record<string, number>;
  result_coefficients: Record<string, number>;
  status: string;
};

const categoryLabels: Record<string, string> = {
  campus: '校园招聘',
  domestic_functional: '国内职能岗位',
  domestic_rd: '国内研发岗位',
  overseas: '海外岗位',
  executive_expert: '高管／关键专家',
};
const timeLabels: Record<string, string> = {
  lte_80: '≤ 80%',
  '80_90': '> 80% 且 ≤ 90%',
  '90_100': '> 90% 且 ≤ 100%',
  '100_110': '> 100% 且 ≤ 110%',
  '110_130': '> 110% 且 ≤ 130%',
  '130_150': '> 130% 且 ≤ 150%',
  gt_150: '> 150%',
};
const resultLabels: Record<string, string> = {
  onboarded: '已入职',
  offer_accepted: '已接受 Offer',
  offer_pending: 'Offer 待确认',
  interview_passed: '面试通过，进入录用决策',
  business_interview_completed: '业务面完成',
  hr_interview_completed: 'HR 面完成',
  open: '岗位 Open',
};

const currentQuarter = () => `${dayjs().year()}-Q${Math.floor(dayjs().month() / 3) + 1}`;
const formatScore = (value: number) => Number(value || 0).toFixed(2);
const formatRate = (value?: number) => value == null ? '—' : `${(value * 100).toFixed(2)}%`;

const medalPalettes = {
  1: { ribbon: '#e0a20b', ribbonLight: '#ffd45d', face: '#ffedaa', border: '#efb72e', text: '#805400' },
  2: { ribbon: '#9aabc2', ribbonLight: '#dbe4ef', face: '#eef3f8', border: '#b7c4d5', text: '#52647d' },
  3: { ribbon: '#bd774c', ribbonLight: '#e6ae87', face: '#f5d3ba', border: '#cf8c61', text: '#7d4625' },
} as const;

const MedalIcon = ({ rank }: { rank: 1 | 2 | 3 }) => {
  const palette = medalPalettes[rank];
  return (
    <svg
      aria-label={`第 ${rank} 名`}
      className="performance-podium-medal"
      role="img"
      viewBox="0 0 40 48"
    >
      <path d="M6 3h12l4 12-8 7-5-10z" fill={palette.ribbonLight} stroke={palette.ribbon} />
      <path d="M22 3h12l-3 9-5 10-8-7z" fill={palette.ribbon} stroke={palette.ribbon} />
      <path d="M13 3h14l-7 14z" fill={palette.ribbonLight} opacity="0.72" />
      <circle cx="20" cy="31" fill={palette.face} r="13.5" stroke={palette.border} />
      <circle cx="20" cy="31" fill="none" opacity="0.52" r="10.5" stroke="#fff" />
      <text
        fill={palette.text}
        fontSize="15"
        fontWeight="700"
        textAnchor="middle"
        x="20"
        y="36"
      >
        {rank}
      </text>
    </svg>
  );
};

const PerformanceLeaderboard = ({ leaderboard, loading }: { leaderboard?: Leaderboard; loading: boolean }) => {
  const entries = leaderboard?.entries || [];
  const podium = entries.slice(0, 3);
  const remaining = entries.slice(3);

  return (
    <section
      aria-label="招聘绩效排行榜"
      className={`performance-leaderboard${loading ? ' is-loading' : ''}`}
    >
      {entries.length === 0 ? (
        <Empty className="performance-leaderboard-empty" description="暂无排名数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <div className="performance-podium">
            {podium.map(entry => (
              <div
                aria-current={entry.is_current_user ? 'true' : undefined}
                className={`performance-podium-entry performance-podium-entry--${entry.rank}`}
                key={entry.rank}
              >
                <div className="performance-podium-person">
                  <MedalIcon rank={entry.rank as 1 | 2 | 3} />
                  <Text strong>{entry.name}</Text>
                  <Text className="performance-podium-rate">{formatRate(entry.achievement_rate)}</Text>
                </div>
                <div aria-hidden="true" className="performance-podium-step" />
              </div>
            ))}
          </div>
          {remaining.length > 0 && (
            <div className="performance-rank-list">
              {remaining.map(entry => (
                <div
                  aria-current={entry.is_current_user ? 'true' : undefined}
                  className="performance-rank-row"
                  key={entry.rank}
                >
                  <Text className="performance-rank-number">{entry.rank}</Text>
                  <Text strong>{entry.name}</Text>
                  <Text className="performance-rank-rate">{formatRate(entry.achievement_rate)}</Text>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
};

const SlotLedger = ({ slots }: { slots: HcScore[] }) => (
  <div className="performance-ledger">
    <Table
      rowKey="slot_id"
      size="small"
      pagination={false}
      scroll={{ x: 980 }}
      dataSource={slots.filter(slot => !['cancelled', 'frozen'].includes(slot.status))}
      columns={[
        { title: 'HC', dataIndex: 'slot_number', width: 66, render: value => `#${value}` },
        { title: '候选人', dataIndex: 'candidate_name', render: value => value || <Text type="secondary">未占位</Text> },
        { title: '结果', dataIndex: 'result_stage', render: (value, row) => <Space><Tag color={row.status === 'completed' ? 'green' : 'blue'}>{value}</Tag><Text type="secondary">× {row.result_coefficient}</Text></Space> },
        { title: '目标', dataIndex: 'target_days', render: value => `${value}天` },
        { title: '累计实际', dataIndex: 'actual_days', render: value => `${value}天` },
        { title: '扣除', dataIndex: 'deducted_days', render: value => `${value}天` },
        { title: '有效持有', dataIndex: 'effective_held_days', render: value => `${value}天` },
        { title: '时间系数', dataIndex: 'time_coefficient' },
        { title: '任务积分', dataIndex: 'task_points', render: formatScore },
        { title: '得分', dataIndex: 'score', render: (value) => <Text strong>{formatScore(value)}</Text> },
      ]}
    />
  </div>
);

const PositionTable = ({ positions }: { positions: PositionScore[] }) => (
  <Table
    rowKey="position_id"
    pagination={false}
    scroll={{ x: 760 }}
    dataSource={positions}
    expandable={{ expandedRowRender: row => <SlotLedger slots={row.slots} /> }}
    columns={[
      { title: '岗位', dataIndex: 'title', render: (value, row) => <div><Text strong>{value}</Text><div><Text type="secondary">{categoryLabels[row.category] || row.category} · P{row.priority}</Text></div></div> },
      { title: 'HC', dataIndex: 'hc_count', render: (value, row) => `${value}（入职 ${row.onboarded_count}）` },
      { title: '最高阶段', dataIndex: 'highest_result_stage', render: value => <Tag>{value}</Tag> },
      { title: '任务积分', dataIndex: 'task_points', sorter: (a, b) => a.task_points - b.task_points, render: formatScore },
      { title: '得分', dataIndex: 'score', sorter: (a, b) => a.score - b.score, render: (value) => <Text strong>{formatScore(value)}</Text> },
      { title: '达成率', dataIndex: 'achievement_rate', sorter: (a, b) => (a.achievement_rate || 0) - (b.achievement_rate || 0), render: value => formatRate(value) },
    ]}
  />
);

const HandoffCreditTable = ({ credits }: { credits: HandoffCredit[] }) => {
  if (credits.length === 0) return null;
  return (
    <div className="performance-handoff-credits">
      <Title level={5}>录用阶段转交积分</Title>
      <Table
        rowKey={row => `${row.position_id}-${row.transferred_at}`}
        pagination={false}
        size="small"
        scroll={{ x: 720 }}
        dataSource={credits}
        expandable={{ expandedRowRender: row => <SlotLedger slots={row.slots} /> }}
        columns={[
          { title: '岗位', dataIndex: 'position_title', render: value => <Text strong>{value}</Text> },
          { title: '首次达到录用阶段', dataIndex: 'milestone_at', render: value => dayjs(value).format('YYYY-MM-DD HH:mm') },
          { title: '岗位转交时间', dataIndex: 'transferred_at', render: value => dayjs(value).format('YYYY-MM-DD HH:mm') },
          { title: '合格 HC', dataIndex: 'slots', render: value => value.length },
          { title: '冻结任务积分', dataIndex: 'task_points', render: formatScore },
          { title: '冻结得分', dataIndex: 'score', render: value => <Text strong>{formatScore(value)}</Text> },
        ]}
      />
    </div>
  );
};

const PersonDetails = ({ person }: { person: PersonScore }) => (
  <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <PositionTable positions={person.positions} />
    <HandoffCreditTable credits={person.handoff_credits || []} />
  </Space>
);

const ScoreWorkspace = ({ overview, admin }: { overview?: Overview; admin: boolean }) => {
  const people = overview?.people || [];
  const totals = useMemo(() => ({
    hc: people.reduce((sum, person) => sum + person.hc_count, 0),
    onboarded: people.reduce((sum, person) => sum + person.onboarded_count, 0),
  }), [people]);
  const averageScore = people.length
    ? people.reduce((sum, person) => sum + person.score, 0) / people.length
    : undefined;
  const achievedPeople = people.filter(person => person.achievement_rate != null);
  const averageRate = achievedPeople.length
    ? achievedPeople.reduce((sum, person) => sum + (person.achievement_rate || 0), 0) / achievedPeople.length
    : undefined;

  if (!overview) return null;
  return (
    <>
      <div className="performance-status-line">
        <Space wrap>
          {overview.status !== 'trial' && (
            <Tag color={overview.status === 'settled' ? 'green' : 'blue'}>
              {overview.status === 'settled' ? `已结算 V${overview.settlement_version}` : '实时预估'}
            </Tag>
          )}
          <Text type="secondary">数据截至 {overview.as_of}</Text>
        </Space>
      </div>
      <Row gutter={[16, 16]} className="performance-metrics">
        <Col xs={12} lg={6}><Card><Statistic title="有效HC" value={totals.hc} prefix={<TeamOutlined />} /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="已入职HC" value={totals.onboarded} prefix={<CheckCircleOutlined />} /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="平均绩效得分" value={averageScore == null ? '—' : formatScore(averageScore)} prefix={<AuditOutlined />} /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="平均达成率" value={averageRate == null ? '—' : (averageRate * 100).toFixed(2)} suffix={averageRate == null ? undefined : '%'} prefix={<ClockCircleOutlined />} /></Card></Col>
      </Row>
      <Card className="performance-table-card" variant="borderless">
        {people.length === 0 ? <Empty description="当前季度没有有效绩效任务" /> : admin ? (
          <Table
            rowKey="user_id"
            dataSource={people}
            pagination={false}
            scroll={{ x: 760 }}
            expandable={{ expandedRowRender: person => <PersonDetails person={person} /> }}
            columns={[
              { title: 'Recruiter', dataIndex: 'name', sorter: (a, b) => a.name.localeCompare(b.name), render: (value, row) => <div><Space><Text strong>{value}</Text>{!row.is_active && <Tag>已停用</Tag>}</Space><div><Text type="secondary">{row.email}</Text></div></div> },
              { title: 'HC任务', dataIndex: 'hc_count' },
              { title: '已入职', dataIndex: 'onboarded_count', sorter: (a, b) => a.onboarded_count - b.onboarded_count },
              { title: '任务积分', dataIndex: 'task_points', sorter: (a, b) => a.task_points - b.task_points, render: formatScore },
              { title: '得分', dataIndex: 'score', sorter: (a, b) => a.score - b.score, render: (value) => <Text strong>{formatScore(value)}</Text> },
              { title: '总达成率', dataIndex: 'achievement_rate', sorter: (a, b) => (a.achievement_rate || 0) - (b.achievement_rate || 0), render: value => formatRate(value) },
            ]}
          />
        ) : people[0] ? <PersonDetails person={people[0]} /> : null}
      </Card>
    </>
  );
};

const RuleSettings = ({ period }: { period: string }) => {
  const [form] = Form.useForm();
  const [config, setConfig] = useState<Config>();
  const [saving, setSaving] = useState(false);
  const load = async () => {
    const data = await request.get(`/recruitment-performance/config?period=${period}`);
    setConfig(data);
    form.setFieldsValue(data);
  };
  useEffect(() => { load().catch(() => message.error('获取绩效规则失败')); }, [period]);
  if (!config) return null;
  const publish = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await request.put('/recruitment-performance/config', values);
      message.success('绩效规则已发布');
      await load();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '发布失败');
    } finally { setSaving(false); }
  };
  return (
    <Form form={form} layout="vertical" className="rule-sheet">
      <Form.Item name="effective_year" hidden><InputNumber /></Form.Item>
      <Form.Item name="effective_quarter" hidden><InputNumber /></Form.Item>
      <Alert type="info" showIcon title={`正在编辑 ${config.effective_year}-Q${config.effective_quarter}，规则发布后仅对该季度生效。`} />
      <div className="rule-grid">
        <Card title="岗位分类目标时间" size="small">
          {Object.entries(categoryLabels).map(([key, label]) => <Form.Item key={key} name={['target_days', key]} label={`${label}（天）`} rules={[{ required: true }]}><InputNumber min={1} /></Form.Item>)}
        </Card>
        <Card title="时间系数（区间固定）" size="small">
          {Object.entries(timeLabels).map(([key, label]) => <Form.Item key={key} name={['time_coefficients', key]} label={label} rules={[{ required: true }]}><InputNumber min={0} max={2} step={0.1} /></Form.Item>)}
        </Card>
        <Card title="结果系数（阶段固定）" size="small">
          {Object.entries(resultLabels).map(([key, label]) => <Form.Item key={key} name={['result_coefficients', key]} label={label} rules={[{ required: true }]}><InputNumber min={0} max={1} step={0.1} /></Form.Item>)}
        </Card>
      </div>
      <Button type="primary" loading={saving} onClick={publish}>发布季度规则</Button>
    </Form>
  );
};

const RecruitmentPerformance: React.FC = () => {
  const { user } = useAuth();
  const role = (user as any)?.role?.value ?? (user as any)?.role;
  const admin = role === 'admin';
  const [period, setPeriod] = useState<string>();
  const [periods, setPeriods] = useState<string[]>([]);
  const [periodsLoading, setPeriodsLoading] = useState(true);
  const [overview, setOverview] = useState<Overview>();
  const [leaderboard, setLeaderboard] = useState<Leaderboard>();
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    setPeriodsLoading(true);
    request.get('/recruitment-performance/periods')
      .then((data: { periods: string[]; default_period: string }) => {
        if (!active) return;
        setPeriods(data.periods);
        setPeriod(current => current && data.periods.includes(current) ? current : data.default_period);
      })
      .catch(() => message.error('获取绩效季度失败'))
      .finally(() => { if (active) setPeriodsLoading(false); });
    return () => { active = false; };
  }, []);
  const load = async () => {
    if (!period) return;
    setLoading(true);
    try {
      const endpoint = admin ? 'overview' : 'me';
      const [overviewData, leaderboardData] = await Promise.all([
        request.get(`/recruitment-performance/${endpoint}?period=${period}`),
        request.get(`/recruitment-performance/leaderboard?period=${period}`),
      ]);
      setOverview(overviewData);
      setLeaderboard(leaderboardData);
    } catch { message.error('获取招聘绩效失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [period, admin]);
  const settle = () => Modal.confirm({
    title: `结算 ${period}`,
    content: '结算将生成不可变快照；后续更正会形成新的修订版本。',
    okText: '确认结算',
    onOk: async () => {
      try {
        await request.post(`/recruitment-performance/settlements/${period}`, {});
        message.success('季度已结算');
        await load();
      }
      catch (error: any) { message.error(error?.response?.data?.detail || '结算失败'); }
    },
  });
  const futureQuarter = useMemo(() => {
    const [year, q] = currentQuarter().split('-Q').map(Number);
    const absolute = year * 4 + q;
    return `${Math.floor(absolute / 4)}-Q${(absolute % 4) + 1}`;
  }, []);
  return (
    <div className="performance-page">
      <header className="performance-hero">
        <div className="performance-hero-title">
          <Title level={2}>招聘绩效</Title>
        </div>
        <PerformanceLeaderboard leaderboard={leaderboard} loading={loading} />
        <Space className="performance-hero-actions" wrap>
          <Select
            aria-label="绩效季度"
            value={period}
            options={periods.map(value => ({ value, label: value }))}
            onChange={setPeriod}
            loading={periodsLoading}
            disabled={periodsLoading || periods.length === 0}
            style={{ width: 128 }}
          />
          {admin && <Button icon={<AuditOutlined />} onClick={settle}>季度结算</Button>}
        </Space>
      </header>
      {admin ? (
        <Tabs
          items={[
            { key: 'overview', label: '人员概览', children: <div className={loading ? 'is-loading' : ''}><ScoreWorkspace overview={overview} admin /></div> },
            { key: 'rules', label: <Space><SettingOutlined />规则设置</Space>, children: <RuleSettings period={futureQuarter} /> },
          ]}
        />
      ) : <div className={loading ? 'is-loading' : ''}><ScoreWorkspace overview={overview} admin={false} /></div>}
    </div>
  );
};

export default RecruitmentPerformance;
