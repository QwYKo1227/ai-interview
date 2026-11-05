import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Checkbox, DatePicker, Descriptions, Drawer, Empty, Form, Input, InputNumber, Modal, Pagination, Select, Space, Spin, Switch, Table, Tag, Timeline, Tooltip, Typography, message } from 'antd';
import { CheckCircleOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import request from '../../utils/request';
import { useAuth } from '../../contexts/AuthContext';
import { PAGE_SIZE_OPTIONS } from '../../hooks/useListPageState';
import type { Config, Metrics, Person, QualityRules, Report } from './types';
import CandidateFlowCard from './CandidateFlowCard';
import { currentLabel, flowSteps, groupCandidates, matchingFlows, nodeMatches } from './candidate-flow';
import type { CandidateFilters, FlowStep, FlowView } from './candidate-flow';
import { legendStates, statuses, statusFilters } from './statuses';
import { stepBusinessHref } from './business-links';
import './quality.css';

const { Text, Title } = Typography;
const stages = [
  ['screening', '初筛'], ['department', '部门评审'], ['interview', '面试与录用决策'],
  ['offer', 'Offer'], ['onboarding', '入职'], ['exception', '异常处理'],
];
const actionLabels: Record<string, string> = { note: '补充处理记录', waive: '记录例外（历史）', follow_up: '更新进展 / 催办（历史）', resolve: '登记异常处理结果（历史）', transition: '状态流转', offer_transition: 'Offer状态变更', rescheduled: '面试改期' };
const deadlineFields: [keyof QualityRules, string][] = [
  ['screening_days', '提交初筛结论'], ['department_assignment_days', '初筛通过 → 指派部门评审'],
  ['department_decision_days', '评审意见交齐 → HR决策'], ['interview_arrangement_days', '通过后 → 安排首轮面试'],
  ['next_interview_days', '进入下一轮 → 安排面试'], ['interview_decision_days', '反馈到齐 → 面试最终决策'],
  ['offer_send_days', '最终面试通过 / 重开 → 发送Offer'], ['result_update_days', '入职等结果登记'],
  ['exception_days', '面试进展、Offer到期等异常处理'],
];
const ownerKey = (id: string | null) => id ?? 'unassigned';
const time = (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '未设置';
const ratio = (value: number | null, numerator: number, denominator: number) => (
  <span className="quality-ratio"><strong>{value === null ? '暂无可统计项' : `${value}%`}</strong><Text type="secondary">{numerator} / {denominator}</Text></span>
);
function errorText(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : '加载或保存失败，请重试';
}

export default function RecruitmentQuality() {
  const { user } = useAuth();
  const admin = user?.role === 'admin';
  const manager = admin || user?.role === 'hr';
  const [report, setReport] = useState<Report | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const startDate = dateRange?.[0].format('YYYY-MM-DD');
  const endDate = dateRange?.[1].format('YYYY-MM-DD');
  const [owner, setOwner] = useState<string>();
  const [position, setPosition] = useState<string>();
  const [stage, setStage] = useState<string>();
  const [problem, setProblem] = useState('all');
  const [search, setSearch] = useState('');
  const [mine, setMine] = useState(false);
  const [selectedId, setSelectedId] = useState<string>();
  const [selection, setSelection] = useState<{ flow: FlowView; step: FlowStep }>();
  const [flowSelections, setFlowSelections] = useState<Record<string, string>>({});
  const [candidatePage, setCandidatePage] = useState(1);
  const [candidatePageSize, setCandidatePageSize] = useState(10);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [recordOpen, setRecordOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [policyForm] = Form.useForm<QualityRules & { name: string; position_id?: string }>();
  const [actionForm] = Form.useForm<{ reason: string }>();
  const sequence = useRef(0);
  const load = useCallback(async () => {
    if (!user?.id) return;
    const version = ++sequence.current;
    setLoading(true);
    setError('');
    try {
      const [data, settings] = await Promise.all([
        request.get('/recruitment-quality/overview', { params: { ...(startDate ? { start_date: startDate } : {}), ...(endDate ? { end_date: endDate } : {}) } }) as Promise<Report>,
        manager ? request.get('/recruitment-quality/config') as Promise<Config> : Promise.resolve(null),
      ]);
      if (version !== sequence.current) return;
      setReport(data);
      setConfig(settings);
    } catch (e) {
      if (version === sequence.current) { setError(errorText(e)); setReport(null); }
    } finally {
      if (version === sequence.current) setLoading(false);
    }
  }, [startDate, endDate, manager, user?.id]);
  useEffect(() => { void load(); return () => { sequence.current += 1; }; }, [load]);

  const filters: CandidateFilters = { owner: manager ? owner : undefined, position, stage, problem, search, mine, userId: user?.id };
  const candidates = useMemo(() => report ? groupCandidates(report) : [], [report]);
  const visibleCandidates = useMemo(() => candidates.flatMap(candidate => {
    const matchedFlows = matchingFlows(candidate, { owner: manager ? owner : undefined, position, stage, problem, search, mine, userId: user?.id });
    return matchedFlows.length ? [{ candidate, preferred: matchedFlows.find(f => f.is_current) ?? matchedFlows[0] }] : [];
  }), [candidates, owner, position, stage, problem, search, mine, manager, user?.id]);
  const page = Math.min(candidatePage, Math.max(1, Math.ceil(visibleCandidates.length / candidatePageSize)));
  const pageCandidates = visibleCandidates.slice((page - 1) * candidatePageSize, page * candidatePageSize);
  const selectedFlow = selection && (candidates.flatMap(c => c.flows).find(f => f.id === selection.flow.id) ?? selection.flow);
  const selectedStep = selectedFlow && selection && flowSteps(selectedFlow).find(s => s.id === selection.step.id);
  const selectedNodes = selectedStep ? [...selectedStep.nodes, ...selectedStep.exceptions] : [];
  const selected = report?.nodes.find(n => n.id === selectedId) ?? selectedNodes[0];
  const resetCandidates = () => { setCandidatePage(1); setFlowSelections({}); };
  const selectStep = (flow: FlowView, step: FlowStep) => {
    const choices = [...step.nodes, ...step.exceptions].sort((a, b) => Number(b.overdue) - Number(a.overdue));
    const chosen = choices.find(n => nodeMatches(n, filters)) ?? choices[0];
    setSelectedId(chosen?.id);
    setSelection({ flow, step });
  };

  const openRules = () => {
    const latest = config?.policies.filter(p => !p.position_id).at(-1);
    policyForm.setFieldsValue({ name: latest?.name ?? '标准招聘流程', position_id: undefined, ...(latest?.rules ?? config?.defaults) });
    setRulesOpen(true);
  };
  const publish = async () => {
    const values = await policyForm.validateFields().catch(() => null);
    if (!values) return;
    const { name, position_id, ...rules } = values;
    setSaving(true);
    try {
      await request.post('/recruitment-quality/policies', { name, position_id: position_id || null, rules });
      setRulesOpen(false);
      message.success('规则已发布；尚未开始计时的节点采用新配置');
      await load();
      window.dispatchEvent(new Event('recruitment-quality-updated'));
    } catch (e) { message.error(errorText(e)); } finally { setSaving(false); }
  };
  const saveAction = async () => {
    const values = await actionForm.validateFields().catch(() => null);
    if (!values) return;
    if (!selected) return;
    setSaving(true);
    try {
      await request.post(`/recruitment-quality/bindings/${selected.binding_id}/nodes/${encodeURIComponent(selected.key)}/actions`, {
        kind: 'note', reason: values.reason,
      });
      setRecordOpen(false);
      message.success('已补充处理记录');
      await load();
      window.dispatchEvent(new Event('recruitment-quality-updated'));
    } catch (e) { message.error(errorText(e)); } finally { setSaving(false); }
  };
  const beginRecord = () => { actionForm.resetFields(); setRecordOpen(true); };
  const columns = [
    { title: '跟进负责人', dataIndex: 'name', render: (name: string, p: Person) => <Button type="link" onClick={() => { setOwner(ownerKey(p.user_id)); resetCandidates(); }}>{name}</Button> },
    { title: '在招岗位 / 在办候选人', render: (_: unknown, p: Person) => `${p.open_position_count} / ${p.active_candidate_count}` },
    { title: '流程完整率', render: (_: unknown, p: Metrics) => ratio(p.process_rate, p.completed_nodes, p.required_nodes) },
  ];
  return <div className="quality-page">
    <header className="quality-heading">
      <div><Title level={2}>招聘过程质量</Title><Text type="secondary">查看每份简历的流程推进与结果更新是否及时。</Text></div>
      <Space><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>{admin && <Button aria-label="流程规则" icon={<SettingOutlined />} onClick={openRules}>流程规则</Button>}</Space>
    </header>
    {error && <Alert type="error" showIcon title={error} action={<Button onClick={() => void load()}>重试</Button>} />}
    <Spin spinning={loading}>
      {report && !report.enabled ? <div className="quality-panel"><Empty description={admin ? '启用后按已有操作记录核算流程完整率。' : '管理员尚未启用过程质量检查。'}>{admin && <Button type="primary" onClick={openRules}>启用标准流程</Button>}</Empty></div> : report && <>
        <div className="quality-summary">
          <div className="quality-signal"><CheckCircleOutlined /><span>流程完整率{ratio(report.summary.process_rate, report.summary.completed_nodes, report.summary.required_nodes)}</span></div>
          <Text type="secondary">按业务阶段统计结果登记和后续推进；未到期事项暂不考核，逾期补齐仍保留逾期。备选暂停，恢复后重新给完整期限。</Text>
        </div>
        <div className="quality-panel">
          <div className="quality-section-heading quality-overview-heading">
            <Title level={4}>{manager ? '人员总览' : '我的流程记录'}</Title>
            <div className="quality-overview-filters">
              <span>流程开始日期</span>
              <DatePicker.RangePicker aria-label="流程开始日期"
                value={dateRange} placeholder={['开始日期', '结束日期']}
                onChange={value => {
                  setDateRange(value?.[0] && value[1] ? [value[0], value[1]] : null);
                  resetCandidates(); setSelection(undefined); setSelectedId(undefined);
                }}
                presets={[
                  { label: '今天', value: () => [dayjs(), dayjs()] },
                  { label: '近7天', value: () => [dayjs().subtract(6, 'day'), dayjs()] },
                  { label: '近30天', value: () => [dayjs().subtract(29, 'day'), dayjs()] },
                  { label: '本月', value: () => [dayjs().startOf('month'), dayjs()] },
                ]} />
            </div>
          </div>
          <Table<Person> rowKey={p => ownerKey(p.user_id)} columns={columns} dataSource={report.people} pagination={{ defaultPageSize: 10, pageSizeOptions: PAGE_SIZE_OPTIONS, showSizeChanger: true, hideOnSinglePage: report.people.length <= 10 }} scroll={{ x: 950 }} locale={{ emptyText: '当前范围暂无人员流程记录' }} />
        </div>
        <div className="quality-panel">
          <div className="quality-section-heading"><Title level={4}>候选人招聘流程</Title><Text type="secondary">共 {visibleCandidates.length} 位候选人</Text></div>
          <div className="quality-filters">
            {manager && <Select aria-label="跟进负责人" placeholder="全部负责人" allowClear value={owner} onChange={value => { setOwner(value); resetCandidates(); }} options={report.people.map(p => ({ value: ownerKey(p.user_id), label: p.name }))} />}
            {manager && <Select aria-label="岗位" placeholder="全部岗位" allowClear showSearch optionFilterProp="label" value={position} onChange={value => { setPosition(value); resetCandidates(); }} options={report.positions.map(p => ({ value: p.id, label: p.title }))} />}
            <Select aria-label="流程节点" placeholder="全部流程节点" allowClear value={stage} onChange={value => { setStage(value); resetCandidates(); }}
              options={stages.map(([value, label]) => ({ value, label }))} />
            <Select aria-label="流程状态" value={problem} onChange={value => { setProblem(value); resetCandidates(); }}
              options={statusFilters} popupMatchSelectWidth={320} listHeight={360}
              optionRender={option => <div className="quality-status-option">
                <span>{option.data.label}</span><small>{option.data.description}</small>
              </div>} />
            <Input.Search aria-label="搜索流程记录" placeholder="搜索候选人、岗位或负责人" value={search} allowClear onChange={e => { setSearch(e.target.value); resetCandidates(); }} />
            <Checkbox checked={mine} onChange={e => { setMine(e.target.checked); resetCandidates(); }}>只看待我处理</Checkbox>
            <Button onClick={() => { setOwner(undefined); setPosition(undefined); setStage(undefined); setProblem('all'); setSearch(''); setMine(false); resetCandidates(); }}>重置筛选</Button>
          </div>
          <div className="quality-track-legend" aria-label="流程状态图例">
            {legendStates.map(state => <Tooltip key={state} title={statuses[state].description}>
              <span className={`is-${state}`}>{statuses[state].label}</span>
            </Tooltip>)}
          </div>
          <div className="quality-candidate-list" aria-label="候选人流程列表">
            {pageCandidates.map(({ candidate, preferred }) => <CandidateFlowCard key={candidate.id}
              candidate={candidate} flow={candidate.flows.find(f => f.id === flowSelections[candidate.id]) ?? preferred}
              filters={filters} onFlowChange={id => setFlowSelections(current => ({ ...current, [candidate.id]: id }))}
              onSelect={selectStep} />)}
            {!pageCandidates.length && <Empty description="当前筛选下没有候选人，可调整阶段或问题类型" />}
          </div>
          <Pagination className="quality-candidate-pagination" current={page} pageSize={candidatePageSize}
            total={visibleCandidates.length} showSizeChanger pageSizeOptions={PAGE_SIZE_OPTIONS}
            showTotal={total => `共 ${total} 位候选人`}
            onChange={(next, size) => { setCandidatePage(size === candidatePageSize ? next : 1); setCandidatePageSize(size); }} />
        </div>
      </>}
    </Spin>
    <Drawer title={selected?.label ?? selectedStep?.label ?? '节点详情'} open={!!selection} onClose={() => { setSelection(undefined); setSelectedId(undefined); }} size="large">
      {selectedNodes.length > 1 && <Select className="quality-node-picker" aria-label="查看节点记录"
        value={selected?.id} onChange={setSelectedId} options={selectedNodes.map(n => ({
          value: n.id, label: `${n.label} · ${statuses[n.status]?.label ?? n.status}`,
        }))} />}
      {!selected && selectedFlow && selectedStep && <Space orientation="vertical" size="large">
        <Descriptions column={1} items={[
          { key: 'candidate', label: '候选人 / 岗位', children: `${candidates.find(c => c.id === selectedFlow.resume_id)?.name ?? ''} / ${selectedFlow.position_title}` },
          { key: 'status', label: '当前进度', children: currentLabel(selectedFlow) },
          ...(selectedStep.stage === 'interview' ? [{ key: 'schedule', label: '面试时间', children: selectedStep.interview?.scheduled_at
            ? time(selectedStep.interview.scheduled_at) : selectedStep.current ? '等待安排' : '缺少面试时间记录' }] : []),
        ]} />
        <Text type="secondary">{selectedStep.current ? '该环节尚在办理，结果提交后可查看时效依据。' : '此阶段缺少可核实的操作记录，无法判定当时是否及时。'}</Text>
        <Button type="primary" onClick={() => window.open(stepBusinessHref(selectedFlow, selectedStep), '_blank', 'noopener,noreferrer')}>进入业务页面处理</Button>
      </Space>}
      {selected && <Space orientation="vertical" size="large" style={{ width: '100%' }}>
        <Descriptions column={1} items={[
          { key: 'candidate', label: '候选人 / 岗位', children: `${selected.candidate_name ?? '岗位公共资料'} / ${selected.position_title}` },
          { key: 'owner', label: '跟进负责人', children: selected.owner_name }, { key: 'executor', label: '当前待办执行人', children: selected.executor_name },
          { key: 'template', label: '适用流程', children: `${selected.policy_name} v${selected.policy_version}` },
          { key: 'due', label: '办理期限', children: time(selected.due_at) },
          { key: 'state', label: '检查结果', children: <Tag color={statuses[selected.status]?.color}>{statuses[selected.status]?.label}</Tag> },
        ]} />
        {selected.historical && <Alert type="info" showIcon title="历史记录缺少证据时只能标记为无法核实，不代表当时未执行。" />}
        <div>
          <Title level={5}>结果登记与推进依据</Title>
          {selected.fields.map((f, i) => <div key={i} className="quality-requirement">
            <Tag color={f.late_due_at ? 'error' : f.valid ? 'success' : 'default'}>{f.status ?? (f.valid ? '按期完成' : '待办理')}</Tag>{f.label}
            {f.due_at && <p><Text type="secondary">期限：{time(f.due_at)} 提交：{f.completed_at ? time(f.completed_at) : '尚未提交'}{f.policy_version ? ` · 规则 v${f.policy_version}` : ''}</Text></p>}
            {f.late_due_at && f.late_due_at !== f.due_at && <p><Text type="danger">此前逾期截止时间：{time(f.late_due_at)}</Text></p>}
          </div>)}
          {selected.evidence.map(e => <p key={e}><Text type="secondary">{e}</Text></p>)}
        </div>
        <Space wrap><Button type="primary" onClick={() => window.open(selected.href, '_blank', 'noopener,noreferrer')}>进入业务页面处理</Button>
          {manager && (admin || selected.executor_id === user?.id) && <Button onClick={beginRecord}>补充处理记录</Button>}
        </Space>
        <div><Title level={5}>处理记录</Title>{selected.actions.length ? <Timeline items={selected.actions.map((a, i) => ({ key: i, content: <><Text strong>{actionLabels[a.kind] ?? a.kind}</Text><p>{a.reason}</p><Text type="secondary">{a.actor_name ?? (a.actor_id ? '已记录操作人' : '系统处理')} · {time(a.occurred_at)}</Text>{a.details.expected_resume_at && <p>预计恢复：{time(a.details.expected_resume_at)}</p>}</> }))} /> : <Text type="secondary">暂无额外处理记录</Text>}</div>
      </Space>}
    </Drawer>
    <Modal title={report?.enabled ? '发布新版本流程规则' : '启用标准招聘流程'} open={rulesOpen} onCancel={() => setRulesOpen(false)} onOk={() => void publish()} confirmLoading={saving} okText={report?.enabled ? '发布新版本' : '启用检查'} destroyOnHidden>
      <Alert type="info" showIcon title="期限按中国大陆工作日计算，包含调休补班。新配置用于尚未开始计时的节点；已开始计时和历史逾期保持不变。" />
      <Form form={policyForm} layout="vertical" style={{ marginTop: 20 }}>
        <Form.Item name="name" label="流程名称" rules={[{ required: true, whitespace: true }]}><Input maxLength={100} /></Form.Item>
        {report?.enabled && <Form.Item name="position_id" label="适用岗位（留空为全局默认）"><Select allowClear showSearch optionFilterProp="label" onChange={(id) => {
          const latest = config?.policies.filter(p => p.position_id === (id ?? null)).at(-1) ?? config?.policies.filter(p => !p.position_id).at(-1);
          policyForm.setFieldsValue({ ...(latest?.rules ?? config?.defaults), name: latest?.name ?? '标准招聘流程' });
        }} options={report.positions.map(p => ({ value: p.id, label: p.title }))} /></Form.Item>}
        {deadlineFields.map(([key, label]) => <Form.Item key={key} name={key} label={label + '（工作日）'} rules={[{ required: true }]}><InputNumber min={1} max={60} precision={0} /></Form.Item>)}
        <Form.Item name="department_review_required" label="部门评审为必需步骤" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
    <Modal title="补充处理记录" open={recordOpen} onCancel={() => setRecordOpen(false)} onOk={() => void saveAction()} confirmLoading={saving} okText="保存记录" destroyOnHidden>
      <Alert type="info" showIcon title="记录进展、沟通情况、异常原因及处理结果，仅供留痕。流程进度和质量检查以业务页面的实际操作为准。" />
      <Form form={actionForm} layout="vertical" style={{ marginTop: 20 }}>
        <Form.Item name="reason" label="记录内容" rules={[{ required: true, whitespace: true, message: '请填写记录内容' }]}><Input.TextArea rows={3} maxLength={1000} showCount /></Form.Item>
      </Form>
    </Modal>
  </div>;
}
