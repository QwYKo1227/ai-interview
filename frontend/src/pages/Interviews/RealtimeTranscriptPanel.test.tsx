import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RealtimeTranscriptPanel from './RealtimeTranscriptPanel';

afterEach(cleanup);

describe('RealtimeTranscriptPanel', () => {
  it('keeps long finalized text readable instead of truncating it', () => {
    const longText = '这是一段很长的实时转写内容，面试官需要完整阅读，不能再以省略号截断。'.repeat(5);
    render(
      <RealtimeTranscriptPanel
        active
        status="connected"
        segments={[{ id: 'segment-1', speaker: 'speaker_2', text: longText }]}
        partial="正在识别的下一句话"
        expanded={false}
        onExpandedChange={vi.fn()}
      />,
    );

    expect(screen.getByText(longText)).toBeInTheDocument();
    expect(screen.getByText('说话人 3')).toBeInTheDocument();
    expect(screen.getByText('正在识别的下一句话')).toBeInTheDocument();
  });

  it('collapses to the latest line without losing the transcript history', () => {
    render(
      <RealtimeTranscriptPanel
        active
        status="connected"
        segments={[{ id: 'segment-1', speaker: 'speaker_0', text: '已经确认的内容' }]}
        partial="最新草稿"
        expanded={false}
        onExpandedChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '折叠实时字幕' }));
    expect(screen.getByText('最新草稿')).toBeInTheDocument();
    expect(screen.queryByText('已经确认的内容')).not.toBeInTheDocument();
  });
});
