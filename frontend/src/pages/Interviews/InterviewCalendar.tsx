import React, { useMemo, useRef, useState } from 'react';
import FullCalendar, { type CalendarRef, type MoreLinkHandler } from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/react/daygrid';
import timeGridPlugin from '@fullcalendar/react/timegrid';
import interactionPlugin from '@fullcalendar/react/interaction';
import classicThemePlugin from '@fullcalendar/react/themes/classic';
import zhCnLocale from '@fullcalendar/react/locales/zh-cn';
import '@fullcalendar/react/skeleton.css';
import '@fullcalendar/react/themes/classic/theme.css';
import { Button, Descriptions, Modal, Popover, Segmented, Space, Tag, Typography } from 'antd';
import { CalendarOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons';
import { getInterviewEnd, toBeijingTime } from './interviewSchedule';
import './InterviewCalendar.css';

const { Text } = Typography;

const getInterviewProgress = (record: any) => {
  if (record.lifecycle_state === 'cancelled' || record.status === 'cancelled') return 'cancelled';
  if (record.final_decision_at) return 'decided';
  if (record.lifecycle_state === 'ended') return 'pending_decision';
  if (record.lifecycle_state === 'ending') return 'ending';
  return record.lifecycle_state || record.status;
};

type InterviewCalendarProps = {
  interviews: any[];
  loading: boolean;
  interviewerNameMap: Record<string, string>;
  onRangeChange: (start: Date, end: Date) => void;
  onEmptyDoubleClick: (date: Date, allDay: boolean) => void;
  renderActions: (record: any) => React.ReactNode;
};

const PROGRESS_META: Record<string, { label: string }> = {
  scheduled: { label: '待面试' },
  in_progress: { label: '面试中' },
  ending: { label: '正在结束' },
  pending_decision: { label: '待确认结果' },
  decided: { label: '已完成' },
  cancelled: { label: '已取消' },
};

export const MONTH_DAY_MAX_EVENTS = true;

export const getCalendarEventClass = (record: any) => (
  [
    'interview-calendar__event',
    `interview-event--${getInterviewProgress(record)}`,
    isCompactCalendarEvent(record) ? 'interview-calendar__event--compact' : '',
  ].filter(Boolean).join(' ')
);

export const isCompactCalendarEvent = (record: any) => {
  const start = toBeijingTime(record?.interview_time);
  const end = getInterviewEnd(record).value;
  if (!start || !end) return false;
  const durationMinutes = end.diff(start, 'minute');
  return durationMinutes > 0 && durationMinutes <= 45;
};

type MoreLinkClickInfo = Parameters<MoreLinkHandler>[0];

export const getOverflowDayRecords = (info: Pick<MoreLinkClickInfo, 'allSegs'>) => {
  const records = info.allSegs.map((segment) => segment.event.extendedProps.record).filter(Boolean);
  return Array.from(new Map(records.map((record) => [String(record.id), record])).values());
};

export const formatCalendarTitle = (
  viewType: string,
  start: Date,
  end: Date,
  fallbackTitle: string,
) => {
  if (viewType !== 'timeGridWeek') return fallbackTitle;
  const rangeStart = toBeijingTime(start);
  const rangeEnd = toBeijingTime(end)?.subtract(1, 'day');
  if (!rangeStart || !rangeEnd) return fallbackTitle;
  return `${rangeStart.format('YYYY年M月D日')} - ${rangeEnd.format('YYYY年M月D日')}`;
};

const getInterviewerNames = (record: any, nameMap: Record<string, string>) => {
  const members = Array.isArray(record?.panel_members) ? record.panel_members : [];
  return members.map((id: string) => nameMap[String(id)] || String(id)).join('、') || record?.interviewer || '-';
};

const getLocationText = (record: any) => {
  if (record?.interview_type === 'video') return record?.meeting_link || '视频面试';
  if (record?.interview_type === 'phone') return '电话面试';
  return record?.interview_location || '现场面试';
};

const getDayClassNames = (info: { dow: number; date: Date }) => [
  'interview-calendar__day',
  info.dow === 0 || info.dow === 6 ? 'interview-calendar__day--weekend' : '',
  toBeijingTime(info.date)?.isSame(toBeijingTime(new Date()), 'day') ? 'interview-calendar__day--today' : '',
].filter(Boolean).join(' ');

const EventDetails: React.FC<{
  record: any;
  interviewerNameMap: Record<string, string>;
  actions: React.ReactNode;
}> = ({ record, interviewerNameMap, actions }) => {
  const progress = getInterviewProgress(record);
  const meta = PROGRESS_META[progress] || { label: progress };
  const start = toBeijingTime(record?.interview_time);
  const { value: end, estimated } = getInterviewEnd(record);
  return (
    <div className="interview-event-popover">
      <div className="interview-event-popover__header">
        <div>
          <Text strong>{record?.resume?.candidate_name || '未知候选人'}</Text>
          <div className="interview-event-popover__position">{record?.position?.title || '未知岗位'}</div>
        </div>
        <Tag className={`interview-status-tag interview-status-tag--${progress}`}>{meta.label}</Tag>
      </div>
      <Descriptions size="small" column={1} colon={false}>
        <Descriptions.Item label="时间">
          {start?.format('YYYY-MM-DD HH:mm')}–{end?.format('HH:mm')}{estimated ? '（预计）' : ''}
        </Descriptions.Item>
        <Descriptions.Item label="面试官">{getInterviewerNames(record, interviewerNameMap)}</Descriptions.Item>
        <Descriptions.Item label="形式/地点">{getLocationText(record)}</Descriptions.Item>
      </Descriptions>
      <div className="interview-event-popover__actions">{actions}</div>
    </div>
  );
};

const InterviewCalendar: React.FC<InterviewCalendarProps> = ({
  interviews,
  loading,
  interviewerNameMap,
  onRangeChange,
  onEmptyDoubleClick,
  renderActions,
}) => {
  const savedView = localStorage.getItem('interview-calendar-view');
  const initialView = savedView === 'timeGridWeek' ? 'timeGridWeek' : 'dayGridMonth';
  const calendarRef = useRef<CalendarRef | null>(null);
  const [calendarView, setCalendarView] = useState(initialView);
  const [calendarTitle, setCalendarTitle] = useState('');
  const [overflowDay, setOverflowDay] = useState<{ date: Date; records: any[] } | null>(null);
  const events = useMemo(() => interviews
    .filter((record) => record?.interview_time)
    .map((record) => {
      const end = getInterviewEnd(record).value;
      return {
        id: String(record.id),
        title: `${record?.resume?.candidate_name || '未知候选人'} · ${record?.position?.title || '未知岗位'}`,
        start: record.interview_time,
        end: end?.toISOString(),
        extendedProps: { record },
      };
    }), [interviews]);

  return (
    <div className={`interview-calendar ${loading ? 'interview-calendar--loading' : ''}`}>
      <div className="interview-calendar__commandbar">
        <div className="interview-calendar__navigation">
          <Button
            className="interview-calendar__today-button"
            onClick={() => calendarRef.current?.getApi().today()}
          >
            今天
          </Button>
          <Space.Compact className="interview-calendar__arrow-group">
            <Button
              aria-label="上一时间范围"
              icon={<LeftOutlined />}
              onClick={() => calendarRef.current?.getApi().prev()}
            />
            <Button
              aria-label="下一时间范围"
              icon={<RightOutlined />}
              onClick={() => calendarRef.current?.getApi().next()}
            />
          </Space.Compact>
          <h3 className="interview-calendar__title">{calendarTitle}</h3>
        </div>
        <Segmented
          className="interview-calendar__view-switch"
          value={calendarView}
          options={[
            { value: 'dayGridMonth', label: '月' },
            { value: 'timeGridWeek', label: '周' },
          ]}
          onChange={(value) => calendarRef.current?.getApi().changeView(String(value))}
        />
      </div>
      <FullCalendar
        ref={calendarRef}
        plugins={[classicThemePlugin, dayGridPlugin, timeGridPlugin, interactionPlugin]}
        locale={zhCnLocale}
        timeZone="Asia/Shanghai"
        initialView={initialView}
        firstDay={1}
        headerToolbar={false}
        className="interview-calendar__root"
        viewClass={(info) => `interview-calendar__view interview-calendar__view--${info.view.type}`}
        tableClass="interview-calendar__table"
        dayHeaderClass={getDayClassNames}
        dayCellClass={getDayClassNames}
        dayLaneClass={getDayClassNames}
        slotLaneClass="interview-calendar__slot"
        nonBusinessHoursClass="interview-calendar__non-business"
        eventClass={(info) => getCalendarEventClass(info.event.extendedProps.record)}
        events={events}
        allDaySlot={false}
        editable={false}
        selectable={false}
        dayMaxEvents={MONTH_DAY_MAX_EVENTS}
        moreLinkText={(count) => `另有 ${count} 场`}
        moreLinkClass="interview-calendar__more-link"
        moreLinkClick={(info) => {
          setOverflowDay({ date: info.date, records: getOverflowDayRecords(info) });
        }}
        businessHours={{ daysOfWeek: [1, 2, 3, 4, 5], startTime: '08:30', endTime: '19:30' }}
        slotMinTime="00:00:00"
        slotMaxTime="24:00:00"
        scrollTime="08:30:00"
        slotDuration="00:15:00"
        eventTimeFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
        height={calendarView === 'timeGridWeek' ? 720 : 900}
        datesSet={(info) => {
          localStorage.setItem('interview-calendar-view', info.view.type);
          setCalendarView(info.view.type);
          setCalendarTitle(formatCalendarTitle(info.view.type, info.start, info.end, info.view.title));
          setOverflowDay(null);
          onRangeChange(info.start, info.end);
        }}
        dateClick={(info) => {
          if (info.jsEvent.detail === 2) onEmptyDoubleClick(info.date, info.allDay);
        }}
        eventContent={(info) => {
          const record = info.event.extendedProps.record;
          return (
            <Popover
              trigger="click"
              placement="rightTop"
              content={(
                <EventDetails
                  record={record}
                  interviewerNameMap={interviewerNameMap}
                  actions={renderActions(record)}
                />
              )}
            >
              <button type="button" className="interview-event-content" onDoubleClick={(event) => event.stopPropagation()}>
                <span className="interview-event-content__time">{info.timeText}</span>
                <span className="interview-event-content__title">{info.event.title}</span>
              </button>
            </Popover>
          );
        }}
        noEventsContent={() => (
          <Space direction="vertical" align="center" size={8} className="interview-calendar__empty">
            <CalendarOutlined />
            <Text type="secondary">当前范围暂无面试安排</Text>
            <Button type="link">双击空白时段可安排面试</Button>
          </Space>
        )}
      />
      <Modal
        className="interview-overflow-modal"
        title={overflowDay ? `${toBeijingTime(overflowDay.date)?.format('YYYY年M月D日')} · ${overflowDay.records.length}场面试` : ''}
        open={Boolean(overflowDay)}
        footer={null}
        width={680}
        centered
        destroyOnHidden
        onCancel={() => setOverflowDay(null)}
      >
        <div className="interview-overflow-list">
          {overflowDay?.records.map((record) => {
            const progress = getInterviewProgress(record);
            const meta = PROGRESS_META[progress] || { label: progress };
            const start = toBeijingTime(record?.interview_time);
            const { value: end, estimated } = getInterviewEnd(record);
            return (
              <div key={record.id} className={`interview-overflow-item interview-overflow-item--${progress}`}>
                <div className="interview-overflow-item__time">
                  <strong>{start?.format('HH:mm')}</strong>
                  <span>{end?.format('HH:mm')}{estimated ? ' 预计' : ''}</span>
                </div>
                <div className="interview-overflow-item__main">
                  <strong>{record?.resume?.candidate_name || '未知候选人'}</strong>
                  <span>{record?.position?.title || '未知岗位'}</span>
                </div>
                <Tag className={`interview-status-tag interview-status-tag--${progress}`}>{meta.label}</Tag>
                <div className="interview-overflow-item__actions">{renderActions(record)}</div>
              </div>
            );
          })}
        </div>
      </Modal>
    </div>
  );
};

export default InterviewCalendar;
