import type { FlowStep, FlowView } from './candidate-flow';

export function stepBusinessHref(flow: FlowView, step: FlowStep): string {
  const params = new URLSearchParams({ position_id: flow.position_id });
  if (step.stage === 'interview') {
    const interview = step.interview;
    if (interview && !interview.cancelled_at) {
      return `/interviews/${interview.id}/${interview.ended_at || interview.status === 'completed' ? 'result' : 'score'}`;
    }
    const query = new URLSearchParams({ candidate: flow.resume_id, position: flow.position_id });
    if (interview) query.set('interview_id', interview.id);
    else if (flow.is_current && ['pending_interview', 'pending_next_interview'].includes(flow.status)) query.set('action', 'schedule');
    return `/interviews?${query}`;
  }
  if (['offer', 'onboarding'].includes(step.stage)) {
    params.set('resume_id', flow.resume_id);
    if (step.stage === 'offer' && flow.is_current && flow.status === 'interview_passed') params.set('action', 'create');
    return `/offers?${params}`;
  }
  params.set('section', step.stage);
  return `/resumes/${flow.resume_id}?${params}`;
}
