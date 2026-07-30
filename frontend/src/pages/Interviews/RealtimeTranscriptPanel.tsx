import React, { useEffect, useRef, useState } from 'react';
import { Button, Tag, Typography } from 'antd';
import {
  AudioOutlined,
  CompressOutlined,
  DownOutlined,
  ExpandOutlined,
  UpOutlined,
} from '@ant-design/icons';
import type { RealtimeSegment, RealtimeStatus } from './realtimeTranscription';

const { Text } = Typography;

type Props = {
  active: boolean;
  status: RealtimeStatus;
  segments: RealtimeSegment[];
  partial: string;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
};

const statusConfig: Record<RealtimeStatus, { color: string; label: string }> = {
  connecting: { color: 'processing', label: '正在连接' },
  connected: { color: 'success', label: '实时' },
  reconnecting: { color: 'warning', label: '正在恢复' },
  unavailable: { color: 'error', label: '字幕不可用，录音继续' },
  stopped: { color: 'default', label: '已停止' },
};

const speakerLabel = (speaker?: string) => {
  const match = /(?:speaker[_\s-]*|说话人\s*)(\d+)/i.exec(speaker || '');
  if (!match) return speaker || '说话人';
  const raw = Number(match[1]);
  return `说话人 ${speaker?.toLowerCase().startsWith('speaker') ? raw + 1 : raw}`;
};

const RealtimeTranscriptPanel: React.FC<Props> = ({
  active,
  status,
  segments,
  partial,
  expanded,
  onExpandedChange,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const [height, setHeight] = useState(190);
  const [followLatest, setFollowLatest] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!followLatest || collapsed) return;
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [segments, partial, followLatest, collapsed]);

  const startResize = (event: React.PointerEvent) => {
    if (collapsed || expanded) return;
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = height;
    const move = (moveEvent: PointerEvent) => {
      setHeight(Math.max(140, Math.min(320, startHeight + startY - moveEvent.clientY)));
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
  };

  const config = statusConfig[status];
  const latestText = partial || segments[segments.length - 1]?.text || '等待语音输入…';

  return (
    <section
      aria-label="实时字幕"
      style={{
        position: 'relative',
        flex: expanded ? 1 : `0 0 ${collapsed ? 42 : height}px`,
        minHeight: collapsed ? 42 : 140,
        borderTop: '1px solid #CBD5E1',
        background: '#F8FAFC',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {!collapsed && !expanded && (
        <div
          aria-label="调整字幕面板高度"
          onPointerDown={startResize}
          style={{ position: 'absolute', inset: '-3px 0 auto', height: 7, cursor: 'ns-resize', zIndex: 2 }}
        />
      )}
      <header style={{ height: 42, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '0 10px 0 14px' }}>
        <AudioOutlined style={{ color: active ? '#DC2626' : '#64748B' }} />
        <Text strong style={{ fontSize: 13 }}>实时字幕</Text>
        <Tag color={config.color} variant="filled" style={{ margin: 0, fontSize: 11 }}>{config.label}</Tag>
        {collapsed && <Text ellipsis style={{ flex: 1, color: '#475569', fontSize: 12 }}>{latestText}</Text>}
        {!collapsed && <span style={{ flex: 1 }} />}
        {!collapsed && (
          <Button
            type="text"
            size="small"
            aria-label={expanded ? '还原字幕面板' : '展开字幕面板'}
            icon={expanded ? <CompressOutlined /> : <ExpandOutlined />}
            onClick={() => onExpandedChange(!expanded)}
          />
        )}
        <Button
          type="text"
          size="small"
          aria-label={collapsed ? '展开实时字幕' : '折叠实时字幕'}
          icon={collapsed ? <UpOutlined /> : <DownOutlined />}
          onClick={() => {
            if (!collapsed && expanded) onExpandedChange(false);
            setCollapsed(!collapsed);
          }}
        />
      </header>

      {!collapsed && (
        <div
          ref={scrollRef}
          onScroll={(event) => {
            const element = event.currentTarget;
            setFollowLatest(element.scrollHeight - element.scrollTop - element.clientHeight < 24);
          }}
          style={{ flex: 1, overflowY: 'auto', padding: '4px 14px 14px' }}
        >
          {segments.length === 0 && !partial && (
            <Text type="secondary" style={{ fontSize: 13 }}>
              {status === 'unavailable' ? '实时字幕暂不可用，完整录音仍在继续。' : '等待语音输入…'}
            </Text>
          )}
          {segments.map((segment) => (
            <div key={segment.id} style={{ display: 'grid', gridTemplateColumns: '72px 1fr', gap: 8, marginTop: 8 }}>
              <Text style={{ color: '#1D4ED8', fontSize: 12, fontWeight: 600 }}>{speakerLabel(segment.speaker)}</Text>
              <Text style={{ color: '#1E293B', fontSize: 13, lineHeight: 1.65 }}>{segment.text}</Text>
            </div>
          ))}
          {partial && (
            <div style={{ marginTop: 8, paddingLeft: 80 }}>
              <Text style={{ color: '#64748B', fontSize: 13, lineHeight: 1.65 }}>{partial}</Text>
            </div>
          )}
          {!followLatest && (
            <Button
              size="small"
              type="primary"
              onClick={() => setFollowLatest(true)}
              style={{ position: 'sticky', bottom: 0, float: 'right' }}
            >
              回到最新
            </Button>
          )}
        </div>
      )}
    </section>
  );
};

export default RealtimeTranscriptPanel;
