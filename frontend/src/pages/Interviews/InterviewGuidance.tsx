import { Card, Tag, Typography } from 'antd';
import { BulbOutlined, FileSearchOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const { Text } = Typography;

type Props = {
  resume?: {
    ai_review?: string | null;
    hr_review?: string | null;
    match_score?: number | null;
  };
  question?: {
    resume_association?: string;
    follow_up?: string | string[];
  };
};

// Reuse the recommendation in the existing screening report as a prompt for the interviewer.
const getReviewSuggestion = (review: string) => {
  const sections = review.split(/(?=^#{1,6}\s)/m);
  return sections.filter(section => /^#{1,6}\s[^\n]*(综合建议|面试建议|面试重点|面试方向)/.test(section))
    .map(section => section.replace(/^#{1,6}[^\n]*\n?/, '').trim())
    .filter(Boolean).join('\n\n');
};

export default function InterviewGuidance({ resume, question }: Props) {
  const suggestion = getReviewSuggestion(resume?.ai_review || '');
  const followUps = (Array.isArray(question?.follow_up) ? question.follow_up : [question?.follow_up])
    .filter((item): item is string => typeof item === 'string' && Boolean(item.trim()));

  return (
    <div className="interview-guidance">
      <Card
        size="small"
        className="interview-guidance-card"
        title={<span><FileSearchOutlined /> 候选人简历评估</span>}
        extra={resume?.match_score != null && <Tag color="blue">岗位匹配 {resume.match_score} 分</Tag>}
      >
        {resume?.ai_review ? (
          <div className="interview-review-markdown interview-resume-review" tabIndex={0} role="region" aria-label="简历评估内容">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{resume.ai_review}</ReactMarkdown>
          </div>
        ) : <Text type="secondary">暂无简历评估，可结合左侧简历核实岗位相关经历。</Text>}
      </Card>

      <Card
        size="small"
        className="interview-guidance-card interview-focus-card"
        title={<span><BulbOutlined /> 面试分析建议</span>}
        extra={<Tag color="gold">重点提醒</Tag>}
      >
        {suggestion && (
          <div className="interview-focus-section">
            <Text strong>简历初审建议</Text>
            <div className="interview-review-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{suggestion}</ReactMarkdown>
            </div>
          </div>
        )}
        {resume?.hr_review && (
          <div className="interview-focus-section">
            <Text strong>HR 评语</Text>
            <div className="interview-focus-text">{resume.hr_review}</div>
          </div>
        )}
        {question?.resume_association && (
          <div className="interview-focus-section">
            <Text strong>本题核实重点</Text>
            <div className="interview-focus-text">{question.resume_association}</div>
          </div>
        )}
        {followUps.length > 0 && (
          <div className="interview-focus-section">
            <Text strong>本题追问方向</Text>
            <ul className="interview-follow-ups">
              {followUps.map((item, index) => <li key={index}>{item}</li>)}
            </ul>
          </div>
        )}
        {!suggestion && !resume?.hr_review && !question?.resume_association && followUps.length === 0 && (
          <Text type="secondary">围绕岗位要求与简历中的待核实经历提问，重点确认本人贡献、关键决策和实际结果。</Text>
        )}
        <div className="interview-focus-hint">结合现场回答调整追问，优先核实简历中的不足与证据缺口。</div>
      </Card>
    </div>
  );
}
