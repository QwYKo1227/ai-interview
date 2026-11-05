import { Button, Select, Tag, Tooltip } from 'antd';
import { CheckOutlined, ClockCircleOutlined, ExclamationOutlined, PauseOutlined, QuestionOutlined, StopOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { CSSProperties } from 'react';
import type { CandidateView, CandidateFilters, FlowStep, FlowView } from './candidate-flow';
import { currentLabel, flowSteps, isTerminal, nextTask, nodeMatches, stepLabels } from './candidate-flow';
import { statuses } from './statuses';

interface Props {
  candidate: CandidateView; flow: FlowView; filters: CandidateFilters;
  onFlowChange: (id: string) => void; onSelect: (flow: FlowView, step: FlowStep) => void;
}
export default function CandidateFlowCard({ candidate, flow, filters, onFlowChange, onSelect }: Props) {
  const steps = flowSteps(flow);
  const task = nextTask(flow);
  const highlight = filters.problem !== 'all' || filters.stage === 'exception' || !!filters.search.trim() || !!filters.owner || filters.mine || !!filters.position;
  const issueCount = flow.nodes.filter(n => n.overdue).length;
  const ended = isTerminal(flow.status) || !!flow.ended_at;
  const rejected = ['rejected', 'interview_failed'].includes(flow.status);
  const stepCount = steps.length + Number(rejected);
  const trackStyle = {
    '--columns-wide': Math.min(stepCount, 6),
    '--columns-medium': Math.min(stepCount, 4),
    '--columns-small': Math.min(stepCount, 2),
  } as CSSProperties;
  return <article className="quality-candidate" aria-label={`${candidate.name}的招聘流程`}>
    <div className="quality-candidate-heading">
      <div className="quality-candidate-identity">
        <strong>{candidate.name}</strong>
        <span className="quality-candidate-position">{flow.position_title}</span>
        {flow.owner_name && <span className="quality-candidate-owner">HR：{flow.owner_name}</span>}
      </div>
      <div className="quality-candidate-state">
        {issueCount > 0 && <Tag color="error">存在逾期</Tag>}
        {ended ? <span className={`quality-ended-status${flow.status === 'completed' ? ' is-onboarded' : ''}`}>{currentLabel(flow)}</span>
          : <span className={flow.status === 'waitlist' ? 'is-paused' : ''}>{flow.is_current ? '当前' : '历史进度'}：{currentLabel(flow)}</span>}
        {candidate.flows.length > 1 && <Select
          aria-label={`${candidate.name}的流程记录`} value={flow.id} onChange={onFlowChange}
          options={candidate.flows.map(f => ({ value: f.id,
            label: `${f.is_current ? '当前流程' : '历史流程'} · ${f.position_title}${f.started_at ? ` · ${dayjs(f.started_at).format('YYYY-MM-DD HH:mm')}` : ''}` }))}
        />}
      </div>
    </div>
    <ol className="quality-candidate-track" style={trackStyle} aria-label={`${candidate.name}的流程节点`}>
      {steps.map((step, index) => {
        const nodes = [...step.nodes, ...step.exceptions];
        const matched = highlight && nodes.some(n => nodeMatches(n, filters) && (filters.stage !== 'exception' || n.stage === 'exception'));
        const paused = flow.status === 'waitlist' && step.current || nodes.some(n => n.paused);
        const icons = {
          complete: <CheckOutlined />, pending: <ClockCircleOutlined />, missing: <ExclamationOutlined />,
          late: <ExclamationOutlined />, paused: <PauseOutlined />, unknown: <QuestionOutlined />, future: null,
        };
        const state = paused && !['missing', 'late'].includes(step.state) ? 'paused' : step.state;
        const detail = nodes.find(n => n.overdue) ?? nodes[0];
        return <li key={step.id} className={`quality-track-step is-${state}${step.reached ? ' is-reached' : ''}${steps[index + 1]?.reached || (rejected && index === steps.length - 1) ? ' is-joined' : ''}${step.current && !ended ? ' is-current' : ''}${matched ? ' is-match' : ''}`}>
          <Tooltip title={<>
            <div>{step.label} · {stepLabels[state]}</div>
            <div>{statuses[state].description}</div>
            {detail?.due_at && <div>期限：{dayjs(detail.due_at).format('YYYY-MM-DD HH:mm')}</div>}
            {step.interview?.scheduled_at && <div>面试时间：{dayjs(step.interview.scheduled_at).format('MM-DD HH:mm')}</div>}
          </>}>
            <button className="quality-track-node" disabled={!step.reached}
              aria-label={`${candidate.name} · ${step.label} · ${stepLabels[state]} · 查看依据`}
              onClick={() => onSelect(flow, step)}>
              <span className="quality-track-dot">{icons[state]}</span>
              <span className="quality-track-label">{step.label}</span>
              <span className="quality-track-caption">{stepLabels[state]}</span>
            </button>
          </Tooltip>
          {step.exceptions.length > 0 && <Button type="text" size="small" className="quality-step-exceptions"
            onClick={() => onSelect(flow, step)}>异常 {step.exceptions.length}</Button>}
          {paused && ['missing', 'late'].includes(state) && <span className="quality-step-pause"><PauseOutlined /> {statuses.paused.label}</span>}
        </li>;
      })}
      {rejected && <li className="quality-track-step is-terminated" aria-label="流程终止：淘汰">
        <div className="quality-track-node quality-track-terminal">
          <span className="quality-track-dot"><StopOutlined /></span>
          <span className="quality-track-label">淘汰</span>
        </div>
      </li>}
    </ol>
    <div className="quality-candidate-task">
      <span>{task.label}</span>
      {task.due && <time dateTime={task.due}>截止 {dayjs(task.due).format('MM-DD HH:mm')}</time>}
      {!flow.is_current && <span className="quality-history-note">正在查看历史流程</span>}
    </div>
  </article>;
}
