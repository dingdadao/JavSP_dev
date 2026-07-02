import { useEffect, useState } from 'react'
import {
  Card, Input, Button, Space, Switch, Typography, Form,
  Alert, Progress, Tag, Steps, Result, Divider, Row, Col, message
} from 'antd'
import {
  PlayCircleOutlined, ScanOutlined, CheckCircleOutlined,
  LoadingOutlined, FolderOutlined, RocketOutlined
} from '@ant-design/icons'
import { useSocket } from '../hooks/useSocket'
import { createScrapeTask, fetchConfig } from '../api'

export default function Scrape() {
  const { lastProgress } = useSocket()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [config, setConfig] = useState<any>({})

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    try {
      const { data } = await fetchConfig()
      setConfig(data)
      const scanner = data?.scanner || {}
      const summarizer = data?.summarizer || {}
      form.setFieldsValue({
        source: scanner.input_directory || '',
        dest: summarizer.output_folder_pattern || '',
        translate: true,
        move_files: summarizer.move_files ?? true,
      })
    } catch (e) {
      console.error(e)
    }
  }

  const handleSubmit = async (values: any) => {
    setLoading(true)
    try {
      const res = await createScrapeTask(values)
      if (res.code === 0) {
        setTaskId(res.data.task_id)
        message.success(res.message)
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '创建任务失败')
    } finally {
      setLoading(false)
    }
  }

  const isRunning = lastProgress?.status === 'running'
  const isDone = taskId && lastProgress && ['completed', 'partial', 'failed', 'error'].includes(lastProgress.status)

  const currentStep = isRunning ? 1 : isDone ? 2 : 0

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <RocketOutlined /> 开始刮削
      </Typography.Title>

      <Row gutter={24}>
        <Col xs={24} lg={10}>
          <Card title="刮削设置" bordered={false}>
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
              initialValues={{ translate: true, move_files: true }}
            >
              <Form.Item
                label={<Space><FolderOutlined />{'源文件夹路径'}</Space>}
                name="source"
                rules={[{ required: true, message: '请输入源文件夹路径' }]}
                extra="包含影片文件的目录，程序将自动扫描并识别番号"
              >
                <Input placeholder="/path/to/movies" />
              </Form.Item>

              <Form.Item
                label={<Space><FolderOutlined />{'输出文件夹路径'}</Space>}
                name="dest"
                rules={[{ required: true, message: '请输入输出路径' }]}
                extra="刮削结果(NFO, 封面等)将保存到此目录"
              >
                <Input placeholder="/path/to/output" />
              </Form.Item>

              <Form.Item label="翻译标题和简介" name="translate" valuePropName="checked">
                <Switch />
              </Form.Item>

              <Form.Item label="移动文件（否则复制）" name="move_files" valuePropName="checked">
                <Switch />
              </Form.Item>

              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<PlayCircleOutlined />}
                  loading={loading}
                  disabled={isRunning}
                  size="large"
                  block
                >
                  {isRunning ? '任务进行中...' : '开始刮削'}
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={14}>
          <Card title="刮削进度" bordered={false}>
            <Steps
              current={currentStep}
              items={[
                { title: '准备', icon: <ScanOutlined /> },
                { title: '刮削中', icon: isRunning ? <LoadingOutlined /> : <PlayCircleOutlined /> },
                { title: '完成', icon: <CheckCircleOutlined /> },
              ]}
              style={{ marginBottom: 32 }}
            />

            {isRunning && lastProgress && (
              <Space direction="vertical" style={{ width: '100%' }} size="large">
                <Alert
                  type="info"
                  showIcon
                  message={lastProgress.message}
                  description={lastProgress.current ? `当前: ${lastProgress.current}` : undefined}
                />
                <Progress
                  percent={lastProgress.total ? Math.round(((lastProgress.completed || 0) / lastProgress.total) * 100) : 0}
                  status="active"
                  strokeColor={{ from: '#6366f1', to: '#22c55e' }}
                  size="default"
                />
                <Row gutter={16}>
                  <Col span={8}>
                    <Card size="small" bordered={false}>
                      <Typography.Text type="secondary">总计</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold' }}>{lastProgress.total || 0}</div>
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card size="small" bordered={false}>
                      <Typography.Text type="secondary">成功</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: '#22c55e' }}>{lastProgress.success || 0}</div>
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card size="small" bordered={false}>
                      <Typography.Text type="secondary">失败</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: '#ef4444' }}>{lastProgress.failed || 0}</div>
                    </Card>
                  </Col>
                </Row>
              </Space>
            )}

            {isDone && (
              <Result
                status={lastProgress.status === 'completed' ? 'success' : lastProgress.status === 'failed' ? 'error' : 'warning'}
                title={lastProgress.message}
                subTitle={`成功 ${(lastProgress as any).success || 0} / ${lastProgress.total || 0}`}
              />
            )}

            {!isRunning && !isDone && (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'rgba(255,255,255,0.25)' }}>
                <PlayCircleOutlined style={{ fontSize: 64 }} />
                <div style={{ marginTop: 16, fontSize: 16 }}>
                  配置好路径后点击「开始刮削」启动任务
                </div>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
