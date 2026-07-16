import React, { useState } from 'react';
import { Form, Input, Button, Card, Upload, Select, message } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import request from '../../utils/request';

const QuestionBankUpload: React.FC = () => {
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [fileList, setFileList] = useState<any[]>([]);

  const onFinish = async (values: any) => {
    if (fileList.length === 0) {
      message.error('请上传题库文件');
      return;
    }

    const formData = new FormData();
    formData.append('name', values.name);
    formData.append('category', values.category);
    formData.append('difficulty', values.difficulty);
    if (values.tags) {
      formData.append('tags', values.tags.join(','));
    }
    formData.append('file', fileList[0].originFileObj);

    setLoading(true);
    try {
      await request.post('/question-banks', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      message.success('上传成功');
      navigate('/question-banks');
    } catch (error) {
      message.error('上传失败');
    } finally {
      setLoading(false);
    }
  };

  const uploadProps = {
    onRemove: (file) => {
      setFileList([]);
    },
    beforeUpload: (file) => {
      setFileList([file]);
      return false;
    },
    fileList,
  };

  return (
    <Card title="上传题库">
      <Form
        form={form}
        layout="vertical"
        onFinish={onFinish}
        initialValues={{ category: 'technical', difficulty: 'intermediate' }}
      >
        <Form.Item
          name="name"
          label="题库名称"
          rules={[{ required: true, message: '请输入题库名称' }]}
        >
          <Input />
        </Form.Item>

        <Form.Item
          name="category"
          label="分类"
          rules={[{ required: true, message: '请选择分类' }]}
        >
          <Select>
            <Select.Option value="technical">技术</Select.Option>
            <Select.Option value="management">管理</Select.Option>
            <Select.Option value="hr">人力资源</Select.Option>
            <Select.Option value="other">其他</Select.Option>
          </Select>
        </Form.Item>

        <Form.Item
          name="difficulty"
          label="难度"
          rules={[{ required: true, message: '请选择难度' }]}
        >
          <Select>
            <Select.Option value="junior">初级</Select.Option>
            <Select.Option value="intermediate">中级</Select.Option>
            <Select.Option value="senior">高级</Select.Option>
          </Select>
        </Form.Item>

        <Form.Item
          name="tags"
          label="标签"
        >
          <Select mode="tags" style={{ width: '100%' }} placeholder="请输入标签" />
        </Form.Item>

        <Form.Item
          name="file"
          label="题库文件"
          rules={[{ required: true, message: '请上传文件' }]}
        >
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>
            上传
          </Button>
          <Button style={{ marginLeft: 8 }} onClick={() => navigate('/question-banks')}>
            取消
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
};

export default QuestionBankUpload;
