import { describe, expect, it } from 'vitest';
import { currentLabel, currentStage, flowSteps, groupCandidates, matchingFlows, nextTask, nodeMatches } from './candidate-flow';
import { stepBusinessHref } from './business-links';
import type { FlowView } from './candidate-flow';
import type { QualityFlow, QualityNode, Report } from './types';

const makeFlow = (overrides: Partial<QualityFlow> = {}): QualityFlow => ({
  id: 'flow', binding_id: 'binding', resume_id: 'resume', position_id: 'position', position_title: '工程师',
  started_at: '2026-11-01T00:00:00Z', is_current: true, status: 'interview_scheduled', previous_status: null,
  department_required: false, owner_id: 'hr', owner_name: '招聘甲', interviews: [], ...overrides,
});
const makeNode = (overrides: Partial<QualityNode> = {}): QualityNode => ({
  id: 'node', flow_id: 'flow', binding_id: 'binding', key: 'screening', resume_id: 'resume', candidate_name: '同名候选人',
  position_id: 'position', position_title: '工程师', owner_id: 'hr', owner_name: '招聘甲', executor_id: 'hr', executor_name: '招聘甲',
  stage: 'screening', label: '初筛', status: 'complete', complete: true, eligible: true, historical: false,
  fields: [], missing: [], due_at: null, paused: false, overdue: false, overdue_hours: 0,
  href: '/resumes/resume', policy_id: 'policy', policy_name: '标准流程', policy_version: 1, evidence: [], actions: [], ...overrides,
});
const report = (nodes: QualityNode[], flows: QualityFlow[]) => ({ nodes, flows } as Report);

describe('candidate process grouping', () => {
  it('shows the newly scheduled interview in a round instead of its cancelled predecessor', () => {
    const flow: FlowView = { ...makeFlow({ status: 'interview_scheduled', interviews: [
      { id: 'cancelled', round: 1, status: 'cancelled', result: null, scheduled_at: '2026-11-01T10:00:00Z', ended_at: null, cancelled_at: '2026-11-01T09:00:00Z' },
      { id: 'new', round: 1, status: 'scheduled', result: null, scheduled_at: '2026-11-06T10:00:00Z', ended_at: null, cancelled_at: null },
    ] }), nodes: [makeNode({ key: 'interview:cancelled', stage: 'interview', label: '第1轮面试', business_status: 'terminated' })] };
    const step = flowSteps(flow).find(s => s.stage === 'interview')!;
    expect(step.state).toBe('pending');
    expect(step.interview?.id).toBe('new');
    expect(step.nodes).toHaveLength(0);
  });

  it('uses the latest Offer record when the current process has older withdrawn offers', () => {
    const flow: FlowView = { ...makeFlow({ status: 'offer_pending' }), nodes: [
      makeNode({ key: 'offer:old', stage: 'offer', business_status: 'completed', business_result: '已撤回' }),
      makeNode({ key: 'offer:new', stage: 'offer', business_status: 'pending', business_result: '等待候选人答复' }),
    ] };
    const step = flowSteps(flow).find(s => s.stage === 'offer')!;
    expect(step.state).toBe('pending');
    expect(step.result).toBe('等待候选人答复');
    expect(currentLabel(flow)).toBe('等待Offer答复');
    expect(nextTask(flow).label).not.toContain('已撤回');
  });

  it('shows withdrawn offers as withdrawn without continuing to ask for a reply or sending', () => {
    const flow: FlowView = { ...makeFlow({ status: 'offer_pending' }), nodes: [
      makeNode({ stage: 'offer', business_status: 'completed', business_result: '已撤回' }),
    ] };
    expect(currentLabel(flow)).toBe('Offer已撤回');
    expect(nextTask(flow).label).toContain('Offer已撤回');
    expect(nextTask(flow).due).toBeNull();
  });

  it('uses pending-send business facts instead of a stale waiting-for-reply label', () => {
    const flow: FlowView = { ...makeFlow({ status: 'offer_pending' }), nodes: [
      makeNode({ stage: 'offer', business_status: 'pending', business_result: '草稿，待发送' }),
    ] };
    expect(currentLabel(flow)).toBe('Offer待发送');
  });

  it('does not reopen scoring for a cancelled interview whose old cancellation time is missing', () => {
    const flow: FlowView = { ...makeFlow({ status: 'pending_interview', interviews: [
      { id: 'cancelled', round: 1, status: 'cancelled', result: 'pending', scheduled_at: '2026-11-02T10:00:00Z',
        ended_at: null, cancelled_at: null },
    ] }), nodes: [makeNode({ stage: 'interview', label: '第1轮面试', business_status: 'terminated' })] };
    expect(stepBusinessHref(flow, flowSteps(flow).find(s => s.stage === 'interview')!)).toMatch(/^\/interviews\?/);
    expect(nextTask(flow).label).toBe('待安排面试');
  });

  it('shows completed recommended department reviews before a terminal rejection even without completion times', () => {
    const flow: FlowView = { ...makeFlow({ status: 'rejected', previous_status: 'pending_dept_review', department_required: true }), nodes: [
      makeNode({ business_status: 'completed', status: 'unknown', complete: false }),
      makeNode({ id: 'department', key: 'department', stage: 'department', label: '部门评审',
        business_status: 'completed', business_result: '推荐', status: 'unknown', complete: false }),
    ] };
    const step = flowSteps(flow).find(s => s.stage === 'department')!;
    expect(step.state).toBe('completed');
    expect(step.result).toBe('推荐');
    expect(flowSteps(flow).some(s => s.stage === 'interview')).toBe(false);
    expect(nextTask(flow).label).toContain('流程已结束');
    expect(nodeMatches(flow.nodes[1], { problem: 'completed', search: '', mine: false })).toBe(true);
    expect(nodeMatches(flow.nodes[1], { problem: 'attention', search: '', mine: false })).toBe(false);
  });

  it('does not turn a stopped incomplete department review into a completed recommendation', () => {
    const flow: FlowView = { ...makeFlow({ status: 'rejected', department_required: true }), nodes: [
      makeNode({ id: 'department', stage: 'department', business_status: 'terminated', status: 'unknown', complete: false }),
    ] };
    expect(flowSteps(flow).find(s => s.stage === 'department')?.state).toBe('terminated');
  });

  it('keeps expired unanswered offers pending even if an old deadline closed the timing window', () => {
    const flow: FlowView = { ...makeFlow({ status: 'offer_pending' }), nodes: [
      makeNode({ id: 'offer', stage: 'offer', business_status: 'pending', business_result: '已到期，待处理', complete: true }),
    ] };
    expect(flowSteps(flow).find(s => s.stage === 'offer')?.state).toBe('pending');
    expect(flowSteps(flow).find(s => s.stage === 'offer')?.result).toBe('已到期，待处理');
  });

  it('moves passed interviews to the Offer stage while retaining the outstanding send deadline', () => {
    const flow: FlowView = { ...makeFlow({ status: 'interview_passed' }), nodes: [
      makeNode({ id: 'interview', stage: 'interview', label: '第1轮面试', business_status: 'completed', business_result: '通过',
        fields: [{ label: '及时发送Offer', valid: false, due_at: '2026-11-03T00:00:00Z' }] }),
    ] };
    expect(currentStage(flow)).toBe('offer');
    expect(flowSteps(flow).find(s => s.stage === 'interview')?.state).toBe('completed');
    expect(nextTask(flow).label).toBe('及时发送Offer');
  });

  it('ignores observed completions without timestamps when choosing the next business task', () => {
    const flow: FlowView = { ...makeFlow({ status: 'pending_hr_decision' }), nodes: [
      makeNode({ business_status: 'completed', fields: [{ label: '部门评审已完成', valid: false,
        business_completed: true, due_at: '2026-11-03T00:00:00Z' }] }),
    ] };
    expect(nextTask(flow).label).toBe('部门意见已提交，待HR决策');
  });

  it('groups current stages once per candidate and excludes past positions', () => {
    const old = makeFlow({ id: 'old', binding_id: 'old-binding', position_id: 'old-position', is_current: false, started_at: '2026-10-01T00:00:00Z' });
    const result = groupCandidates(report([
      makeNode(), makeNode({ id: 'interview', key: 'interview:i', stage: 'interview', label: '第1轮面试' }),
      makeNode({ id: 'old-node', flow_id: 'old', binding_id: 'old-binding', position_id: 'old-position' }),
      makeNode({ id: 'other', flow_id: 'other', binding_id: 'other', resume_id: 'another-person' }),
    ], [makeFlow(), old, makeFlow({ id: 'other', binding_id: 'other', resume_id: 'another-person' })]));
    expect(result).toHaveLength(2);
    expect(result[0].flows).toHaveLength(1);
    expect(result[0].current.id).toBe('flow');
    expect(result[0].current.nodes).toHaveLength(2);
  });

  it('filters by real current stage while a problem match retains the whole flow', () => {
    const nodes = [makeNode({ status: 'late', overdue: true, complete: false }),
      makeNode({ id: 'interview', key: 'interview:i', stage: 'interview', label: '第1轮面试' })];
    const [candidate] = groupCandidates(report(nodes, [makeFlow({ status: 'offer_pending' })]));
    const filters = { problem: 'overdue', search: '', mine: false };
    expect(matchingFlows(candidate, { ...filters, stage: 'screening' })).toHaveLength(0);
    const matches = matchingFlows(candidate, { ...filters, stage: 'offer' });
    expect(matches).toHaveLength(1);
    expect(matches[0].nodes).toHaveLength(2);
    expect(flowSteps(matches[0]).some(s => s.stage === 'interview')).toBe(true);
  });

  it('includes a scheduled second interview even before it has a quality result, and skips optional review', () => {
    const flow: FlowView = { ...makeFlow({ interviews: [
      { id: 'i1', round: 1, status: 'completed', result: 'next_round', scheduled_at: null, ended_at: '2026-11-01T10:00:00Z', cancelled_at: null },
      { id: 'i2', round: 2, status: 'scheduled', result: null, scheduled_at: '2026-11-05T10:00:00Z', ended_at: null, cancelled_at: null },
    ] }), nodes: [makeNode(), makeNode({ id: 'interview', key: 'interview:i1', stage: 'interview', label: '第1轮面试' })] };
    const steps = flowSteps(flow);
    expect(steps.some(s => s.stage === 'department')).toBe(false);
    expect(steps.find(s => s.id === 'interview:2')).toMatchObject({ current: true, reached: true, state: 'pending' });
    expect(stepBusinessHref(flow, steps.find(s => s.id === 'interview:2')!)).toBe('/interviews/i2/score');
    expect(steps.find(s => s.stage === 'offer')).toMatchObject({ reached: false, state: 'future' });
  });

  it('opens the completed round result and preselects the candidate for an unarranged next round', () => {
    const flow: FlowView = { ...makeFlow({ status: 'pending_next_interview', interviews: [
      { id: 'i1', round: 1, status: 'completed', result: 'next_round', scheduled_at: null, ended_at: '2026-11-01T10:00:00Z', cancelled_at: null },
    ] }), nodes: [] };
    const steps = flowSteps(flow);
    expect(stepBusinessHref(flow, steps.find(s => s.id === 'interview:1')!)).toBe('/interviews/i1/result');
    expect(stepBusinessHref(flow, steps.find(s => s.id === 'interview:2')!)).toBe('/interviews?candidate=resume&position=position&action=schedule');
    expect(stepBusinessHref({ ...flow, is_current: false }, steps.find(s => s.id === 'interview:2')!)).not.toContain('action=');
    expect(stepBusinessHref(flow, steps.find(s => s.stage === 'offer')!)).toBe('/offers?position_id=position&resume_id=resume');
  });

  it('ends a valid screening rejection at screening rather than inventing later unfinished stages', () => {
    const flow = { ...makeFlow({ status: 'rejected', previous_status: 'pending_review' }), nodes: [makeNode()] };
    expect(flowSteps(flow).map(s => s.stage)).toEqual(['screening']);
    expect(flowSteps(flow)[0].state).toBe('complete');
  });

  it('keeps a former deadline failure when the current candidate is paused', () => {
    const flow = { ...makeFlow({ status: 'waitlist', previous_status: 'pending_interview' }),
      nodes: [makeNode({ id: 'interview', key: 'interview:i', stage: 'interview', label: '第1轮面试',
        status: 'missing', complete: false, overdue: true, paused: true })] };
    expect(currentStage(flow)).toBe('interview');
    expect(flowSteps(flow).find(s => s.stage === 'interview')?.state).toBe('missing');
  });

  it('attaches cancellation to its interview round and never creates an extra candidate or process step', () => {
    const i = { id: 'i2', round: 2, status: 'cancelled', result: null, scheduled_at: null, ended_at: null, cancelled_at: '2026-11-02T10:00:00Z' };
    const flow: FlowView = { ...makeFlow({ interviews: [i] }), nodes: [
      makeNode(), makeNode({ id: 'cancel', key: 'cancel:i2', stage: 'exception', label: '第2轮面试取消处理' }),
    ] };
    const steps = flowSteps(flow);
    expect(steps.find(s => s.id === 'interview:2')?.exceptions).toHaveLength(1);
    expect(steps.some(s => s.stage === 'exception')).toBe(false);
  });

  it('keeps a cancelled second interview on round two instead of inventing a third round', () => {
    const flow: FlowView = { ...makeFlow({ status: 'pending_next_interview', interviews: [
      { id: 'i1', round: 1, status: 'completed', result: 'next_round', scheduled_at: null, ended_at: '2026-11-01T10:00:00Z', cancelled_at: null },
      { id: 'i2', round: 2, status: 'cancelled', result: null, scheduled_at: null, ended_at: null, cancelled_at: '2026-11-02T10:00:00Z' },
    ] }), nodes: [makeNode()] };
    const steps = flowSteps(flow);
    expect(steps.find(s => s.id === 'interview:2')?.current).toBe(true);
    expect(steps.some(s => s.id === 'interview:3')).toBe(false);
  });

  it('hides earlier flows even when they ended before any scored work', () => {
    const old = makeFlow({ id: 'empty-history', is_current: false, ended_at: '2026-10-25T00:00:00Z',
      end_reason: 'transfer', status: 'pending_review', started_at: '2026-10-20T00:00:00Z' });
    const [candidate] = groupCandidates(report([makeNode()], [makeFlow(), old]));
    expect(candidate.flows).toHaveLength(1);
    expect(candidate.flows.some(f => f.id === old.id)).toBe(false);
    expect(candidate.current.id).toBe('flow');
  });

  it('filters by the current HR while retaining the stages recorded under a former HR', () => {
    const [candidate] = groupCandidates(report([
      makeNode({ owner_id: 'former', owner_name: '原HR', current_owner_id: 'current', current_owner_name: '现任HR' }),
    ], [makeFlow({ owner_id: 'current', owner_name: '现任HR' })]));
    const filters = { problem: 'all', search: '', mine: false };
    expect(matchingFlows(candidate, { ...filters, owner: 'former' })).toHaveLength(0);
    expect(matchingFlows(candidate, { ...filters, owner: 'current' })).toHaveLength(1);
    expect(matchingFlows(candidate, { ...filters, search: '原HR' })).toHaveLength(0);
    expect(matchingFlows(candidate, { ...filters, search: '现任HR' })).toHaveLength(1);
  });
});
