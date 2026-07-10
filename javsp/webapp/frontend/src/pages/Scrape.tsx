import { useEffect, useState } from 'react'
import {
  Card, Button, Space, Switch, Typography, Form, Input,
  Alert, Progress, Tag, Steps, Result, Row, Col, Select, App,
  Collapse, List, Tooltip,
} from 'antd'
import {
  PlayCircleOutlined, ScanOutlined, CheckCircleOutlined,
  LoadingOutlined, RocketOutlined, DatabaseOutlined,
  PauseCircleOutlined, SaveOutlined, FolderOpenOutlined,
  WarningOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useSocket } from '../hooks/useSocket'
import { createScrapeTask, fetchConfig, fetchScrapeStatus, stopScrapeTask, fetchMediaLibraries, updateConfig } from '../api'

export default function Scrape() {
  const { lastProgress, connected } = useSocket()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)
  const [saving, setSaving] = useState(false)
  const [libraries, setLibraries] = useState<any[]>([])
  const [defaultLib, setDefaultLib] = useState<any>(null)
  const { message } = App.useApp()

  const currentProgress = lastProgress?.status ? lastProgress : null

  useEffect(() => {
    loadConfig()
    checkRunningTask()
  }, [])

  // 轮询兜底：如果 stopping 为 true 但超过 3 秒没收到终态，主动拉取状态
  useEffect(() => {
    if (!stopping) return
    const timer = setInterval(async () => {
      try {
        const res = await fetchScrapeStatus()
        if (res.code === 0 && res.data) {
          const s = res.data.status
          if (s !== 'running') {
            setStopping(false)
            clearInterval(timer)
          }
        }
      } catch { /* ignore */ }
    }, 2000)
    return () => clearInterval(timer)
  }, [stopping])

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
      const scanner = data?.scanner || {}
      const summarizer = data?.summarizer || {}
      const translator = data?.translator || {}
      form.setFieldsValue({
        source: scanner.input_directory || '',
        dest: summarizer.output_folder_pattern || '',
        translate: translator.translate_title ?? true,
        move_files: summarizer.move_files ?? true,
      })

      // 加载媒体库列表
      const libsRes = await fetchMediaLibraries()
      const libList = libsRes.data || []
      setLibraries(libList)
      const def = libList.find((l: any) => l.is_default) || libList[0] || null
      setDefaultLib(def)
      if (def) {
        form.setFieldsValue({ library: def.id })
      }
    } catch (e) {
      console.error(e)
    }
  }

  const handleSave = async (values: any) => {
    setSaving(true)
    try {
      await updateConfig([
        { group: 'scanner', key: 'input_directory', value: values.source || '' },
        { group: 'summarizer', key: 'output_folder_pattern', value: values.dest || '' },
        { group: 'translator', key: 'translate_title', value: values.translate ?? true },
        { group: 'translator', key: 'translate_plot', value: values.translate ?? true },
        { group: 'summarizer', key: 'move_files', value: values.move_files ?? true },
      ])
      message.success('配置已保存')
    } catch (e: any) {
      message.error(e.response?.data?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleSubmit = async (values: any) => {
    setLoading(true)
    try {
      const selectedLib = libraries.find(l => l.id === values.library)
      const params: any = {
        translate: values.translate,
        move_files: values.move_files,
      }

      if (selectedLib) {
        params.source = selectedLib.path
        params.dest = selectedLib.path
      } else {
        params.source = values.source
        params.dest = values.dest
      }

      const res = await createScrapeTask(params)
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
  const isDone = taskId && currentProgress && ['completed', 'failed', 'error', 'stopped'].includes(currentProgress.status)

  useEffect(() => {
    if (isDone) {
      setStopping(false)
    }
  }, [isDone])

  const currentStep = isRunning ? 1 : isDone ? 2 : 0

  const libOptions = libraries.map(lib => ({
    label: `${lib.name} (${lib.path})`,
    value: lib.id,
  }))

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
          <Card title="刮削设置" variant="borderless"
            extra={
              <Button
                icon={<SaveOutlined />}
                type="default"
                loading={saving}
                onClick={() => handleSave(form.getFieldsValue())}
                disabled={isRunning}
              >
                保存
              </Button>
            }
          >
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
              initialValues={{ translate: true, move_files: true }}
            >
              {libraries.length > 0 && (
                <Form.Item
                  label={<Space><DatabaseOutlined />选择媒体库</Space>}
                  name="library"
                  extra="选择媒体库后将使用库路径，忽略下方手动路径"
                >
                  <Select
                    options={libOptions}
                    placeholder="选择媒体库（可选）"
                    showSearch
                    optionFilterProp="label"
                    allowClear
                  />
                </Form.Item>
              )}

              <Form.Item
                label={<Space><FolderOpenOutlined />源文件夹路径</Space>}
                name="source"
                rules={[{ required: true, message: '请输入源文件夹路径' }]}
              >
                <Input placeholder="/path/to/movies" />
              </Form.Item>

              <Form.Item
                label={<Space><FolderOpenOutlined />输出文件夹路径</Space>}
                name="dest"
                rules={[{ required: true, message: '请输入输出文件夹路径' }]}
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
                  <Col span={6}>
                    <Card size="small" variant="borderless">
                      <Typography.Text type="secondary">总计</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold' }}>{currentProgress.total || 0}</div>
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card size="small" variant="borderless">
                      <Typography.Text type="secondary">成功</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: '#22c55e' }}>{currentProgress.success || 0}</div>
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card size="small" variant="borderless">
                      <Typography.Text type="secondary">失败</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: '#ef4444' }}>{currentProgress.failed || 0}</div>
                    </Card>
                  </Col>
                  <Col span={6}>
                    <Card size="small" variant="borderless">
                      <Typography.Text type="secondary">未识别</Typography.Text>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: '#faad14' }}>{currentProgress.unrecognized || 0}</div>
                    </Card>
                  </Col>
                </Row>
              </Space>
            )}

            {isDone && currentProgress && (
              <ScrapeResult progress={currentProgress} />
            )}

            {!isRunning && !isDone && (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'rgba(255,255,255,0.25)' }}>
                <PlayCircleOutlined style={{ fontSize: 64 }} />
                <div style={{ marginTop: 16, fontSize: 16 }}>
                  配置路径后点击「开始刮削」启动任务
                </div>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

function ScrapeResult({ progress }: { progress: any }) {
  const successCount = progress.success || 0
  const failedCount = progress.failed || 0
  const unrecognizedCount = progress.unrecognized || 0
  const totalCount = progress.total || 0

  const statusColor = progress.status === 'completed' ? 'success'
    : progress.status === 'stopped' ? 'warning'
    : 'error'

  const statusText = progress.status === 'completed' ? '刮削完成'
    : progress.status === 'stopped' ? '任务已中断'
    : '任务失败（有失败项）'

  // 计算跳过数（总数 - 成功 - 失败，负数则置0）
  const skippedCount = Math.max(0, totalCount - successCount - failedCount)

  const resultsSuccess = progress.results_success || []
  const resultsFailed = progress.results_failed || []
  const resultsUnrecognized = progress.results_unrecognized || []

  const collapseItems = []

  if (failedCount > 0) {
    collapseItems.push({
      key: 'failed',
      label: (
        <Space>
          <ExclamationCircleOutlined style={{ color: '#ef4444' }} />
          <span>失败 ({failedCount})</span>
        </Space>
      ),
      children: (
        <List
          size="small"
          dataSource={resultsFailed}
          renderItem={(item: any) => (
            <List.Item style={{ padding: '4px 0' }}>
              <Tooltip title={item.source}>
                <Typography.Text code>{item.dvdid}</Typography.Text>
              </Tooltip>
              <Typography.Text type="danger" style={{ marginLeft: 8, fontSize: 12 }}>
                {item.message}
              </Typography.Text>
            </List.Item>
          )}
        />
      ),
    })
  }

  if (unrecognizedCount > 0) {
    collapseItems.push({
      key: 'unrecognized',
      label: (
        <Space>
          <WarningOutlined style={{ color: '#faad14' }} />
          <span>未识别番号 ({unrecognizedCount})</span>
        </Space>
      ),
      children: (
        <List
          size="small"
          dataSource={resultsUnrecognized}
          renderItem={(path: string) => (
            <List.Item style={{ padding: '2px 0' }}>
              <Tooltip title={path}>
                <Typography.Text type="warning" style={{ fontSize: 12, wordBreak: 'break-all' }}>
                  {path.split('/').pop() || path}
                </Typography.Text>
              </Tooltip>
            </List.Item>
          )}
        />
      ),
    })
  }

  if (successCount > 0) {
    collapseItems.push({
      key: 'success',
      label: (
        <Space>
          <CheckCircleOutlined style={{ color: '#22c55e' }} />
          <span>成功 ({successCount})</span>
        </Space>
      ),
      children: (
        <List
          size="small"
          dataSource={resultsSuccess}
          renderItem={(item: any) => (
            <List.Item style={{ padding: '4px 0' }}>
              <Tooltip title={item.source}>
                <Typography.Text code>{item.dvdid}</Typography.Text>
              </Tooltip>
              {item.dest_path && (
                <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                  {item.dest_path.split('/').pop()}
                </Typography.Text>
              )}
            </List.Item>
          )}
        />
      ),
    })
  }

  return (
    <div>
      <Result
        status={statusColor}
        title={statusText}
        subTitle={progress.message}
      />
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small" variant="borderless">
            <Typography.Text type="secondary">总计</Typography.Text>
            <div style={{ fontSize: 20, fontWeight: 'bold' }}>{totalCount}</div>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" variant="borderless">
            <Typography.Text type="secondary">成功</Typography.Text>
            <div style={{ fontSize: 20, fontWeight: 'bold', color: '#22c55e' }}>{successCount}</div>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" variant="borderless">
            <Typography.Text type="secondary">失败</Typography.Text>
            <div style={{ fontSize: 20, fontWeight: 'bold', color: '#ef4444' }}>{failedCount}</div>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" variant="borderless">
            <Typography.Text type="secondary">未识别番号</Typography.Text>
            <div style={{ fontSize: 20, fontWeight: 'bold', color: '#faad14' }}>{unrecognizedCount}</div>
          </Card>
        </Col>
      </Row>
      {collapseItems.length > 0 && (
        <Collapse
          items={collapseItems}
          defaultActiveKey={['failed', 'unrecognized']}
          size="small"
        />
      )}
    </div>
  )
}
