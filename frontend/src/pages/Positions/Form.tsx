import React, { useEffect, useState } from 'react';
import { Form, Input, Button, Card, message, Select, Typography } from 'antd';
import { useParams } from 'react-router-dom';
import { RobotOutlined, ArrowLeftOutlined } from '@ant-design/icons';
import request from '../../utils/request';
import JDGeneratorModal from '../../components/JDGeneratorModal';
import { useAuth } from '../../contexts/AuthContext';
import { useReturnToList } from '../../hooks/useListPageState';
import {
  getAllowedStatusOptions,
  normalizePositionClassification,
  POSITION_CATEGORY_OPTIONS,
  PRIORITY_OPTIONS,
  statusChangeRequiresReason,
  type PositionStatus,
} from './options';

const { Title, Text } = Typography;

const PositionForm: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [form] = Form.useForm();
  const returnToList = useReturnToList('/positions');
  const { id } = useParams();
  const [loading, setLoading] = useState(false);
  const [users, setUsers] = useState<any[]>([]);
  const [jdModalVisible, setJdModalVisible] = useState(false);
  const [originalPosition, setOriginalPosition] = useState<{ status: PositionStatus; hiring_manager_id: string | null } | null>(null);
  const selectedStatus = Form.useWatch('status', form) as PositionStatus | undefined;
  const selectedOwnerId = Form.useWatch('hiring_manager_id', form) as string | undefined;

  useEffect(() => {
    if (id) {
      fetchPosition(id);
    }
    fetchUsers();
  }, [id]);

  const fetchPosition = async (positionId: string) => {
    try {
      const res = await request.get(`/positions/${positionId}`);
      setOriginalPosition(res);
      form.setFieldsValue(res);
    } catch (error) {
      message.error('获取岗位详情失败');
    }
  };

  const fetchUsers = async () => {
    if (!isAdmin) {
      setUsers([]);
      return;
    }
    try {
      const res = await request.get('/positions/hiring-managers');
      setUsers(res);
    } catch (error) {
      console.error('Failed to fetch users');
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

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      if (id) {
        await request.put(`/positions/${id}`, normalizePositionClassification(values));
        message.success('更新成功');
      } else {
        await request.post('/positions', normalizePositionClassification(values));
        message.success('创建成功');
      }
      returnToList();
    } catch (error) {
      message.error('提交失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={returnToList}>
          返回列表
        </Button>
      </div>
      
      <Card>
        <Title level={4} style={{ marginBottom: 24 }}>{id ? '编辑岗位' : '新增岗位'}</Title>
        <Form
          form={form}
          layout="vertical"
          onFinish={onFinish}
          initialValues={{ status: 'open', priority: 3, category: 'uncategorized', position_type: 'full_time', headcount: 1 }}
          style={{ maxWidth: 800 }}
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
            <Input.TextArea rows={6} placeholder="请输入详细的岗位职责描述" showCount maxLength={2000} />
          </Form.Item>

          <Form.Item
            name="requirements"
            label="任职要求"
          >
            <Input.TextArea rows={6} placeholder="请输入任职资格要求" showCount maxLength={2000} />
          </Form.Item>

          <Form.Item
            name="status"
            label="状态"
          >
            <Select size="large" options={getAllowedStatusOptions(originalPosition?.status, isAdmin)} />
          </Form.Item>

          {originalPosition && selectedStatus !== originalPosition.status && <Form.Item
            name="status_change_reason"
            label="状态变更原因"
            rules={[{ required: statusChangeRequiresReason(originalPosition.status, selectedStatus), message: '请填写状态变更原因' }]}
          >
            <Input.TextArea rows={3} maxLength={1000} placeholder="请说明本次状态变更原因" />
          </Form.Item>}

          {originalPosition && isAdmin && selectedOwnerId !== originalPosition.hiring_manager_id && <Form.Item
            name="owner_change_reason"
            label="招聘负责人变更原因"
            rules={[{ required: true, message: '请填写招聘负责人变更原因' }]}
          >
            <Input.TextArea rows={3} maxLength={1000} placeholder="请说明本次负责人变更原因" />
          </Form.Item>}

          <Form.Item style={{ marginTop: 32 }}>
            <Button type="primary" htmlType="submit" loading={loading} size="large">
              提交
            </Button>
            <Button style={{ marginLeft: 12 }} onClick={returnToList} size="large">
              取消
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <JDGeneratorModal
        visible={jdModalVisible}
        onCancel={() => setJdModalVisible(false)}
        onConfirm={handleJDConfirm}
        title={form.getFieldValue('title') || ''}
        department={form.getFieldValue('department')}
        location={form.getFieldValue('location')}
        salary_range={form.getFieldValue('salary_range')}
      />
    </div>
  );
};

export default PositionForm;
