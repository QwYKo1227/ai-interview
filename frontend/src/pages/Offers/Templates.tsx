import React, { useEffect, useState } from 'react';
import {
  Card, Table, Button, Space, Modal, Form, Input, InputNumber, Select, 
  message, Popconfirm, Tag, Typography, Row, Col, Switch, Tooltip
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, FileTextOutlined
} from '@ant-design/icons';
import request from '../../utils/request';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { Option } = Select;

interface OfferTemplate {
  id: string;
  name: string;
  position_id: string | null;
  salary_monthly: number | null;
  salary_annual: number | null;
  salary_structure: string | null;
  department: string | null;
  report_to: string | null;
  work_location: string | null;
  work_hours: string | null;
  probation_months: number;
  benefits: string | null;
  bonus: string | null;
  special_terms: string | null;
  notes: string | null;
  valid_days: number;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
  position_info: {
    id: string;
    title: string;
    department: string;
    location: string;
  } | null;
}

const OfferTemplates: React.FC = () => {
  const [templates, setTemplates] = useState<OfferTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [positions, setPositions] = useState<any[]>([]);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  
  const [modalVisible, setModalVisible] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<OfferTemplate | null>(null);
  const [form] = Form.useForm();

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const response = await request.get('/offer-templates?include_inactive=true');
      setTemplates(response.items || []);
    } catch (error) {
      message.error('获取模板列表失败');
    } finally {
      setLoading(false);
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

  useEffect(() => {
    fetchTemplates();
    fetchPositions();
  }, []);

  const handleCreate = () => {
    setEditingTemplate(null);
    form.resetFields();
    form.setFieldsValue({
      probation_months: 3,
      valid_days: 7,
      is_default: false,
    });
    setModalVisible(true);
  };

  const handleEdit = (template: OfferTemplate) => {
    setEditingTemplate(template);
    form.setFieldsValue({
      ...template,
      position_id: template.position_id || undefined,
    });
    setModalVisible(true);
  };

  const handleSubmit = async (values: any) => {
    try {
      if (editingTemplate) {
        await request.put(`/offer-templates/${editingTemplate.id}`, values);
        message.success('模板更新成功');
      } else {
        await request.post('/offer-templates', values);
        message.success('模板创建成功');
      }
      setModalVisible(false);
      fetchTemplates();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '操作失败');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await request.delete(`/offer-templates/${id}`);
      message.success('模板删除成功');
      fetchTemplates();
    } catch (error: any) {
      message.error(error.response?.data?.detail || '删除失败');
    }
  };

  const handleToggleActive = async (template: OfferTemplate) => {
    try {
      await request.put(`/offer-templates/${template.id}`, {
        is_active: !template.is_active
      });
      message.success(template.is_active ? '模板已停用' : '模板已启用');
      fetchTemplates();
    } catch (error: any) {
      message.error('操作失败');
    }
  };

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的模板');
      return;
    }
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 个模板吗？`,
      okText: '确认',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await Promise.all(selectedRowKeys.map(id => request.delete(`/offer-templates/${id}`)));
          message.success(`成功删除 ${selectedRowKeys.length} 个模板`);
          setSelectedRowKeys([]);
          fetchTemplates();
        } catch (error) {
          message.error('批量删除失败');
        }
      },
    });
  };

  const columns = [
    {
      title: '模板名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: OfferTemplate) => (
        <div>
          <Text strong>{text}</Text>
          {record.is_default && <Tag color="blue" style={{ marginLeft: 8 }}>默认</Tag>}
          {!record.is_active && <Tag color="red" style={{ marginLeft: 8 }}>已停用</Tag>}
        </div>
      ),
    },
    {
      title: '关联岗位',
      dataIndex: 'position_info',
      key: 'position',
      render: (info: any) => info ? info.title : <Text type="secondary">通用模板</Text>,
    },
    {
      title: '薪资',
      key: 'salary',
      render: (_: any, record: OfferTemplate) => (
        <div>
          {record.salary_monthly && <Text>月薪 {record.salary_monthly.toLocaleString()}元</Text>}
          {record.salary_annual && <><br /><Text type="secondary">年薪 {record.salary_annual.toLocaleString()}元</Text></>}
          {!record.salary_monthly && !record.salary_annual && <Text type="secondary">未设置</Text>}
        </div>
      ),
    },
    {
      title: '工作地点',
      dataIndex: 'work_location',
      key: 'work_location',
      render: (text: string) => text || <Text type="secondary">-</Text>,
    },
    {
      title: '试用期',
      dataIndex: 'probation_months',
      key: 'probation_months',
      render: (months: number) => `${months}个月`,
    },
    {
      title: '有效期',
      dataIndex: 'valid_days',
      key: 'valid_days',
      render: (days: number) => `${days}天`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => dayjs(date).format('YYYY-MM-DD'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: OfferTemplate) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button type="text" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          </Tooltip>
          <Tooltip title={record.is_active ? '停用' : '启用'}>
            <Switch 
              size="small" 
              checked={record.is_active} 
              onChange={() => handleToggleActive(record)}
            />
          </Tooltip>
          <Popconfirm title="确定删除此模板？" onConfirm={() => handleDelete(record.id)}>
            <Tooltip title="删除">
              <Button type="text" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0 }}>Offer模板管理</Title>
        <Text type="secondary">管理Offer模板，新建Offer时可自动填充</Text>
      </div>

      <Card>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
          <Space>
            <Text>共 {templates.length} 个模板</Text>
            {selectedRowKeys.length > 0 && (
              <>
                <span style={{ lineHeight: '32px' }}>已选 {selectedRowKeys.length} 项</span>
                <Button danger onClick={handleBatchDelete}>批量删除</Button>
                <Button onClick={() => setSelectedRowKeys([])}>取消选择</Button>
              </>
            )}
          </Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新建模板</Button>
        </div>

        <Table
          columns={columns}
          dataSource={templates}
          rowKey="id"
          loading={loading}
          pagination={false}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys),
          }}
        />
      </Card>

      <Modal
        title={editingTemplate ? '编辑模板' : '新建模板'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={() => form.submit()}
        width={700}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="name" label="模板名称" rules={[{ required: true }]}>
                <Input placeholder="如：技术岗位标准Offer" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="position_id" label="关联岗位（可选）">
                <Select placeholder="选择岗位，留空表示通用模板" allowClear>
                  {positions.map(p => (
                    <Option key={p.id} value={p.id}>{p.title}</Option>
                  ))}
                </Select>
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
            <TextArea rows={2} placeholder="如：基本工资+绩效奖金+年终奖" />
          </Form.Item>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="department" label="部门">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="report_to" label="汇报对象">
                <Input />
              </Form.Item>
            </Col>
          </Row>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="work_location" label="工作地点">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="work_hours" label="工作时间">
                <Input placeholder="如：9:00-18:00" />
              </Form.Item>
            </Col>
          </Row>
          
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="probation_months" label="试用期(月)">
                <InputNumber style={{ width: '100%' }} min={0} max={12} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="valid_days" label="Offer有效期(天)">
                <InputNumber style={{ width: '100%' }} min={1} max={90} />
              </Form.Item>
            </Col>
          </Row>
          
          <Form.Item name="benefits" label="福利待遇">
            <TextArea rows={3} placeholder="五险一金、带薪年假、节日福利等" />
          </Form.Item>
          
          <Form.Item name="bonus" label="奖金说明">
            <TextArea rows={2} placeholder="年终奖、项目奖金、股权激励等" />
          </Form.Item>
          
          <Form.Item name="special_terms" label="特殊条款">
            <TextArea rows={2} placeholder="竞业限制、保密协议等" />
          </Form.Item>
          
          <Form.Item name="notes" label="备注">
            <TextArea rows={2} />
          </Form.Item>
          
          <Form.Item name="is_default" label="设为默认模板" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default OfferTemplates;
