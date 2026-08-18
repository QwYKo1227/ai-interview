import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Table, Button, Space, message, Modal, Form, Input, Select, Tag, Tooltip, Typography, Drawer, Descriptions, Divider, Progress, Badge, Card, Timeline } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, EyeOutlined, CopyOutlined, RobotOutlined, UndoOutlined, SearchOutlined, FilterOutlined, ArrowLeftOutlined } from '@ant-design/icons';
import request from '../../utils/request';
import JDGeneratorModal from '../../components/JDGeneratorModal';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  buildCurrentPositionListParams,
  createEmptyPositionListFilters,
  type PositionListFilters,
  reconcileDepartmentSelection,
  reconcileHiringManagerSelection,
} from './filters';
import { createLatestRequestCoordinator } from '../../utils/latestRequest';
import { useAuth } from '../../contexts/AuthContext';
import {
  getCategoryLabel,
  normalizePositionClassification,
  POSITION_CATEGORY_OPTIONS,
  PRIORITY_OPTIONS,
  getAllowedStatusOptions,
  getStatusOption,
  POSITION_STATUS_OPTIONS,
  statusChangeRequiresReason,
  type PositionStatus,
} from './options';

const { Title, Text } = Typography;

interface PositionStats {
  total_resumes: number;
  pending_screening: number;
  pending_interview: number;
  interview_completed: number;
  interview_passed: number;
  offer_pending: number;
  offer_accepted: number;
  rejected: number;
}

interface QuestionBankBrief {
  id: string;
  name: string;
  category: string;
  question_count: number;
}

interface Position {
  id: string;
  title: string;
  description: string;
  requirements: string | null;
  salary_range: string | null;
  location: string | null;
  department: string | null;
  status: PositionStatus;
  priority: number;
  category: string;
  position_type: string;
  headcount: number;
  hiring_manager_id: string | null;
  hiring_manager_name: string | null;
  created_at: string;
  updated_at: string;
  stats: PositionStats;
  linked_question_banks?: QuestionBankBrief[];
  deleted_at?: string | null;
  deleted_by_name?: string | null;
  delete_reason?: string | null;
  events?: PositionEvent[];
}

interface PositionEvent {
  id: string;
  event_type: string;
  old_value: string | null;
  new_value: string | null;
  actor_name: string | null;
  reason: string | null;
  occurred_at: string;
  event_metadata: Record<string, unknown>;
}

interface HiringManagerOption {
  id: string;
  full_name: string | null;
  email: string;
}

const priorityColors: Record<number, string> = {
  1: 'default',
  2: 'blue',
  3: 'gold',
  4: 'orange',
  5: 'red',
};

const positionTypeConfig: Record<string, { color: string; text: string }> = {
  full_time: { color: 'blue', text: '全职' },
  part_time: { color: 'cyan', text: '兼职' },
  contract: { color: 'purple', text: '合同' },
  internship: { color: 'green', text: '实习' },
};

const eventTypeLabels: Record<string, string> = {
  initial_status: '初始状态',
  status_baseline: '历史状态基线',
  status_changed: '状态变更',
  initial_owner: '初始招聘负责人',
  owner_changed: '招聘负责人变更',
  soft_deleted: '删除岗位',
  restored: '恢复岗位',
};

const displayEventValue = (event: PositionEvent, side: 'old' | 'new') => {
  const ownerName = event.event_metadata?.[`${side}_owner_name`];
  if (typeof ownerName === 'string' && ownerName) return ownerName;
  const raw = side === 'old' ? event.old_value : event.new_value;
  if (!raw) return '-';
  if (['initial_owner', 'owner_changed'].includes(event.event_type)) return '未知负责人';
  return getStatusOption(raw).label;
};

const PositionsList: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [data, setData] = useState<Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [isDrawerVisible, setIsDrawerVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingRecord, setEditingRecord] = useState<Position | null>(null);
  const [viewingRecord, setViewingRecord] = useState<Position | null>(null);
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [users, setUsers] = useState<HiringManagerOption[]>([]);
  const [hiringManagers, setHiringManagers] = useState<HiringManagerOption[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [jdModalVisible, setJdModalVisible] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const selectedStatus = Form.useWatch('status', form) as PositionStatus | undefined;
  const selectedOwnerId = Form.useWatch('hiring_manager_id', form) as string | undefined;

  const [filters, setFilters] = useState<PositionListFilters>(createEmptyPositionListFilters);
  const positionListFiltersRef = useRef(filters);
  positionListFiltersRef.current = filters;
  const [positionRequestCoordinator] = useState(createLatestRequestCoordinator);
  const [hiringManagerRequestCoordinator] = useState(createLatestRequestCoordinator);
  const [departmentRequestCoordinator] = useState(createLatestRequestCoordinator);

  const fetchPositions = useCallback(async () => {
    await positionRequestCoordinator.run<Position[]>(
      () => request.get('/positions', {
          params: buildCurrentPositionListParams(positionListFiltersRef),
      }),
      {
        onStart: () => setLoading(true),
        onSuccess: setData,
        onError: () => message.error('获取岗位列表失败'),
        onSettled: () => setLoading(false),
      },
    );
  }, [positionRequestCoordinator]);

  const fetchUsers = useCallback(async () => {
    if (!isAdmin) {
      setUsers([]);
      return;
    }
    try {
      const res = await request.get('/positions/hiring-managers');
      setUsers(res);
    } catch {
      console.error('Failed to fetch users');
    }
  }, [isAdmin]);

  const fetchHiringManagers = useCallback(async () => {
    if (!isAdmin) {
      setHiringManagers([]);
      return;
    }
    await hiringManagerRequestCoordinator.run<HiringManagerOption[]>(
      () => request.get('/positions/hiring-managers'),
      {
        onSuccess: (res) => {
          setHiringManagers(res);
          setFilters((current) => ({
            ...current,
            hiringManagerId: reconcileHiringManagerSelection(
              current.hiringManagerId,
              res,
            ),
          }));
        },
        onError: () => message.error('获取招聘负责人列表失败'),
      },
    );
  }, [hiringManagerRequestCoordinator, isAdmin]);

  const fetchDepartments = useCallback(async () => {
    await departmentRequestCoordinator.run<string[]>(
      () => request.get('/positions/departments'),
      {
        onSuccess: (res) => {
          setDepartments(res);
          setFilters((current) => ({
            ...current,
            department: reconcileDepartmentSelection(current.department, res),
          }));
        },
        onError: () => message.error('获取部门列表失败'),
      },
    );
  }, [departmentRequestCoordinator]);

  useEffect(() => {
    void fetchUsers();
    void fetchHiringManagers();
    void fetchDepartments();
  }, [fetchDepartments, fetchHiringManagers, fetchUsers]);

  useEffect(() => {
    void fetchPositions();
  }, [
    fetchPositions,
    filters.department,
    filters.hiringManagerId,
    filters.status,
    filters.title,
    filters.priority,
    filters.category,
    filters.deletedOnly,
  ]);

  const handleAdd = () => {
    setEditingId(null);
    setEditingRecord(null);
    form.resetFields();
    form.setFieldsValue({ status: 'open', priority: 3, category: 'uncategorized', position_type: 'full_time', headcount: 1 });
    setIsModalVisible(true);
  };

  const handleEdit = async (record: Position) => {
    setEditingId(record.id);
    try {
      const res = await request.get(`/positions/${record.id}`);
      setEditingRecord(res);
      form.setFieldsValue(res);
      setIsModalVisible(true);
    } catch {
      message.error('获取岗位详情失败');
    }
  };

  const handleView = async (record: Position) => {
    try {
      const res = await request.get(`/positions/${record.id}`);
      setViewingRecord(res);
      setIsDrawerVisible(true);
    } catch {
      message.error('获取岗位详情失败');
    }
  };

  const handleDelete = (id: string) => {
    let reason = '';
    Modal.confirm({
      title: '确认删除岗位',
      content: <Input.TextArea rows={3} maxLength={1000} placeholder="请填写删除原因（必填）" onChange={(event) => { reason = event.target.value; }} />,
      okText: '确认',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        if (!reason.trim()) {
          message.error('请填写删除原因');
          return Promise.reject();
        }
        try {
          await request.delete(`/positions/${id}`, { params: { reason: reason.trim() } });
          message.success('删除成功');
          void fetchPositions();
          void fetchHiringManagers();
          void fetchDepartments();
        } catch {
          message.error('删除失败');
        }
      },
    });
  };

  const handleBatchStatus = (targetStatus: PositionStatus) => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的岗位');
      return;
    }
    const target = getStatusOption(targetStatus);
    let reason = '';
    const reasonRequired = ['paused', 'cancelled'].includes(targetStatus);
    Modal.confirm({
      title: `确认批量变更为“${target.label}”`,
      content: <div><div style={{ marginBottom: 12 }}>将统一变更选中的 {selectedRowKeys.length} 个岗位。</div><Input.TextArea rows={3} maxLength={1000} placeholder={`变更原因${reasonRequired ? '（必填）' : '（选填）'}`} onChange={(event) => { reason = event.target.value; }} /></div>,
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        if (reasonRequired && !reason.trim()) {
          message.error('请填写状态变更原因');
          return Promise.reject();
        }
        try {
          await request.post('/positions/batch-status', {
            position_ids: selectedRowKeys,
            status: targetStatus,
            reason: reason.trim() || undefined,
          });
          message.success(`已批量变更为“${target.label}”`);
          setSelectedRowKeys([]);
          fetchPositions();
        } catch {
          message.error('操作失败');
        }
      },
    });
  };

  const handleRestore = (id: string) => {
    let reason = '';
    Modal.confirm({
      title: '恢复岗位为待发布',
      content: <Input.TextArea rows={3} maxLength={1000} placeholder="请填写恢复原因（必填）" onChange={(event) => { reason = event.target.value; }} />,
      onOk: async () => {
        if (!reason.trim()) {
          message.error('请填写恢复原因');
          return Promise.reject();
        }
        await request.post(`/positions/${id}/restore`, { reason: reason.trim() });
        message.success('岗位已恢复为待发布');
        void fetchPositions();
      },
    });
  };

  const handleCopyLink = (id: string) => {
    const url = `${window.location.origin}/public/jobs/${id}`;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(url).then(() => {
        message.success('岗位链接已复制');
      });
    } else {
      const textArea = document.createElement('textarea');
      textArea.value = url;
      textArea.style.position = 'fixed';
      textArea.style.left = '-999999px';
      textArea.style.top = '-999999px';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      try {
        document.execCommand('copy');
        message.success('岗位链接已复制');
      } catch {
        message.error('复制失败');
      }
      document.body.removeChild(textArea);
    }
  };

  const handleOpenJDModal = async () => {
    try {
      const values = await form.validateFields(['title']);
      if (!values.title) {
        message.error('请先填写岗位名称');
        return;
      }
      setJdModalVisible(true);
    } catch {
      message.error('请先填写岗位名称');
    }
  };

  const handleJDConfirm = (description: string, requirements: string) => {
    form.setFieldsValue({
      description,
      requirements
    });
  };

  const handleOk = async () => {
    try {
      const values = normalizePositionClassification(await form.validateFields());
      setSubmitting(true);
      if (editingId) {
        await request.put(`/positions/${editingId}`, values);
        message.success('更新成功');
      } else {
        await request.post('/positions', values);
        message.success('创建成功');
      }
      setIsModalVisible(false);
      void fetchPositions();
      void fetchHiringManagers();
      void fetchDepartments();
    } catch {
      // Validation error
    } finally {
      setSubmitting(false);
    }
  };

  const renderStats = (stats: PositionStats | undefined) => {
    if (!stats) return <Text type="secondary">-</Text>;
    const total = stats.total_resumes || 0;
    if (total === 0) return <Text type="secondary">暂无简历</Text>;
    
    return (
      <Tooltip title={
        <div>
          <div>待筛选: {stats.pending_screening}</div>
          <div>待面试: {stats.pending_interview}</div>
          <div>面试完成: {stats.interview_completed}</div>
          <div>面试通过: {stats.interview_passed}</div>
          <div>Offer待定: {stats.offer_pending}</div>
          <div>已入职: {stats.offer_accepted}</div>
          <div>已淘汰: {stats.rejected}</div>
        </div>
      }>
        <Space size={4}>
          <Badge count={total} style={{ backgroundColor: '#3B82F6' }} />
          <Progress 
            percent={Math.round((stats.offer_accepted / total) * 100) || 0} 
            size="small" 
            style={{ width: 60 }}
            showInfo={false}
            strokeColor="#10B981"
          />
        </Space>
      </Tooltip>
    );
  };

  const isRecycleBin = Boolean(filters.deletedOnly);
  const activeFilterCount = [
    filters.title,
    filters.department,
    filters.hiringManagerId,
    filters.priority,
    filters.category,
    filters.status,
  ].filter(Boolean).length;

  const resetFilters = () => {
    setFilters({
      ...createEmptyPositionListFilters(),
      deletedOnly: isRecycleBin,
    });
  };

  const toggleRecycleBin = () => {
    setSelectedRowKeys([]);
    setFilters({
      ...createEmptyPositionListFilters(),
      deletedOnly: !isRecycleBin,
    });
  };

  const columns = [
    { 
      title: '岗位名称',
      dataIndex: 'title', 
      key: 'title',
      width: 220,
      render: (text: string) => <span style={{ fontWeight: 500, color: '#0F172A' }}>{text}</span>
    },
    { title: '部门', dataIndex: 'department', key: 'department', width: 120, render: (v: string) => v || '-' },
    {
      title: '岗位分类',
      dataIndex: 'category',
      key: 'category',
      width: 150,
      render: (category: string) => getCategoryLabel(category),
    },
    {
      title: '招聘人数',
      dataIndex: 'headcount',
      key: 'headcount',
      width: 100,
      render: (value: number) => `${value || 1} 人`,
    },
    {
      title: '招聘负责人',
      dataIndex: 'hiring_manager_name',
      key: 'hiring_manager_name',
      width: 180,
      render: (value: string | null) => value || '-',
    },
    { 
      title: '优先度',
      dataIndex: 'priority',
      key: 'priority',
      width: 100,
      render: (priority: number) => (
        <Tag color={priorityColors[priority] || 'default'} style={{ border: 'none' }}>
          {priority}
        </Tag>
      ),
    },
    { 
      title: '状态', 
      dataIndex: 'status', 
      key: 'status',
      width: 100,
      render: (status: string, record: Position) => {
        if (record.deleted_at) return <Tag color="default">已删除</Tag>;
        const option = getStatusOption(status);
        return <Tag color={option.color} style={{ border: 'none' }}>{option.label}</Tag>;
      },
    },
    { 
      title: '招聘进度', 
      key: 'stats',
      width: 160,
      render: (_: unknown, record: Position) => renderStats(record.stats)
    },
    { 
      title: '创建时间', 
      dataIndex: 'created_at', 
      key: 'created_at',
      width: 180,
      render: (date: string) => <span style={{ color: '#64748B' }}>{new Date(date).toLocaleDateString()}</span>
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      render: (_: unknown, record: Position) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button type="text" icon={<EyeOutlined style={{ color: '#3B82F6' }} />} onClick={() => handleView(record)} />
          </Tooltip>
          {record.status === 'published' && (
             <Tooltip title="复制链接">
                <Button type="text" icon={<CopyOutlined />} onClick={() => handleCopyLink(record.id)} />
             </Tooltip>
          )}
          {!record.deleted_at && <Tooltip title="编辑">
            <Button type="text" icon={<EditOutlined style={{ color: '#64748B' }} />} onClick={() => handleEdit(record)} />
          </Tooltip>}
          {isAdmin && !record.deleted_at && <Tooltip title="删除">
            <Button type="text" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)} />
          </Tooltip>}
          {isAdmin && record.deleted_at && <Tooltip title="恢复为待发布">
            <Button type="text" icon={<UndoOutlined />} onClick={() => handleRestore(record.id)} />
          </Tooltip>}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div className="positions-page-header">
        <div>
          <Title level={2} style={{ margin: 0, fontWeight: 700 }}>{isRecycleBin ? '岗位回收站' : '岗位管理'}</Title>
          <Text type="secondary">{isRecycleBin ? '查看已删除岗位，必要时可恢复为待发布' : '管理企业的招聘岗位信息'}</Text>
        </div>
        <Space size={12}>
          {isAdmin && <Button
            className={isRecycleBin ? undefined : 'positions-recycle-button'}
            icon={isRecycleBin ? <ArrowLeftOutlined /> : <DeleteOutlined />}
            onClick={toggleRecycleBin}
            size="large"
          >
            {isRecycleBin ? '返回岗位管理' : '岗位回收站'}
          </Button>}
          {!isRecycleBin && <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd} size="large">新增岗位</Button>}
        </Space>
      </div>
      
      <Card className="positions-filter-bar" styles={{ body: { padding: 0 } }}>
        <div className="positions-filter-heading">
          <div className="positions-filter-title">
            <span className="positions-filter-icon"><FilterOutlined /></span>
            <div>
              <Text strong>筛选岗位</Text>
              <Text type="secondary" className="positions-filter-hint">精准定位需要处理的招聘需求</Text>
            </div>
            {activeFilterCount > 0 && <Tag color="blue" bordered={false}>{activeFilterCount} 项条件</Tag>}
          </div>
          <Button type="text" onClick={resetFilters} disabled={activeFilterCount === 0}>清除筛选</Button>
        </div>
        <div className="positions-filter-grid">
          <label className="positions-filter-field positions-filter-search">
            <span>岗位名称</span>
            <Input
              placeholder="搜索岗位名称"
              prefix={<SearchOutlined />}
              allowClear
              value={filters.title}
              onChange={(event) => setFilters((current) => ({
                ...current,
                title: event.target.value,
              }))}
            />
          </label>
          <label className="positions-filter-field">
            <span>部门</span>
            <Select
              placeholder="全部部门"
              allowClear
              showSearch
              value={filters.department}
              options={departments.map((department) => ({
                value: department,
                label: department,
              }))}
              onChange={(department) => setFilters((current) => ({
                ...current,
                department,
              }))}
            />
          </label>
          {isAdmin && <label className="positions-filter-field positions-filter-owner">
            <span>招聘负责人</span>
            <Select
              placeholder="全部负责人"
              allowClear
              showSearch
              optionFilterProp="label"
              options={hiringManagers.map((manager) => ({
                value: manager.id,
                label: manager.full_name
                  ? `${manager.full_name} (${manager.email})`
                  : manager.email,
              }))}
              value={filters.hiringManagerId}
              onChange={(hiringManagerId) => setFilters((current) => ({
                ...current,
                hiringManagerId,
              }))}
            />
          </label>}
          <label className="positions-filter-field">
            <span>优先度</span>
            <Select
              placeholder="全部优先度"
              allowClear
              options={PRIORITY_OPTIONS}
              value={filters.priority}
              onChange={(priority) => setFilters((current) => ({
                ...current,
                priority,
              }))}
            />
          </label>
          <label className="positions-filter-field">
            <span>岗位分类</span>
            <Select
              placeholder="全部分类"
              allowClear
              options={POSITION_CATEGORY_OPTIONS}
              value={filters.category}
              onChange={(category) => setFilters((current) => ({
                ...current,
                category,
              }))}
            />
          </label>
          <label className="positions-filter-field">
            <span>状态</span>
            <Select
              placeholder="全部状态"
              allowClear
              value={filters.status}
              onChange={(status) => setFilters((current) => ({
                ...current,
                status,
              }))}
            >
              {POSITION_STATUS_OPTIONS.map((option) => <Select.Option key={option.value} value={option.value}>{option.label}</Select.Option>)}
            </Select>
          </label>
        </div>
      </Card>

      {!isRecycleBin && selectedRowKeys.length > 0 && <div className="positions-batch-bar" role="region" aria-label="批量操作">
        <div className="positions-batch-summary" aria-live="polite">
          <span className="positions-batch-count">{selectedRowKeys.length}</span>
          <Text strong>个岗位已选</Text>
        </div>
        <Space className="positions-batch-actions" wrap size={10}>
          <Button onClick={() => handleBatchStatus('published')} type="primary">批量发布</Button>
          <Button onClick={() => handleBatchStatus('paused')}>批量暂停</Button>
          <Button onClick={() => handleBatchStatus('closed')}>批量关闭</Button>
          <Button danger onClick={() => handleBatchStatus('cancelled')}>批量取消</Button>
          <Button className="positions-batch-clear" type="text" onClick={() => setSelectedRowKeys([])}>取消选择</Button>
        </Space>
      </div>}
      
      <Table 
        className="positions-table"
        columns={columns} 
        dataSource={data} 
        scroll={{ x: 1360 }}
        loading={loading} 
        rowKey="id" 
        pagination={{ pageSize: 10, showSizeChanger: true }}
        rowSelection={isRecycleBin ? undefined : {
          columnWidth: 64,
          selectedRowKeys,
          onChange: setSelectedRowKeys,
          getCheckboxProps: (record) => ({ disabled: Boolean(record.deleted_at) }),
        }}
      />

      <Modal
        title={editingId ? '编辑岗位' : '新增岗位'}
        open={isModalVisible}
        onOk={handleOk}
        onCancel={() => setIsModalVisible(false)}
        confirmLoading={submitting}
        width={800}
        centered
        destroyOnHidden
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 24 }}
        >
          <Form.Item
            name="title"
            label="岗位名称"
            rules={[{ required: true, message: '请输入岗位名称' }]}
          >
            <Input placeholder="例如：高级前端工程师" size="large" />
          </Form.Item>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            <Form.Item
              name="department"
              label="所属部门"
            >
              <Input placeholder="例如：研发部" size="large" />
            </Form.Item>

            <Form.Item
              name="location"
              label="工作地点"
            >
              <Input placeholder="例如：北京" size="large" />
            </Form.Item>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            <Form.Item
              name="salary_range"
              label="薪资范围"
            >
              <Input placeholder="例如：20k-30k" size="large" />
            </Form.Item>

            <Form.Item
              name="headcount"
              label="招聘人数"
            >
              <Input type="number" min={1} placeholder="1" size="large" />
            </Form.Item>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            <Form.Item
              name="position_type"
              label="岗位类型"
            >
              <Select size="large">
                <Select.Option value="full_time">全职</Select.Option>
                <Select.Option value="part_time">兼职</Select.Option>
                <Select.Option value="contract">合同</Select.Option>
                <Select.Option value="internship">实习</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item
              name="priority"
              label="优先度"
            >
              <Select size="large" allowClear options={PRIORITY_OPTIONS} placeholder="请选择优先度" />
            </Form.Item>
          </div>

          <Form.Item name="category" label="岗位分类">
            <Select size="large" allowClear options={POSITION_CATEGORY_OPTIONS} placeholder="请选择岗位分类" />
          </Form.Item>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            <Form.Item
              name="hiring_manager_id"
              hidden={!isAdmin}
              rules={isAdmin ? [{ required: true, message: '请选择招聘负责人' }] : undefined}
              label="招聘负责人"
            >
              <Select size="large" allowClear placeholder="选择招聘负责人" showSearch optionFilterProp="children">
                {users.map(user => (
                  <Select.Option key={user.id} value={user.id}>{user.full_name} ({user.email})</Select.Option>
                ))}
              </Select>
            </Form.Item>

 
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <Text strong>岗位职责</Text>
            <Button 
              type="link" 
              icon={<RobotOutlined />} 
              onClick={handleOpenJDModal}
            >
              AI 生成 JD
            </Button>
          </div>
          <Form.Item
            name="description"
            rules={[{ required: true, message: '请输入岗位职责' }]}
          >
            <Input.TextArea rows={4} placeholder="请输入详细的岗位职责描述" showCount maxLength={2000} style={{ padding: '8px 12px' }} />
          </Form.Item>

          <Form.Item
            name="requirements"
            label="任职要求"
          >
            <Input.TextArea rows={4} placeholder="请输入任职资格要求" showCount maxLength={2000} style={{ padding: '8px 12px' }} />
          </Form.Item>

          <Form.Item
            name="status"
            label="状态"
          >
            <Select size="large" options={getAllowedStatusOptions(editingRecord?.status, isAdmin)} />
          </Form.Item>
          {editingRecord && selectedStatus !== editingRecord.status && <Form.Item
            name="status_change_reason"
            label="状态变更原因"
            rules={[{ required: statusChangeRequiresReason(editingRecord.status, selectedStatus), message: '请填写状态变更原因' }]}
          >
            <Input.TextArea rows={3} maxLength={1000} placeholder="请说明本次状态变更原因" />
          </Form.Item>}
          {editingRecord && isAdmin && selectedOwnerId !== editingRecord.hiring_manager_id && <Form.Item
            name="owner_change_reason"
            label="招聘负责人变更原因"
            rules={[{ required: true, message: '请填写招聘负责人变更原因' }]}
          >
            <Input.TextArea rows={3} maxLength={1000} placeholder="请说明本次负责人变更原因" />
          </Form.Item>}
        </Form>
      </Modal>

      <JDGeneratorModal
        visible={jdModalVisible}
        onCancel={() => setJdModalVisible(false)}
        onConfirm={handleJDConfirm}
        title={form.getFieldValue('title') || ''}
        department={form.getFieldValue('department')}
        location={form.getFieldValue('location')}
        salary_range={form.getFieldValue('salary_range')}
      />

      <Drawer
        title="岗位详情"
        size={800}
        onClose={() => setIsDrawerVisible(false)}
        open={isDrawerVisible}
        extra={
          <Space>
            {!viewingRecord?.deleted_at && <Button onClick={() => {
              setIsDrawerVisible(false);
              if (viewingRecord) handleEdit(viewingRecord);
            }}>编辑</Button>}
            <Button type="primary" onClick={() => setIsDrawerVisible(false)}>关闭</Button>
          </Space>
        }
      >
        {viewingRecord && (
          <div>
            <div style={{ marginBottom: 24 }}>
              <Title level={3} style={{ margin: 0 }}>{viewingRecord.title}</Title>
              <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                <Tag color={getStatusOption(viewingRecord.status).color} style={{ border: 'none' }}>
                  {getStatusOption(viewingRecord.status).label}
                </Tag>
                {viewingRecord.deleted_at && <Tag>已删除</Tag>}
                <Tag color={priorityColors[viewingRecord.priority] || 'default'} style={{ border: 'none' }}>
                  优先度 {viewingRecord.priority}
                </Tag>
                <Tag color={positionTypeConfig[viewingRecord.position_type]?.color || 'default'} style={{ border: 'none' }}>
                  {positionTypeConfig[viewingRecord.position_type]?.text || viewingRecord.position_type}
                </Tag>
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  创建于 {new Date(viewingRecord.created_at).toLocaleDateString()}
                </Text>
              </div>
            </div>

            <Descriptions column={2} size="middle" labelStyle={{ color: '#64748B' }} contentStyle={{ fontWeight: 500, color: '#0F172A' }}>
              <Descriptions.Item label="所属部门">{viewingRecord.department || '-'}</Descriptions.Item>
              <Descriptions.Item label="工作地点">{viewingRecord.location || '-'}</Descriptions.Item>
              <Descriptions.Item label="薪资范围">{viewingRecord.salary_range || '-'}</Descriptions.Item>
              <Descriptions.Item label="招聘人数">{viewingRecord.headcount || 1} 人</Descriptions.Item>
              <Descriptions.Item label="招聘负责人">{viewingRecord.hiring_manager_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="岗位分类">{getCategoryLabel(viewingRecord.category)}</Descriptions.Item>
            </Descriptions>

            {viewingRecord.deleted_at && <>
              <Divider style={{ margin: '24px 0' }} />
              <Descriptions column={1} size="small" title="删除信息">
                <Descriptions.Item label="删除时间">{new Date(viewingRecord.deleted_at).toLocaleString()}</Descriptions.Item>
                <Descriptions.Item label="删除人">{viewingRecord.deleted_by_name || '-'}</Descriptions.Item>
                <Descriptions.Item label="删除原因">{viewingRecord.delete_reason || '-'}</Descriptions.Item>
              </Descriptions>
            </>}

            <Divider style={{ margin: '24px 0' }} />

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ marginBottom: 16 }}>岗位变更记录</Title>
              {viewingRecord.events?.length ? <Timeline items={viewingRecord.events.map((event) => ({
                children: <div>
                  <div><Text strong>{eventTypeLabels[event.event_type] || event.event_type}</Text><Text type="secondary" style={{ marginLeft: 12 }}>{new Date(event.occurred_at).toLocaleString()}</Text></div>
                  {(event.old_value || event.new_value) && <div style={{ marginTop: 4, color: '#475569' }}>{displayEventValue(event, 'old')} → {displayEventValue(event, 'new')}</div>}
                  <div style={{ marginTop: 4, color: '#64748B' }}>操作人：{event.actor_name || '历史数据'}{event.reason ? `；原因：${event.reason}` : ''}</div>
                </div>,
              }))} /> : <Text type="secondary">暂无变更记录</Text>}
            </div>

            <Divider style={{ margin: '24px 0' }} />

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ marginBottom: 12 }}>招聘进度</Title>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                <div style={{ background: '#F8FAFC', padding: '12px 16px', borderRadius: 8 }}>
                  <Text type="secondary">总简历</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#3B82F6' }}>{viewingRecord.stats?.total_resumes || 0}</div>
                </div>
                <div style={{ background: '#F8FAFC', padding: '12px 16px', borderRadius: 8 }}>
                  <Text type="secondary">待筛选</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#F59E0B' }}>{viewingRecord.stats?.pending_screening || 0}</div>
                </div>
                <div style={{ background: '#F8FAFC', padding: '12px 16px', borderRadius: 8 }}>
                  <Text type="secondary">待面试</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#8B5CF6' }}>{viewingRecord.stats?.pending_interview || 0}</div>
                </div>
                <div style={{ background: '#F8FAFC', padding: '12px 16px', borderRadius: 8 }}>
                  <Text type="secondary">面试完成</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#0EA5E9' }}>{viewingRecord.stats?.interview_completed || 0}</div>
                </div>
                <div style={{ background: '#F8FAFC', padding: '12px 16px', borderRadius: 8 }}>
                  <Text type="secondary">面试通过</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#14B8A6' }}>{viewingRecord.stats?.interview_passed || 0}</div>
                </div>
                <div style={{ background: '#F8FAFC', padding: '12px 16px', borderRadius: 8 }}>
                  <Text type="secondary">Offer待定</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#6366F1' }}>{viewingRecord.stats?.offer_pending || 0}</div>
                </div>
                <div style={{ background: '#F8FAFC', padding: '12px 16px', borderRadius: 8 }}>
                  <Text type="secondary">已入职</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#10B981' }}>{viewingRecord.stats?.offer_accepted || 0}</div>
                </div>
                <div style={{ background: '#F8FAFC', padding: '12px 16px', borderRadius: 8 }}>
                  <Text type="secondary">已淘汰</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#EF4444' }}>{viewingRecord.stats?.rejected || 0}</div>
                </div>
              </div>
            </div>

            <Divider style={{ margin: '24px 0' }} />

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ marginBottom: 12 }}>岗位职责</Title>
              <div style={{ 
                background: '#F8FAFC', 
                padding: '16px', 
                borderRadius: '8px', 
                color: '#334155',
                lineHeight: 1.8
              }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {viewingRecord.description || '暂无描述'}
                </ReactMarkdown>
              </div>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ marginBottom: 12 }}>任职要求</Title>
              <div style={{ 
                background: '#F8FAFC', 
                padding: '16px', 
                borderRadius: '8px', 
                color: '#334155',
                lineHeight: 1.8
              }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {viewingRecord.requirements || '暂无要求'}
                </ReactMarkdown>
              </div>
            </div>

            <Divider style={{ margin: '24px 0' }} />

            <div style={{ marginBottom: 24 }}>
              <Title level={5} style={{ marginBottom: 12 }}>关联题库</Title>
              {viewingRecord.linked_question_banks && viewingRecord.linked_question_banks.length > 0 ? (
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  {viewingRecord.linked_question_banks.map((bank: QuestionBankBrief) => (
                    <div 
                      key={bank.id}
                      style={{ 
                        background: '#F8FAFC', 
                        padding: '12px 16px', 
                        borderRadius: 8,
                        border: '1px solid #E2E8F0',
                        minWidth: 200
                      }}
                    >
                      <div style={{ fontWeight: 500, color: '#0F172A' }}>{bank.name}</div>
                      <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                        <Tag color="blue" style={{ border: 'none', margin: 0 }}>{bank.category}</Tag>
                        <Text type="secondary" style={{ fontSize: 12 }}>{bank.question_count} 道题</Text>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ 
                  background: '#F8FAFC', 
                  padding: '16px', 
                  borderRadius: '8px', 
                  color: '#64748B',
                  textAlign: 'center'
                }}>
                  暂无关联题库，可在题库管理中关联到此岗位
                </div>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
};

export default PositionsList;
