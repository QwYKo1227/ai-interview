import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Table, Button, Space, Tag, Modal, Form, Input, InputNumber, DatePicker,
  Select, message, Popconfirm, Badge, Tooltip, Typography, Row, Col, Statistic,
  Drawer, Descriptions, Divider, Timeline, Alert
} from 'antd';
import {
  PlusOutlined, SwapOutlined, CheckOutlined, CloseOutlined, RollbackOutlined,
  EyeOutlined, EditOutlined, DeleteOutlined, SearchOutlined, ReloadOutlined,
  FileTextOutlined, DollarOutlined, EnvironmentOutlined, ClockCircleOutlined,
  RedoOutlined, UserAddOutlined
} from '@ant-design/icons';
import request from '../../utils/request';
import dayjs from 'dayjs';
import { useAuth } from '../../contexts/AuthContext';
import { formatOfferDateTime } from './offerTime';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { Option } = Select;

interface Offer {
  id: string;
  resume_id: string;
  position_id: string;
  candidate_name: string;
  candidate_email: string;
  salary_monthly: number | null;
  salary_annual: number | null;
  salary_structure: string | null;
  position_title: string;
  department: string | null;
  report_to: string | null;
  work_location: string | null;
  work_hours: string | null;
  onboard_date: string | null;
  probation_months: number;
  benefits: string | null;
  bonus: string | null;
  special_terms: string | null;
  notes: string | null;
  valid_until: string | null;
  status: string;
  sent_at: string | null;
  accepted_at: string | null;
  actual_onboarded_at: string | null;
  rejected_at: string | null;
  rejected_reason: string | null;
  created_at: string;
  updated_at: string | null;
  hiring_manager_id: string | null;
  hiring_manager_name: string | null;
  can_decide: boolean;
  position_info: {
    id: string;
    title: string;
    department: string;
    location: string;
    salary_range: string;
  } | null;
  resume_info: {
    id: string;
    candidate_name: string;
    email: string;
    match_score: number;
  } | null;
}

interface OfferStats {
  total_offers: number;
  pending_offers: number;
  sent_offers: number;
  accepted_offers: number;
  rejected_offers: number;
  expired_offers: number;
  acceptance_rate: number;
  avg_response_days: number | null;
}

interface OfferDecisionAudit {
  id: string;
  previous_status: string;
  new_status: string;
  rejection_reason: string | null;
  rejection_detail: string | null;
  correction_reason: string | null;
  actor_name: string;
  created_at: string;
}

const rejectionReasonLabels: Record<string, string> = {
  salary: '薪资不符',
  other_offer: '接受其他 Offer',
  position_mismatch: '岗位不匹配',
  location: '地点/通勤原因',
  onboard_date: '入职时间不符',
  personal: '个人原因',
  unreachable: '无法联系',
  other: '其他',
};

const formatRejectedReason = (value: string | null) => {
  if (!value) return '-';
  const [reason, ...detail] = value.split(': ');
  const label = rejectionReasonLabels[reason] || reason;
  return detail.length > 0 ? `${label}（${detail.join(': ')}）` : label;
};

const statusConfig: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  pending: { color: 'processing', text: '待发出' },
  sent: { color: 'warning', text: 'Offer待确认' },
  accepted: { color: 'success', text: '已接受' },
  rejected: { color: 'error', text: '已拒绝' },
  expired: { color: 'default', text: '已过期' },
  withdrawn: { color: 'default', text: '已撤回' },
};

const OffersList: React.FC = () => {
  const { user } = useAuth();
  const canManageOffer = user?.role === 'admin' || user?.role === 'hr';
  const [offers, setOffers] = useState<Offer[]>([]);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 10, total: 0 });
  const [stats, setStats] = useState<OfferStats | null>(null);
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [detailDrawerVisible, setDetailDrawerVisible] = useState(false);
  const [statusModalVisible, setStatusModalVisible] = useState(false);
  const [rejectModalVisible, setRejectModalVisible] = useState(false);
  const [acceptModalVisible, setAcceptModalVisible] = useState(false);
  const [onboardingModalVisible, setOnboardingModalVisible] = useState(false);
  
  const [currentOffer, setCurrentOffer] = useState<Offer | null>(null);
  const [decisionAudits, setDecisionAudits] = useState<OfferDecisionAudit[]>([]);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [rejectForm] = Form.useForm();
  const [acceptForm] = Form.useForm();
  const [onboardingForm] = Form.useForm();

  const confirmOnboarding = async () => {
    if (!currentOffer) return;
    const values = await onboardingForm.validateFields();
    try {
      await request.post(`/offers/${currentOffer.id}/confirm-onboarding`, {
        actual_onboard_date: values.actual_onboard_date.format('YYYY-MM-DD'),
      });
      message.success('已确认候选人入职');
      setOnboardingModalVisible(false);
      onboardingForm.resetFields();
      fetchOffers();
      fetchStats();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '确认入职失败');
    }
  };

  const [positions, setPositions] = useState<any[]>([]);
  const [resumes, setResumes] = useState<any[]>([]);
  const [selectedResume, setSelectedResume] = useState<any>(null);
  const [templates, setTemplates] = useState<any[]>([]);

  const fetchOffers = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('page', pagination.current.toString());
      params.append('page_size', pagination.pageSize.toString());
      if (statusFilter) params.append('status', statusFilter);
      if (searchText) params.append('search', searchText);

      const response = await request.get(`/offers?${params.toString()}`);
      setOffers(response.items);
      setPagination(prev => ({ ...prev, total: response.total }));
    } catch (error) {
      message.error('获取Offer列表失败');
    } finally {
      setLoading(false);
    }
  }, [pagination.current, pagination.pageSize, statusFilter, searchText]);

  const fetchStats = async () => {
    try {
      const response = await request.get('/offers/stats');
      setStats(response);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  const fetchPositions = async () => {
    try {
      const response = await request.get('/positions?page=1&page_size=100');
      const positionsData = Array.isArray(response) ? response : (response.items || []);
      setPositions(positionsData);
    } catch (error) {
      console.error('Failed to fetch positions:', error);
    }
  };

  const fetchPassedResumes = async () => {
    try {
      const response = await request.get('/resumes?limit=500');
      const eligibleStatuses = ['interview_passed', 'offer_pending', 'completed'];
      const eligibleResumes = (response || []).filter((r: any) => 
        eligibleStatuses.includes(r.status)
      );
      setResumes(eligibleResumes);
    } catch (error) {
      console.error('Failed to fetch resumes:', error);
    }
  };

  const fetchTemplates = async (positionId?: string) => {
    try {
      const url = positionId 
        ? `/offer-templates?position_id=${positionId}`
        : '/offer-templates';
      const response = await request.get(url);
      setTemplates(response.items || []);
    } catch (error) {
      console.error('Failed to fetch templates:', error);
    }
  };

  const applyTemplate = (template: any) => {
    if (!template) return;
    createForm.setFieldsValue({
      salary_monthly: template.salary_monthly,
      salary_annual: template.salary_annual,
      salary_structure: template.salary_structure,
      department: template.department,
      report_to: template.report_to,
      work_location: template.work_location,
      work_hours: template.work_hours,
      probation_months: template.probation_months || 3,
      benefits: template.benefits,
      bonus: template.bonus,
      special_terms: template.special_terms,
      notes: template.notes,
    });
  };

  useEffect(() => {
    fetchOffers();
    fetchStats();
    if (canManageOffer) {
      fetchPositions();
      fetchPassedResumes();
    }
  }, [fetchOffers, canManageOffer]);

  const handleCreate = async (values: any) => {
    try {
      const data = {
        ...values,
        onboard_date: values.onboard_date?.toISOString(),
        valid_until: values.valid_until?.toISOString(),
      };
      await request.post('/offers', data);
      message.success('Offer创建成功');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchOffers();
      fetchStats();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '创建失败');
    }
  };

  const handleEdit = async (values: any) => {
    if (!currentOffer) return;
    try {
      const data = {
        ...values,
        onboard_date: values.onboard_date?.toISOString(),
        valid_until: values.valid_until?.toISOString(),
      };
      await request.put(`/offers/${currentOffer.id}`, data);
      message.success('Offer更新成功');
      setEditModalVisible(false);
      editForm.resetFields();
      fetchOffers();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '更新失败');
    }
  };

  const handleMarkPendingConfirmation = async () => {
    if (!currentOffer) return;
    try {
      const result = await request.post(`/offers/${currentOffer.id}/mark-pending-confirmation`, {});
      if (!result?.success) {
        message.error(result?.error || '确认发出失败');
        return;
      }
      message.success('Offer状态已变更为“Offer待确认”');
      setStatusModalVisible(false);
      fetchOffers();
      fetchStats();
      window.dispatchEvent(new Event('offer-pending-updated'));
    } catch (error: any) {
      message.error(error.response?.data?.detail || '状态变更失败');
    }
  };

  const handleAccept = async (values: any) => {
    if (!currentOffer) return;
    try {
      await request.post(`/offers/${currentOffer.id}/decision`, {
        decision: 'accepted',
        correction_reason: values.correction_reason,
      });
      message.success(currentOffer.status === 'rejected' ? 'Offer结果已更正为接受' : '已登记候选人接受Offer');
      setAcceptModalVisible(false);
      acceptForm.resetFields();
      fetchOffers();
      fetchStats();
      window.dispatchEvent(new Event('offer-pending-updated'));
    } catch (error: any) {
      message.error(error.response?.data?.detail || '操作失败');
    }
  };

  const handleReject = async (values: any) => {
    if (!currentOffer) return;
    try {
      await request.post(`/offers/${currentOffer.id}/decision`, {
        decision: 'rejected',
        rejection_reason: values.rejection_reason,
        rejection_detail: values.rejection_detail,
        correction_reason: values.correction_reason,
      });
      message.success(currentOffer.status === 'accepted' ? 'Offer结果已更正为拒绝' : '已登记候选人拒绝Offer');
      setRejectModalVisible(false);
      rejectForm.resetFields();
      fetchOffers();
      fetchStats();
      window.dispatchEvent(new Event('offer-pending-updated'));
    } catch (error: any) {
      message.error(error.response?.data?.detail || '操作失败');
    }
  };

  const handleWithdraw = async (offerId: string) => {
    try {
      await request.post(`/offers/${offerId}/withdraw`);
      message.success('Offer已撤回');
      fetchOffers();
      fetchStats();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '撤回失败');
    }
  };

  const handleReopen = async (offerId: string) => {
    try {
      await request.post(`/offers/${offerId}/reopen`);
      message.success('Offer已重新打开');
      fetchOffers();
      fetchStats();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '重新打开失败');
    }
  };

  const handleDelete = async (offerId: string) => {
    try {
      await request.delete(`/offers/${offerId}`);
      message.success('Offer已删除');
      fetchOffers();
      fetchStats();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '删除失败');
    }
  };

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的Offer');
      return;
    }
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 个Offer吗？此操作不可恢复。`,
      okText: '确认',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await Promise.all(selectedRowKeys.map(id => request.delete(`/offers/${id}`)));
          message.success(`成功删除 ${selectedRowKeys.length} 个Offer`);
          setSelectedRowKeys([]);
          fetchOffers();
          fetchStats();
        } catch (error) {
          message.error('批量删除失败');
        }
      },
    });
  };

  const handleBatchMarkPendingConfirmation = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要变更状态的Offer');
      return;
    }
    Modal.confirm({
      title: '批量变更Offer状态',
      content: `确定将选中的 ${selectedRowKeys.length} 个Offer变更为“Offer待确认”吗？`,
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const results = await Promise.all(
            selectedRowKeys.map(id => request.post(`/offers/${id}/mark-pending-confirmation`))
          );
          const failed = results.filter(result => !result?.success);
          if (failed.length > 0) {
            const reason = failed.find(result => result?.error)?.error;
            message.error(reason || `${failed.length} 个 Offer 状态变更失败`);
            fetchOffers();
            fetchStats();
            return;
          }
          message.success(`已将 ${selectedRowKeys.length} 个Offer标记为“Offer待确认”`);
          setSelectedRowKeys([]);
          fetchOffers();
          fetchStats();
        } catch (error) {
          message.error('批量状态变更失败');
        }
      },
    });
  };

  const openEditModal = (offer: Offer) => {
    setCurrentOffer(offer);
    editForm.setFieldsValue({
      ...offer,
      onboard_date: offer.onboard_date ? dayjs(offer.onboard_date) : null,
      valid_until: offer.valid_until ? dayjs(offer.valid_until) : null,
    });
    setEditModalVisible(true);
  };

  const openDetailDrawer = async (offer: Offer) => {
    setCurrentOffer(offer);
    setDetailDrawerVisible(true);
    try {
      const response = await request.get(`/offers/${offer.id}/decision-audits`);
      setDecisionAudits(Array.isArray(response) ? response : []);
    } catch {
      setDecisionAudits([]);
    }
  };

  const columns = [
    {
      title: '候选人',
      dataIndex: 'candidate_name',
      key: 'candidate_name',
      render: (text: string, record: Offer) => (
        <div>
          <Text strong>{text}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>{record.candidate_email}</Text>
        </div>
      ),
    },
    {
      title: '岗位',
      dataIndex: 'position_title',
      key: 'position_title',
      render: (text: string, record: Offer) => (
        <div>
          <Text>{text}</Text>
          {record.department && <><br /><Text type="secondary" style={{ fontSize: 12 }}>{record.department}</Text></>}
        </div>
      ),
    },
    {
      title: '薪资',
      key: 'salary',
      render: (_: any, record: Offer) => (
        <div>
          {record.salary_monthly && <Text>月薪 {record.salary_monthly.toLocaleString()}元</Text>}
          {record.salary_annual && <><br /><Text type="secondary">年薪 {record.salary_annual.toLocaleString()}元</Text></>}
          {!record.salary_monthly && !record.salary_annual && <Text type="secondary">未填写</Text>}
        </div>
      ),
    },
    {
      title: '入职日期',
      dataIndex: 'onboard_date',
      key: 'onboard_date',
      render: (date: string) => date ? dayjs(date).format('YYYY-MM-DD') : <Text type="secondary">待定</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string, record: Offer) => {
        if (record.actual_onboarded_at) return <Tag color="green">已入职</Tag>;
        const config = statusConfig[status] || { color: 'default', text: status };
        return <Tag color={config.color}>{config.text}</Tag>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => formatOfferDateTime(date),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Offer) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button type="text" icon={<EyeOutlined />} onClick={() => openDetailDrawer(record)} />
          </Tooltip>
          {['draft', 'pending'].includes(record.status) && (
            <>
              {canManageOffer && record.status === 'draft' && <Tooltip title="编辑">
                <Button type="text" icon={<EditOutlined />} onClick={() => openEditModal(record)} />
              </Tooltip>}
              {canManageOffer && <Tooltip title="变更为Offer待确认">
                <Button type="text" icon={<SwapOutlined />} onClick={() => {
                  setCurrentOffer(record);
                  setStatusModalVisible(true);
                }} />
              </Tooltip>}
            </>
          )}
          {['sent', 'expired'].includes(record.status) && record.can_decide && (
            <>
              <Tooltip title="接受">
                <Button type="text" style={{ color: '#52c41a' }} icon={<CheckOutlined />} onClick={() => {
                  setCurrentOffer(record);
                  acceptForm.resetFields();
                  setAcceptModalVisible(true);
                }} />
              </Tooltip>
              <Tooltip title="拒绝">
                <Button type="text" danger icon={<CloseOutlined />} onClick={() => {
                  setCurrentOffer(record);
                  rejectForm.resetFields();
                  setRejectModalVisible(true);
                }} />
              </Tooltip>
            </>
          )}
          {record.status === 'accepted' && record.can_decide && (
            <>
              {!record.actual_onboarded_at && <Tooltip title="确认实际入职">
                <Button type="text" style={{ color: '#059669' }} icon={<UserAddOutlined />} onClick={() => {
                  setCurrentOffer(record);
                  onboardingForm.setFieldsValue({ actual_onboard_date: dayjs() });
                  setOnboardingModalVisible(true);
                }} />
              </Tooltip>}
              <Tooltip title="更正为拒绝">
                <Button type="text" danger icon={<CloseOutlined />} onClick={() => {
                  setCurrentOffer(record);
                  rejectForm.resetFields();
                  setRejectModalVisible(true);
                }} />
              </Tooltip>
            </>
          )}
          {record.status === 'rejected' && record.can_decide && (
            <Tooltip title="更正为接受">
              <Button type="text" style={{ color: '#52c41a' }} icon={<CheckOutlined />} onClick={() => {
                setCurrentOffer(record);
                acceptForm.resetFields();
                setAcceptModalVisible(true);
              }} />
            </Tooltip>
          )}
          {canManageOffer && ['draft', 'pending', 'sent'].includes(record.status) && (
            <Popconfirm title="确定撤回此Offer？" onConfirm={() => handleWithdraw(record.id)}>
              <Tooltip title="撤回">
                <Button type="text" icon={<RollbackOutlined />} />
              </Tooltip>
            </Popconfirm>
          )}
          {canManageOffer && ['withdrawn'].includes(record.status) && (
            <Popconfirm title="确定重新打开此Offer？重新打开后状态将变为待发出。" onConfirm={() => handleReopen(record.id)}>
              <Tooltip title="重新打开">
                <Button type="text" icon={<RedoOutlined />} style={{ color: '#1890ff' }} />
              </Tooltip>
            </Popconfirm>
          )}
          {canManageOffer && <Popconfirm title="确定删除此Offer？此操作不可恢复。" onConfirm={() => handleDelete(record.id)}>
            <Tooltip title="删除">
              <Button type="text" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0 }}>Offer管理</Title>
        <Text type="secondary">管理候选人录用通知</Text>
      </div>

      {stats && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col xs={12} sm={6}>
            <Card>
              <Statistic title="总Offer数" value={stats.total_offers} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card>
              <Statistic title="待处理" value={stats.pending_offers + stats.sent_offers} valueStyle={{ color: '#faad14' }} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card>
              <Statistic title="已接受" value={stats.accepted_offers} valueStyle={{ color: '#52c41a' }} />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card>
              <Statistic 
                title="接受率" 
                value={stats.acceptance_rate} 
                suffix="%" 
                valueStyle={{ color: stats.acceptance_rate >= 50 ? '#52c41a' : '#ff4d4f' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      <Card>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <Space wrap>
            <Input.Search
              placeholder="搜索候选人/岗位"
              allowClear
              style={{ width: 200 }}
              onSearch={setSearchText}
              onChange={(e) => !e.target.value && setSearchText('')}
            />
            <Select
              placeholder="状态筛选"
              allowClear
              style={{ width: 120 }}
              onChange={setStatusFilter}
            >
              {Object.entries(statusConfig).map(([key, value]) => (
                <Option key={key} value={key}>{value.text}</Option>
              ))}
            </Select>
            <Button icon={<ReloadOutlined />} onClick={() => { fetchOffers(); fetchStats(); }}>刷新</Button>
            {canManageOffer && selectedRowKeys.length > 0 && (
              <>
                <span style={{ color: '#64748B', lineHeight: '32px' }}>已选 {selectedRowKeys.length} 项</span>
                <Button type="primary" onClick={handleBatchMarkPendingConfirmation}>批量标记待确认</Button>
                <Button danger onClick={handleBatchDelete}>批量删除</Button>
                <Button onClick={() => setSelectedRowKeys([])}>取消选择</Button>
              </>
            )}
          </Space>
          {canManageOffer && <Button type="primary" icon={<PlusOutlined />} onClick={() => {
            createForm.resetFields();
            setCreateModalVisible(true);
          }}>新建Offer</Button>}
        </div>

        <Table
          columns={columns}
          dataSource={offers}
          rowKey="id"
          loading={loading}
          rowSelection={canManageOffer ? {
            selectedRowKeys,
            onChange: setSelectedRowKeys,
          } : undefined}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => setPagination(prev => ({ ...prev, current: page, pageSize })),
          }}
        />
      </Card>

      <Modal
        title="新建Offer"
        open={createModalVisible}
        onCancel={() => { setCreateModalVisible(false); setSelectedResume(null); setTemplates([]); }}
        onOk={() => createForm.submit()}
        width={700}
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item name="resume_id" label="选择候选人（通过面试）" rules={[{ required: true }]}>
                <Select 
                  placeholder="选择通过面试的候选人" 
                  showSearch
                  optionFilterProp="children"
                  onChange={async (value) => {
                    const resume = resumes.find(r => r.id === value);
                    if (resume) {
                      setSelectedResume(resume);
                      const position = positions.find(p => p.id === resume.position_id);
                      createForm.setFieldsValue({
                        candidate_name: resume.candidate_name,
                        candidate_email: resume.email,
                        position_id: resume.position_id,
                        position_title: position?.title || resume.position?.title || '',
                        department: position?.department || resume.position?.department || '',
                        work_location: position?.location || resume.position?.location || '',
                      });
                      
                      await fetchTemplates(resume.position_id);
                      try {
                        const defaultTemplate = await request.get(`/offer-templates/default/${resume.position_id}`);
                        if (defaultTemplate) {
                          applyTemplate(defaultTemplate);
                          message.info('已自动填充岗位默认模板');
                        }
                      } catch (e) {
                        console.log('No default template for this position');
                      }
                    }
                  }}
                >
                  {resumes.map(r => (
                    <Option key={r.id} value={r.id}>
                      {r.candidate_name} - {r.position?.title || '未知岗位'} ({r.email})
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item label="选择Offer模板">
                <Select 
                  placeholder={templates.length > 0 ? "选择模板快速填充（已自动加载默认模板）" : "暂无模板，请先创建Offer模板"}
                  allowClear
                  showSearch
                  optionFilterProp="children"
                  onChange={(value) => {
                    const template = templates.find(t => t.id === value);
                    if (template) {
                      applyTemplate(template);
                      message.success('已应用模板');
                    }
                  }}
                >
                  {templates.map(t => (
                    <Option key={t.id} value={t.id}>
                      {t.name} {t.is_default ? '(默认)' : ''} {t.position_info ? `- ${t.position_info.title}` : '- 通用'}
                    </Option>
                  ))}
                </Select>
                {templates.length === 0 && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    当前岗位暂无模板，可前往 <a onClick={() => window.open('/offers/templates', '_blank')}>Offer模板管理</a> 创建
                  </Text>
                )}
              </Form.Item>
            </Col>
          </Row>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="candidate_name" label="候选人姓名" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="candidate_email" label="候选人邮箱" rules={[{ required: true }, { type: 'email' }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          
          <Form.Item name="position_id" hidden>
            <Input />
          </Form.Item>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="position_title" label="岗位名称" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="department" label="部门">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="salary_monthly" label="月薪(元)">
                <InputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="salary_annual" label="年薪(元)">
                <InputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="salary_structure" label="薪资结构说明">
            <TextArea rows={2} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="work_location" label="工作地点">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="work_hours" label="工作时间">
                <Input placeholder="如: 9:00-18:00" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="onboard_date" label="入职日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="probation_months" label="试用期(月)" initialValue={3}>
                <InputNumber style={{ width: '100%' }} min={0} max={12} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="report_to" label="汇报对象">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="valid_until" label="有效期至">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="benefits" label="福利待遇">
            <TextArea rows={2} />
          </Form.Item>
          <Form.Item name="bonus" label="奖金说明">
            <TextArea rows={2} />
          </Form.Item>
          <Form.Item name="special_terms" label="特殊条款">
            <TextArea rows={2} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑Offer"
        open={editModalVisible}
        onCancel={() => setEditModalVisible(false)}
        onOk={() => editForm.submit()}
        width={700}
      >
        <Form form={editForm} layout="vertical" onFinish={handleEdit}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="salary_monthly" label="月薪(元)">
                <InputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="salary_annual" label="年薪(元)">
                <InputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="salary_structure" label="薪资结构说明">
            <TextArea rows={2} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="work_location" label="工作地点">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="work_hours" label="工作时间">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="onboard_date" label="入职日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="probation_months" label="试用期(月)">
                <InputNumber style={{ width: '100%' }} min={0} max={12} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="report_to" label="汇报对象">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="valid_until" label="有效期至">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="benefits" label="福利待遇">
            <TextArea rows={2} />
          </Form.Item>
          <Form.Item name="bonus" label="奖金说明">
            <TextArea rows={2} />
          </Form.Item>
          <Form.Item name="special_terms" label="特殊条款">
            <TextArea rows={2} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="变更Offer状态"
        open={statusModalVisible}
        onCancel={() => setStatusModalVisible(false)}
        onOk={handleMarkPendingConfirmation}
        okText="变更为Offer待确认"
        cancelText="取消"
      >
        <p>系统不会发送 Offer 邮件。请确认已通过线下渠道将 Offer 交付候选人，再将状态变更为“Offer待确认”。之后由该岗位招聘负责人登记候选人的最终结果。</p>
      </Modal>

      <Modal
        title={currentOffer?.status === 'rejected' ? '更正为接受Offer' : '确认候选人接受Offer'}
        open={acceptModalVisible}
        onCancel={() => setAcceptModalVisible(false)}
        onOk={() => acceptForm.submit()}
      >
        <Form form={acceptForm} layout="vertical" onFinish={handleAccept}>
          <p>请确认候选人已接受“{currentOffer?.position_title}”岗位的 Offer。提交后系统将同步更新简历及统计状态。</p>
          {currentOffer?.status === 'rejected' && (
            <Form.Item name="correction_reason" label="更正原因" rules={[{ required: true, message: '请填写更正原因' }]}>
              <TextArea rows={3} placeholder="请说明本次更正原因" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      <Modal
        title={currentOffer?.status === 'accepted' ? '更正为拒绝Offer' : '登记候选人拒绝Offer'}
        open={rejectModalVisible}
        onCancel={() => setRejectModalVisible(false)}
        onOk={() => rejectForm.submit()}
      >
        <Form form={rejectForm} layout="vertical" onFinish={handleReject}>
          <Form.Item name="rejection_reason" label="拒绝原因" rules={[{ required: true, message: '请选择拒绝原因' }]}>
            <Select>
              <Option value="salary">薪资不符</Option>
              <Option value="other_offer">接受其他 Offer</Option>
              <Option value="position_mismatch">岗位不匹配</Option>
              <Option value="location">地点/通勤原因</Option>
              <Option value="onboard_date">入职时间不符</Option>
              <Option value="personal">个人原因</Option>
              <Option value="unreachable">无法联系</Option>
              <Option value="other">其他</Option>
            </Select>
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, next) => prev.rejection_reason !== next.rejection_reason}>
            {({ getFieldValue }) => getFieldValue('rejection_reason') === 'other' ? (
              <Form.Item name="rejection_detail" label="其他原因说明" rules={[{ required: true, message: '请填写其他原因说明' }]}>
                <TextArea rows={3} />
              </Form.Item>
            ) : null}
          </Form.Item>
          {currentOffer?.status === 'accepted' && (
            <Form.Item name="correction_reason" label="更正原因" rules={[{ required: true, message: '请填写更正原因' }]}>
              <TextArea rows={3} placeholder="请说明本次更正原因" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      <Drawer
        title="Offer详情"
        placement="right"
        width={600}
        onClose={() => setDetailDrawerVisible(false)}
        open={detailDrawerVisible}
      >
        {currentOffer && (
          <div>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="候选人" span={2}>
                <Text strong>{currentOffer.candidate_name}</Text>
                <br />
                <Text type="secondary">{currentOffer.candidate_email}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="岗位">{currentOffer.position_title}</Descriptions.Item>
              <Descriptions.Item label="部门">{currentOffer.department || '-'}</Descriptions.Item>
              <Descriptions.Item label="月薪">
                {currentOffer.salary_monthly ? `${currentOffer.salary_monthly.toLocaleString()}元` : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="年薪">
                {currentOffer.salary_annual ? `${currentOffer.salary_annual.toLocaleString()}元` : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="工作地点">{currentOffer.work_location || '-'}</Descriptions.Item>
              <Descriptions.Item label="工作时间">{currentOffer.work_hours || '-'}</Descriptions.Item>
              <Descriptions.Item label="入职日期">
                {currentOffer.onboard_date ? dayjs(currentOffer.onboard_date).format('YYYY-MM-DD') : '待定'}
              </Descriptions.Item>
              <Descriptions.Item label="试用期">{currentOffer.probation_months}个月</Descriptions.Item>
              <Descriptions.Item label="汇报对象">{currentOffer.report_to || '-'}</Descriptions.Item>
              <Descriptions.Item label="有效期至">
                {currentOffer.valid_until ? dayjs(currentOffer.valid_until).format('YYYY-MM-DD') : '长期有效'}
              </Descriptions.Item>
              <Descriptions.Item label="状态" span={2}>
                <Tag color={statusConfig[currentOffer.status]?.color}>
                  {statusConfig[currentOffer.status]?.text}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {formatOfferDateTime(currentOffer.created_at)}
              </Descriptions.Item>
              <Descriptions.Item label="发送时间">
                {formatOfferDateTime(currentOffer.sent_at)}
              </Descriptions.Item>
              {currentOffer.accepted_at && (
                <Descriptions.Item label="接受时间">
                  {formatOfferDateTime(currentOffer.accepted_at)}
                </Descriptions.Item>
              )}
              {currentOffer.rejected_at && (
                <>
                  <Descriptions.Item label="拒绝时间">
                    {formatOfferDateTime(currentOffer.rejected_at)}
                  </Descriptions.Item>
                  <Descriptions.Item label="拒绝原因" span={2}>
                    {formatRejectedReason(currentOffer.rejected_reason)}
                  </Descriptions.Item>
                </>
              )}
            </Descriptions>
            <Divider>结果变更记录</Divider>
            {decisionAudits.length > 0 ? (
              <Timeline
                items={decisionAudits.map((audit) => ({
                  color: audit.new_status === 'accepted' ? 'green' : 'red',
                  children: (
                    <div>
                      <Text strong>
                        {statusConfig[audit.previous_status]?.text || audit.previous_status}
                        {' → '}
                        {statusConfig[audit.new_status]?.text || audit.new_status}
                      </Text>
                      <div><Text type="secondary">{audit.actor_name} · {formatOfferDateTime(audit.created_at)}</Text></div>
                      {audit.rejection_reason && <div>拒绝原因：{rejectionReasonLabels[audit.rejection_reason] || audit.rejection_reason}{audit.rejection_detail ? `（${audit.rejection_detail}）` : ''}</div>}
                      {audit.correction_reason && <div>更正原因：{audit.correction_reason}</div>}
                    </div>
                  ),
                }))}
              />
            ) : <Text type="secondary">暂无结果变更记录</Text>}

            {currentOffer.salary_structure && (
              <>
                <Divider>薪资结构</Divider>
                <Text>{currentOffer.salary_structure}</Text>
              </>
            )}

            {currentOffer.benefits && (
              <>
                <Divider>福利待遇</Divider>
                <Text>{currentOffer.benefits}</Text>
              </>
            )}

            {currentOffer.bonus && (
              <>
                <Divider>奖金说明</Divider>
                <Text>{currentOffer.bonus}</Text>
              </>
            )}

            {currentOffer.special_terms && (
              <>
                <Divider>特殊条款</Divider>
                <Text>{currentOffer.special_terms}</Text>
              </>
            )}

            {currentOffer.notes && (
              <>
                <Divider>备注</Divider>
                <Text>{currentOffer.notes}</Text>
              </>
            )}
          </div>
        )}
      </Drawer>

      <Modal
        title="确认实际入职"
        open={onboardingModalVisible}
        okText="确认入职"
        cancelText="取消"
        onOk={confirmOnboarding}
        onCancel={() => setOnboardingModalVisible(false)}
      >
        <Alert
          type="info"
          showIcon
          title="确认后，简历状态将更新为“已入职”，并用于招聘绩效结算。"
          style={{ marginBottom: 16 }}
        />
        <Form form={onboardingForm} layout="vertical">
          <Form.Item name="actual_onboard_date" label="实际入职日期" rules={[{ required: true, message: '请选择实际入职日期' }]}>
            <DatePicker style={{ width: '100%' }} disabledDate={(date) => date && date.isAfter(dayjs(), 'day')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default OffersList;
