import { describe, expect, it } from 'vitest';
import { currentStage, flowSteps, groupCandidates, matchingFlows } from './candidate-flow';
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
  it('groups all stages and past positions once per candidate, without merging different same-name candidates', () => {
    const old = makeFlow({ id: 'old', binding_id: 'old-binding', position_id: 'old-position', is_current: false, started_at: '2026-10-01T00:00:00Z' });
    const result = groupCandidates(report([
      makeNode(), makeNode({ id: 'interview', key: 'interview:i', stage: 'interview', label: '第1轮面试' }),
      makeNode({ id: 'old-node', flow_id: 'old', binding_id: 'old-binding', position_id: 'old-position' }),
      makeNode({ id: 'other', flow_id: 'other', binding_id: 'other', resume_id: 'another-person' }),
    ], [makeFlow(), old, makeFlow({ id: 'other', binding_id: 'other', resume_id: 'another-person' })]));
    expect(result).toHaveLength(2);
    expect(result[0].flows).toHaveLength(2);
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

  it('keeps an earlier position that ended before any scored work and makes it selectable under the same candidate', () => {
    const old = makeFlow({ id: 'empty-history', is_current: false, ended_at: '2026-10-25T00:00:00Z',
      end_reason: 'transfer', status: 'pending_review', started_at: '2026-10-20T00:00:00Z' });
    const [candidate] = groupCandidates(report([makeNode()], [makeFlow(), old]));
    expect(candidate.flows).toHaveLength(2);
    const history = candidate.flows.find(f => f.id === old.id)!;
    expect(history.nodes).toHaveLength(0);
    expect(flowSteps(history).map(s => s.stage)).toEqual(['screening']);
    expect(candidate.current.id).toBe('flow');
  });
});
