import React, { useEffect, useState } from 'react';
import { Table, Button, Space, message, Modal, Form, Input, Select, Tag, Tooltip, Typography, Drawer, Descriptions, Divider, Progress, Badge, Spin, Popconfirm } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, EyeOutlined, GlobalOutlined, StopOutlined, CopyOutlined, RobotOutlined, ThunderboltOutlined, DeleteFilled } from '@ant-design/icons';
import request from '../../utils/request';
import JDGeneratorModal from '../../components/JDGeneratorModal';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const { Title, Text } = Typography;

interface PositionStats {
  total_resumes: number;
  pending_screening: number;
  pending_interview: number;
  interview_completed: number;
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
  status: string;
  urgency: string;
  position_type: string;
  headcount: number;
  hiring_manager_id: string | null;
  hiring_manager_name: string | null;
  created_at: string;
  updated_at: string;
  stats: PositionStats;
  linked_question_banks?: QuestionBankBrief[];
}

const urgencyConfig: Record<string, { color: string; text: string }> = {
  low: { color: 'default', text: '低' },
  medium: { color: 'warning', text: '中' },
  high: { color: 'orange', text: '高' },
  urgent: { color: 'red', text: '紧急' },
};

const positionTypeConfig: Record<string, { color: string; text: string }> = {
  full_time: { color: 'blue', text: '全职' },
  part_time: { color: 'cyan', text: '兼职' },
  contract: { color: 'purple', text: '合同' },
  internship: { color: 'green', text: '实习' },
};

const PositionsList: React.FC = () => {
  const [data, setData] = useState<Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [isDrawerVisible, setIsDrawerVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [viewingRecord, setViewingRecord] = useState<Position | null>(null);
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [users, setUsers] = useState<any[]>([]);
  const [jdModalVisible, setJdModalVisible] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  const [searchTitle, setSearchTitle] = useState<string>('');
  const [searchStatus, setSearchStatus] = useState<string | undefined>(undefined);

  const fetchPositions = async () => {
    setLoading(true);
    try {
      const res = await request.get('/positions', {
          params: {
              title: searchTitle,
              status: searchStatus
          }
      });
      setData(res);
    } catch (error) {
      message.error('获取岗位列表失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchUsers = async () => {
    try {
      const res = await request.get('/auth/users');
      setUsers(res);
    } catch (error) {
      console.error('Failed to fetch users');
    }
  };

  useEffect(() => {
    fetchPositions();
    fetchUsers();
  }, [searchTitle, searchStatus]);

  const handleAdd = () => {
    setEditingId(null);
    form.resetFields();
    form.setFieldsValue({ status: 'open', urgency: 'medium', position_type: 'full_time', headcount: 1 });
    setIsModalVisible(true);
  };

  const handleEdit = async (record: Position) => {
    setEditingId(record.id);
    try {
      const res = await request.get(`/positions/${record.id}`);
      form.setFieldsValue(res);
      setIsModalVisible(true);
    } catch (error) {
      message.error('获取岗位详情失败');
    }
  };

  const handleView = async (record: Position) => {
    try {
      const res = await request.get(`/positions/${record.id}`);
      setViewingRecord(res);
      setIsDrawerVisible(true);
    } catch (error) {
      message.error('获取岗位详情失败');
    }
  };

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个岗位吗？',
      okText: '确认',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await request.delete(`/positions/${id}`);
          message.success('删除成功');
          fetchPositions();
        } catch (error) {
          message.error('删除失败');
        }
      },
    });
  };

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的岗位');
      return;
    }
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 个岗位吗？`,
      okText: '确认',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await Promise.all(selectedRowKeys.map(id => request.delete(`/positions/${id}`)));
          message.success(`成功删除 ${selectedRowKeys.length} 个岗位`);
          setSelectedRowKeys([]);
          fetchPositions();
        } catch (error) {
          message.error('批量删除失败');
        }
      },
    });
  };

  const handleBatchPublish = (publish: boolean) => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要操作的岗位');
      return;
    }
    Modal.confirm({
      title: publish ? '确认批量发布' : '确认批量下架',
      content: `确定要${publish ? '发布' : '下架'}选中的 ${selectedRowKeys.length} 个岗位吗？`,
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await Promise.all(selectedRowKeys.map(id => request.put(`/positions/${id}`, { status: publish ? 'published' : 'closed' })));
          message.success(`成功${publish ? '发布' : '下架'} ${selectedRowKeys.length} 个岗位`);
          setSelectedRowKeys([]);
          fetchPositions();
        } catch (error) {
          message.error('操作失败');
        }
      },
    });
  };

  const handlePublish = async (id: string, publish: boolean) => {
    try {
      await request.put(`/positions/${id}`, { status: publish ? 'published' : 'closed' });
      message.success(publish ? '岗位已发布' : '岗位已下架');
      fetchPositions();
    } catch (error) {
      message.error('操作失败');
    }
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
      } catch (err) {
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
      const values = await form.validateFields();
      setSubmitting(true);
      if (editingId) {
        await request.put(`/positions/${editingId}`, values);
        message.success('更新成功');
      } else {
        await request.post('/positions', values);
        message.success('创建成功');
      }
      setIsModalVisible(false);
      fetchPositions();
    } catch (error) {
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

  const columns = [
    { 
      title: '岗位名称',
      dataIndex: 'title', 
      key: 'title',
      render: (text: string) => <span style={{ fontWeight: 500, color: '#0F172A' }}>{text}</span>
    },
    { title: '部门', dataIndex: 'department', key: 'department', render: (v: string) => v || '-' },
    { 
      title: '类型', 
      dataIndex: 'position_type', 
      key: 'position_type',
      render: (type: string) => {
        const config = positionTypeConfig[type] || { color: 'default', text: type };
        return <Tag color={config.color} style={{ border: 'none' }}>{config.text}</Tag>;
      }
    },
    { 
      title: '紧急度', 
      dataIndex: 'urgency', 
      key: 'urgency',
      render: (urgency: string) => {
        const config = urgencyConfig[urgency] || { color: 'default', text: urgency };
        return <Tag color={config.color} style={{ border: 'none' }}>{config.text}</Tag>;
      }
    },
    { 
      title: '状态', 
      dataIndex: 'status', 
      key: 'status',
      render: (status: string) => {
        let color = 'default';
        let text = '已关闭';
        if (status === 'open') {
            color = 'warning';
            text = '待发布';
        } else if (status === 'published') {
            color = 'processing';
            text = '招聘中';
        }
        return <Tag color={color} style={{ border: 'none' }}>{text}</Tag>;
      }
    },
    { 
      title: '招聘进度', 
      key: 'stats',
      render: (_: any, record: Position) => renderStats(record.stats)
    },
    { 
      title: '创建时间', 
      dataIndex: 'created_at', 
      key: 'created_at',
      render: (date: string) => <span style={{ color: '#64748B' }}>{new Date(date).toLocaleDateString()}</span>
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Position) => (
        <Space size="small">
          <Tooltip title="查看详情">
            <Button type="text" icon={<EyeOutlined style={{ color: '#3B82F6' }} />} onClick={() => handleView(record)} />
          </Tooltip>
          {record.status === 'published' ? (
             <Tooltip title="下架岗位">
                <Button type="text" icon={<StopOutlined style={{ color: '#EF4444' }} />} onClick={() => handlePublish(record.id, false)} />
             </Tooltip>
          ) : (
             <Tooltip title="发布岗位">
                <Button type="text" icon={<GlobalOutlined style={{ color: '#10B981' }} />} onClick={() => handlePublish(record.id, true)} />
             </Tooltip>
          )}
          {record.status === 'published' && (
             <Tooltip title="复制链接">
                <Button type="text" icon={<CopyOutlined />} onClick={() => handleCopyLink(record.id)} />
             </Tooltip>
          )}
          <Tooltip title="编辑">
            <Button type="text" icon={<EditOutlined style={{ color: '#64748B' }} />} onClick={() => handleEdit(record)} />
          </Tooltip>
          <Tooltip title="删除">
            <Button type="text" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)} />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 32, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <Title level={2} style={{ margin: 0, fontWeight: 700 }}>岗位管理</Title>
          <Text type="secondary">管理企业的招聘岗位信息</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd} size="large" style={{ borderRadius: '8px' }}>新增岗位</Button>
      </div>
      
      <div style={{ marginBottom: 24, padding: '24px', background: '#fff', borderRadius: '12px', border: '1px solid #E2E8F0', display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center' }}>
          <Input 
              placeholder="搜索岗位名称" 
              prefix={<EyeOutlined style={{ color: '#94A3B8' }} />} 
              style={{ width: 300 }} 
              allowClear
              onChange={(e) => setSearchTitle(e.target.value)}
          />
          <Select
              placeholder="岗位状态"
              style={{ width: 150 }}
              allowClear
              onChange={(value) => setSearchStatus(value)}
          >
              <Select.Option value="open">待发布</Select.Option>
              <Select.Option value="published">招聘中</Select.Option>
              <Select.Option value="closed">已关闭</Select.Option>
          </Select>
          {selectedRowKeys.length > 0 && (
            <Space>
              <span style={{ color: '#64748B' }}>已选 {selectedRowKeys.length} 项</span>
              <Button onClick={() => handleBatchPublish(true)} type="primary" ghost>批量发布</Button>
              <Button onClick={() => handleBatchPublish(false)}>批量下架</Button>
              <Button danger onClick={handleBatchDelete}>批量删除</Button>
              <Button onClick={() => setSelectedRowKeys([])}>取消选择</Button>
            </Space>
          )}
      </div>
      
      <Table 
        columns={columns} 
        dataSource={data} 
        loading={loading} 
        rowKey="id" 
        pagination={{ pageSize: 10, showSizeChanger: true }}
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
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
        destroyOnClose
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
              name="urgency"
              label="紧急程度"
            >
              <Select size="large">
                <Select.Option value="low">低</Select.Option>
                <Select.Option value="medium">中</Select.Option>
                <Select.Option value="high">高</Select.Option>
                <Select.Option value="urgent">紧急</Select.Option>
              </Select>
            </Form.Item>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            <Form.Item
              name="hiring_manager_id"
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
            <Select size="large">
              <Select.Option value="open">待发布</Select.Option>
              <Select.Option value="published">招聘中</Select.Option>
              <Select.Option value="closed">已关闭</Select.Option>
            </Select>
          </Form.Item>
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
        width={800}
        onClose={() => setIsDrawerVisible(false)}
        open={isDrawerVisible}
        extra={
          <Space>
            <Button onClick={() => {
              setIsDrawerVisible(false);
              if (viewingRecord) handleEdit(viewingRecord);
            }}>编辑</Button>
            <Button type="primary" onClick={() => setIsDrawerVisible(false)}>关闭</Button>
          </Space>
        }
      >
        {viewingRecord && (
          <div>
            <div style={{ marginBottom: 24 }}>
              <Title level={3} style={{ margin: 0 }}>{viewingRecord.title}</Title>
              <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                <Tag color={viewingRecord.status === 'published' ? 'processing' : 'default'} style={{ border: 'none' }}>
                  {viewingRecord.status === 'published' ? '招聘中' : viewingRecord.status === 'open' ? '待发布' : '已关闭'}
                </Tag>
                <Tag color={urgencyConfig[viewingRecord.urgency]?.color || 'default'} style={{ border: 'none' }}>
                  {urgencyConfig[viewingRecord.urgency]?.text || viewingRecord.urgency}
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
            </Descriptions>

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
                  <Text type="secondary">已入职</Text>
                  <div style={{ fontSize: 24, fontWeight: 600, color: '#10B981' }}>{viewingRecord.stats?.offer_accepted || 0}</div>
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