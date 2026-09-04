import React, { useEffect, useState } from 'react';
import { Table, Button, Space, message, Tag, Modal, Form, Input, Select, Typography, Popconfirm, Tooltip } from 'antd';
import { PlusOutlined, ReloadOutlined, EditOutlined, DeleteOutlined, StopOutlined, CheckCircleOutlined, LockOutlined } from '@ant-design/icons';
import request from '../../utils/request';
import { useAuth } from '../../contexts/AuthContext';
import { PAGE_SIZE_OPTIONS, useListPageState, useListScrollRestoration } from '../../hooks/useListPageState';

const { Title, Text } = Typography;

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

const getErrorMessage = (error: unknown, fallback: string) => {
  const candidate = error as { response?: { data?: { detail?: unknown } } };
  const detail = candidate?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

const isFormValidationError = (error: unknown) => (
  Array.isArray((error as { errorFields?: unknown })?.errorFields)
);

const UsersList: React.FC = () => {
  const { page, pageSize, setPagination } = useListPageState();
  useListScrollRestoration();
  const { user: currentUser } = useAuth();
  const [data, setData] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [isEditModal, setIsEditModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();
  const [passwordForm] = Form.useForm();
  const [passwordUser, setPasswordUser] = useState<User | null>(null);
  const [passwordSubmitting, setPasswordSubmitting] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const res = await request.get('/auth/users');
      setData(res);
    } catch {
      message.error('获取用户列表失败（权限不足？）');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleAdd = () => {
    form.resetFields();
    setIsEditModal(false);
    setEditingUser(null);
    setIsModalVisible(true);
  };

  const handleEdit = (record: User) => {
    setEditingUser(record);
    setIsEditModal(true);
    form.setFieldsValue({
      full_name: record.full_name,
      role: record.role,
    });
    setIsModalVisible(true);
  };

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);

      if (isEditModal && editingUser) {
        // 更新用户基本信息
        await request.put(`/auth/users/${editingUser.id}`, {
          full_name: values.full_name,
        });
        // 更新角色
        if (values.role !== editingUser.role) {
          await request.put(`/auth/users/${editingUser.id}/role?role=${values.role}`);
        }
        message.success('用户更新成功');
      } else {
        // 创建新用户
        await request.post('/auth/users', values);
        message.success('创建用户成功');
      }

      setIsModalVisible(false);
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, isEditModal ? '更新用户失败' : '创建用户失败'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleStatus = async (record: User) => {
    try {
      const res = await request.put(`/auth/users/${record.id}/status`);
      message.success(res.is_active ? '用户已启用' : '用户已禁用');
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleDelete = async (userId: string) => {
    try {
      await request.delete(`/auth/users/${userId}`);
      message.success('用户已删除');
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除失败'));
    }
  };

  const handleResetPassword = async () => {
    if (!passwordUser) return;
    try {
      const values = await passwordForm.validateFields();
      setPasswordSubmitting(true);
      await request.put(`/auth/users/${passwordUser.id}/password`, {
        new_password: values.new_password,
      });
      message.success('密码已更新，该用户需要重新登录');
      setPasswordUser(null);
      passwordForm.resetFields();
    } catch (error: unknown) {
      if (isFormValidationError(error)) return;
      message.error(getErrorMessage(error, '密码更新失败'));
    } finally {
      setPasswordSubmitting(false);
    }
  };

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的用户');
      return;
    }
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 个用户吗？`,
      okText: '确认',
      cancelText: '取消',
      okType: 'danger',
      onOk: async () => {
        try {
          await Promise.all(selectedRowKeys.map(id => request.delete(`/auth/users/${id}`)));
          message.success(`成功删除 ${selectedRowKeys.length} 个用户`);
          setSelectedRowKeys([]);
          fetchUsers();
        } catch {
          message.error('批量删除失败');
        }
      },
    });
  };

  const getRoleTag = (role: string) => {
    const roleConfig: Record<string, { color: string; label: string }> = {
      admin: { color: 'red', label: '管理员' },
      hr: { color: 'blue', label: 'HR' },
      interviewer: { color: 'green', label: '面试官' },
    };
    const config = roleConfig[role] || { color: 'default', label: role };
    return <Tag color={config.color}>{config.label}</Tag>;
  };

  const columns = [
    { title: '姓名', dataIndex: 'full_name', key: 'full_name', width: 150 },
    { title: '邮箱', dataIndex: 'email', key: 'email', width: 200 },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 120,
      render: (role: string) => getRoleTag(role),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (active: boolean) => (
        <Tag color={active ? 'success' : 'error'}>{active ? '启用' : '禁用'}</Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (date: string) => (date ? new Date(date).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      render: (_: unknown, record: User) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button
              type="text"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            />
          </Tooltip>
          {record.id !== currentUser?.id && (
            <Tooltip title="重置密码">
              <Button
                type="text"
                icon={<LockOutlined />}
                onClick={() => {
                  passwordForm.resetFields();
                  setPasswordUser(record);
                }}
              />
            </Tooltip>
          )}
          <Tooltip title={record.is_active ? '禁用' : '启用'}>
            <Button
              type="text"
              icon={record.is_active ? <StopOutlined /> : <CheckCircleOutlined />}
              onClick={() => handleToggleStatus(record)}
              style={{ color: record.is_active ? '#ff4d4f' : '#52c41a' }}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除该用户吗？"
            description="此操作不可恢复"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
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
      <div style={{ marginBottom: 32, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <Title level={2} style={{ margin: 0 }}>用户管理</Title>
          <Text type="secondary">管理系统用户及权限分配</Text>
        </div>
        <Space>
          {selectedRowKeys.length > 0 && (
            <>
              <span style={{ lineHeight: '32px' }}>已选 {selectedRowKeys.length} 项</span>
              <Button danger onClick={handleBatchDelete}>批量删除</Button>
              <Button onClick={() => setSelectedRowKeys([])}>取消选择</Button>
            </>
          )}
          <Button icon={<ReloadOutlined />} onClick={fetchUsers}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新增用户</Button>
        </Space>
      </div>

      <Table
        columns={columns}
        dataSource={data}
        loading={loading}
        rowKey="id"
        pagination={{
          current: page,
          pageSize,
          pageSizeOptions: PAGE_SIZE_OPTIONS,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: setPagination,
        }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
      />

      <Modal
        title={isEditModal ? '编辑用户' : '新增用户'}
        open={isModalVisible}
        onOk={handleOk}
        onCancel={() => setIsModalVisible(false)}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          {!isEditModal && (
            <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email', message: '请输入有效的邮箱地址' }]}>
              <Input placeholder="请输入邮箱" />
            </Form.Item>
          )}
          <Form.Item name="full_name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input placeholder="请输入姓名" />
          </Form.Item>
          {!isEditModal && (
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 6, message: '密码至少6位' }]}>
              <Input.Password placeholder="请输入密码" />
            </Form.Item>
          )}
          <Form.Item name="role" label="角色" initialValue="interviewer" rules={[{ required: true }]}>
            <Select>
              <Select.Option value="admin">管理员 (Admin)</Select.Option>
              <Select.Option value="hr">HR</Select.Option>
              <Select.Option value="interviewer">面试官 (Interviewer)</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码${passwordUser ? `：${passwordUser.full_name || passwordUser.email}` : ''}`}
        open={!!passwordUser}
        onOk={handleResetPassword}
        onCancel={() => {
          setPasswordUser(null);
          passwordForm.resetFields();
        }}
        confirmLoading={passwordSubmitting}
        okText="确认修改"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={passwordForm} layout="vertical">
          <Form.Item
            name="new_password"
            label="新密码"
            extra="至少 12 个 UTF-8 字节，且必须包含字母和数字"
            rules={[{ required: true, message: '请输入新密码' }]}
          >
            <Input.Password placeholder="请输入新密码" autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) return Promise.resolve();
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="请再次输入新密码" autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default UsersList;
