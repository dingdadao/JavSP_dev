import { useEffect, useState } from 'react'
import {
  Card, Input, Button, Space, Switch, Typography, Form,
  Alert, Progress, Tag, Steps, Result, Divider, Row, Col, App
} from 'antd'
import {
  PlayCircleOutlined, ScanOutlined, CheckCircleOutlined,
  LoadingOutlined, FolderOutlined, RocketOutlined,
  PauseCircleOutlined
} from '@ant-design/icons'
import { useSocket } from '../hooks/useSocket'
import { createScrapeTask, fetchConfig, fetchScrapeStatus, stopScrapeTask } from '../api'

export default function Scrape() {
  const { lastProgress, connected } = useSocket()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)
  const [config, setConfig] = useState<any>({})
  const { message } = App.useApp()

  // 系统永远只有一个任务，任何进度都直接显示
  const currentProgress = lastProgress?.status ? lastProgress : null

  useEffect(() => {
    loadConfig()
    // 页面加载时检查是否有进行中的任务（刷新页面后 taskId 会丢失）
    checkRunningTask()
  }, [])

  const checkRunningTask = async () => {
    try {
      const res = await fetchScrapeStatus()
      if (res.code === 0 && res.data?.status === 'running') {
        setTaskId(res.data.task_id)
      }
    } catch (e) {
      // 忽略
    }
  }

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

  const handleStop = async () => {
    setStopping(true)
    try {
      const res = await stopScrapeTask()
      if (res.code === 0) {
        message.success(res.message)
      } else {
        message.error(res.message)
        setStopping(false)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '停止任务失败')
      setStopping(false)
    }
  }

  const isRunning = currentProgress?.status === 'running'
  const isDone = taskId && currentProgress && ['completed', 'partial', 'failed', 'error', 'stopped'].includes(currentProgress.status)

  // 任务结束（无论完成、失败还是停止）后，重置 stopping 状态
  useEffect(() => {
    if (isDone) {
      setStopping(false)
    }
  }, [isDone])

  const currentStep = isRunning ? 1 : isDone ? 2 : 0

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <RocketOutlined /> 开始刮削
        <Tag color={connected ? 'success' : 'error'} style={{ marginLeft: 12 }}>
          {connected ? '实时连接正常' : '实时连接断开'}
        </Tag>
      </Typography.Title>

      <Row gutter={24}>
        <Col xs={24} lg={10}>
          <Card title="刮削设置" variant="borderless">
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

              {(isRunning || stopping) && (
                <Form.Item>
                  <Button
                    danger
                    icon={<PauseCircleOutlined />}
                    onClick={handleStop}
                    loading={stopping}
                    disabled={stopping}
                    size="large"
                    block
                  >
                    {stopping ? '正在停止...' : '停止任务'}
                  </Button>
                </Form.Item>
              )}
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={14}>
          <Card title="刮削进度" variant="borderless">
            <Steps
              current={currentStep}
              items={[
                { title: '准备', icon: <ScanOutlined /> },
                { title: isRunning ? '刮削中' : '刮削', icon: isRunning ? <LoadingOutlined /> : <PlayCircleOutlined /> },
                { title: currentProgress?.status === 'stopped' ? '已停止' : currentProgress?.status === 'failed' ? '失败' : '完成', icon: <CheckCircleOutlined /> },
              ]}
              style={{ marginBottom: 32 }}
            />

            {isRunning && currentProgress && (
              <Space direction="vertical" style={{ width: '100%' }} size="large">
                <Alert
                  type="info"
                  showIcon
                  message={currentProgress.message}
                  description={currentProgress.current ? `当前: ${currentProgress.current}` : undefined}
                />
                <Progress
                  percent={currentProgress.total ? Math.round(((currentProgress.completed || 0) / currentProgress.total) * 100) : 0}
                  status="active"
                  strokeColor={{ from: '#6366f1', to: '#22c55e' }}
                  size="default"
                />
                <Row gutter={16}>
                  <Col span={8}>
                    <Card size="small" variant="borderless">
                      <Typography.Text type="secondary">总计</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold' }}>{currentProgress.total || 0}</div>
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card size="small" variant="borderless">
                      <Typography.Text type="secondary">成功</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: '#22c55e' }}>{currentProgress.success || 0}</div>
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card size="small" variant="borderless">
                      <Typography.Text type="secondary">失败</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: '#ef4444' }}>{currentProgress.failed || 0}</div>
                    </Card>
                  </Col>
                </Row>
              </Space>
            )}

            {isDone && currentProgress && (
              <Result
                status={currentProgress.status === 'completed' ? 'success' : currentProgress.status === 'failed' ? 'error' : 'warning'}
                title={currentProgress.message}
                subTitle={`成功 ${currentProgress.success || 0} / ${currentProgress.total || 0}`}
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
