import type { QualityFlow, QualityNode, Report } from './types';
import { statuses } from './statuses';

export type StepState = 'complete' | 'pending' | 'missing' | 'late' | 'paused' | 'unknown' | 'future';
export interface FlowView extends QualityFlow { nodes: QualityNode[] }
export interface CandidateView { id: string; name: string; flows: FlowView[]; current: FlowView }
export interface FlowStep {
  id: string; stage: string; label: string; state: StepState; reached: boolean; current: boolean;
  nodes: QualityNode[]; exceptions: QualityNode[]; interview?: QualityFlow['interviews'][number];
}
export interface CandidateFilters {
  owner?: string; position?: string; stage?: string; problem: string; search: string; mine: boolean; userId?: string;
}
export const stepLabels: Record<StepState, string> = {
  complete: statuses.complete.label, pending: statuses.pending.label, missing: statuses.missing.label, late: statuses.late.label,
  paused: statuses.paused.label, unknown: statuses.unknown.label, future: statuses.future.label,
};
const order = ['screening', 'department', 'interview', 'offer', 'onboarding'];
const early = ['pending_screening', 'pending_review', 'auto_rejected_pending_review'];
export const isTerminal = (status: string) => ['rejected', 'interview_failed', 'offer_rejected', 'completed', 'departed'].includes(status);
export const roundLabel = (round: number) => ['一面', '二面', '三面'][round - 1] ?? `第${round}轮面试`;
const stamp = (value?: string) => value ? Date.parse(value) || 0 : 0;
const roundOf = (n: QualityNode) => Number(n.label.match(/第(\d+)轮/)?.[1] ?? 1);

export function groupCandidates(report: Report): CandidateView[] {
  const contexts = new Map((report.flows ?? []).map(flow => [flow.id, flow]));
  const candidates = new Map<string, Map<string, FlowView>>();
  for (const n of report.nodes) {
    if (!n.resume_id) continue;
    const epoch = n.key.match(/^cycle:[^/]+\//)?.[0] ?? '';
    const flowId = n.flow_id ?? `${n.binding_id}/${epoch || 'initial'}`;
    if (!candidates.has(n.resume_id)) candidates.set(n.resume_id, new Map());
    const flows = candidates.get(n.resume_id)!;
    if (!flows.has(flowId)) {
      const fallback: QualityFlow = {
        id: flowId, binding_id: n.binding_id, resume_id: n.resume_id, position_id: n.position_id,
        position_title: n.position_title, owner_id: n.executor_id, owner_name: n.owner_name,
        started_at: '', is_current: true, status: '', previous_status: null, department_required: false, interviews: [],
      };
      flows.set(flowId, { ...(contexts.get(flowId) ?? fallback), nodes: [] });
    }
    flows.get(flowId)!.nodes.push(n);
  }
  for (const flow of report.flows ?? []) {
    if (!candidates.has(flow.resume_id)) candidates.set(flow.resume_id, new Map());
    const flows = candidates.get(flow.resume_id)!;
    if (!flows.has(flow.id)) flows.set(flow.id, { ...flow, nodes: [] });
  }
  return [...candidates].map(([id, map]) => {
    const flows = [...map.values()].sort((a, b) => Number(b.is_current) - Number(a.is_current) || stamp(b.started_at) - stamp(a.started_at));
    return { id, name: flows[0].candidate_name ?? flows.flatMap(f => f.nodes)[0]?.candidate_name ?? '姓名待补齐', flows, current: flows[0] };
  }).sort((a, b) => stamp(b.current.started_at) - stamp(a.current.started_at));
}

function knownStage(flow: FlowView, status: string): string {
  if (early.includes(status)) return 'screening';
  if (['pending_dept_review', 'pending_hr_decision'].includes(status)) return 'department';
  if (status.startsWith('interview_') || ['pending_interview', 'pending_interview_result', 'pending_next_interview'].includes(status)) return 'interview';
  if (['offer_pending', 'offer_rejected'].includes(status)) return 'offer';
  if (['offer_accepted', 'onboarding', 'completed', 'departed'].includes(status)) return 'onboarding';
  return [...order].reverse().find(stage => flow.nodes.some(n => n.stage === stage)) ?? 'screening';
}

export function currentStage(flow: FlowView): string {
  return knownStage(flow, ['rejected', 'waitlist'].includes(flow.status) ? flow.previous_status ?? '' : flow.status);
}

export function currentLabel(flow: FlowView): string {
  if (flow.ended_at && !isTerminal(flow.status)) return flow.end_reason === 'restart' ? '历史流程已重新启动' : '已转岗';
  const labels: Record<string, string> = {
    pending_screening: '待初筛', pending_review: '待初筛', auto_rejected_pending_review: '待人工确认初筛',
    pending_dept_review: '等待部门评审', pending_hr_decision: '待HR决策', pending_interview: '待安排面试',
    interview_scheduled: '面试已安排', interview_in_progress: '面试进行中', pending_interview_result: '待面试最终决策',
    pending_next_interview: '待安排下一轮面试', interview_passed: '录用决策 · 待发Offer',
    interview_failed: '面试淘汰 · 已结束', rejected: '已淘汰 / 退出', waitlist: '备选暂停',
    offer_pending: '等待Offer答复', offer_accepted: '待入职', onboarding: '待入职', offer_rejected: 'Offer拒绝 · 已结束',
    completed: '已入职', departed: '已离职', historical: '历史流程',
  };
  const interview = [...flow.interviews].reverse().find(i => !i.cancelled_at);
  const prefix = interview && ['interview_scheduled', 'interview_in_progress', 'pending_interview_result'].includes(flow.status)
    ? `${roundLabel(interview.round)} · ` : '';
  return prefix + (labels[flow.status] ?? ({ screening: '初筛办理中', department: '部门评审中', interview: '面试办理中', offer: 'Offer办理中', onboarding: '入职办理中' }[currentStage(flow)] ?? '办理中'));
}

export function nodeMatches(n: QualityNode, filters: CandidateFilters): boolean {
  if (filters.owner && n.owner_id !== filters.owner) return false;
  if (filters.mine && n.executor_id !== filters.userId) return false;
  if (filters.position && n.position_id !== filters.position) return false;
  const query = filters.search.trim().toLowerCase();
  if (query && !`${n.candidate_name} ${n.position_title} ${n.label} ${n.owner_name} ${n.executor_name}`.toLowerCase().includes(query)) return false;
  switch (filters.problem) {
    case 'all': return true;
    case 'attention': return !n.complete && n.status !== 'not_applicable' && (n.eligible || n.overdue || n.historical || n.paused || n.status === 'unknown');
    case 'overdue': return n.overdue;
    case 'missing': return n.status === 'missing';
    default: return n.status === filters.problem;
  }
}

export function matchingFlows(candidate: CandidateView, filters: CandidateFilters): FlowView[] {
  if (filters.stage && filters.stage !== 'exception' && currentStage(candidate.current) !== filters.stage) return [];
  return candidate.flows.filter(flow => flow.nodes.length ? flow.nodes.some(n => nodeMatches(n, filters)
    && (filters.stage !== 'exception' || n.stage === 'exception')) :
    filters.problem === 'all' && filters.stage !== 'exception'
    && (!filters.owner || flow.owner_id === filters.owner)
    && (!filters.mine || flow.owner_id === filters.userId)
    && (!filters.position || flow.position_id === filters.position)
    && `${candidate.name} ${flow.position_title} ${flow.owner_name}`.toLowerCase().includes(filters.search.trim().toLowerCase()));
}

function stateOf(nodes: QualityNode[], reached: boolean, current: boolean): StepState {
  if (nodes.some(n => n.overdue && n.status !== 'late')) return 'missing';
  if (nodes.some(n => n.status === 'late')) return 'late';
  if (nodes.some(n => n.paused)) return 'paused';
  if (nodes.some(n => n.status === 'unknown')) return 'unknown';
  if (nodes.length && nodes.every(n => n.complete)) return 'complete';
  if (!reached) return 'future';
  return current || nodes.some(n => n.status === 'pending') ? 'pending' : 'unknown';
}

export function flowSteps(flow: FlowView): FlowStep[] {
  const stage = currentStage(flow);
  const rounds = new Set(flow.interviews.map(i => i.round));
  flow.nodes.filter(n => n.stage === 'interview').forEach(n => rounds.add(roundOf(n)));
  if (!rounds.size) rounds.add(1);
  const previousRound = [...flow.interviews].reverse().find(i => !i.cancelled_at && i.result === 'next_round')?.round
    ?? Math.max(0, ...flow.interviews.filter(i => !i.cancelled_at).map(i => i.round), ...flow.nodes.filter(n => n.stage === 'interview').map(roundOf));
  const waitingRound = previousRound + 1;
  if (flow.status === 'pending_next_interview') rounds.add(waitingRound);
  const sortedRounds = [...rounds].sort((a, b) => a - b);
  const activeRound = flow.status === 'pending_next_interview' ? waitingRound :
    ([...flow.interviews].reverse().find(i => !i.cancelled_at)?.round ?? sortedRounds.at(-1)!);
  const definitions = [
    { id: 'screening', stage: 'screening', label: '初筛' },
    ...(flow.department_required || flow.nodes.some(n => n.stage === 'department') || stage === 'department'
      ? [{ id: 'department', stage: 'department', label: '部门评审' }] : []),
    ...sortedRounds.map(round => ({ id: `interview:${round}`, stage: 'interview', label: roundLabel(round), round })),
    { id: 'offer', stage: 'offer', label: 'Offer' }, { id: 'onboarding', stage: 'onboarding', label: '入职' },
  ];
  const steps: FlowStep[] = definitions.map(def => {
    const round = 'round' in def ? def.round : null;
    const interviews = round ? flow.interviews.filter(i => i.round === round) : [];
    const nodes = flow.nodes.filter(n => n.stage === def.stage && (round === null || roundOf(n) === round));
    const current = stage === def.stage && (round === null || round === activeRound);
    const reached = nodes.length > 0 || interviews.length > 0 || order.indexOf(def.stage) < order.indexOf(stage)
      || (def.stage === stage && (round === null || round <= activeRound));
    return { ...def, current, reached, state: stateOf(nodes, reached, current), nodes, exceptions: [],
             interview: interviews.at(-1) };
  });
  for (const exception of flow.nodes.filter(n => n.stage === 'exception')) {
    const interview = flow.interviews.find(i => exception.key.includes(i.id));
    const target = interview ? steps.find(s => s.id === `interview:${interview.round}`) :
      exception.key.includes('offer') ? steps.find(s => s.stage === 'offer') :
      steps.find(s => s.current) ?? [...steps].reverse().find(s => s.reached);
    if (target) {
      target.exceptions.push(exception);
      target.state = stateOf([...target.nodes, ...target.exceptions], target.reached, target.current);
    }
  }
  if (isTerminal(flow.status) || flow.ended_at || flow.status === 'historical') {
    const end = steps.reduce((last, step, index) => step.reached ? index : last, 0);
    return steps.slice(0, end + 1);
  }
  return steps;
}

export function nextTask(flow: FlowView): { label: string; due: string | null } {
  if (flow.ended_at) return { label: '历史流程已结束，可点击节点查看记录', due: null };
  if (flow.status === 'waitlist') return { label: '备选暂停，恢复后重新计时', due: null };
  if (isTerminal(flow.status)) return { label: '流程已结束，可点击节点查看记录', due: null };
  const tasks = flow.nodes.filter(n => n.stage === currentStage(flow) || n.stage === 'exception')
    .flatMap(n => n.fields).filter(f => !f.valid && !f.completed_at && f.due_at && f.status !== '缺少可追溯时间')
    .sort((a, b) => stamp(a.due_at!) - stamp(b.due_at!));
  return tasks.length ? { label: tasks[0].label, due: tasks[0].due_at! } :
    { label: flow.interviews.some(i => i.scheduled_at && !i.ended_at && !i.cancelled_at)
        ? '面试已安排，等待举行及结果更新' : '按当前进度办理，点击节点查看依据', due: null };
}
