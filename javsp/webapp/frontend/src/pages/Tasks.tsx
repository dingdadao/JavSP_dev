import { useEffect, useState } from 'react'
import {
  Card, Table, Tag, Button, Space, Typography, Modal, Descriptions,
  App, Progress, Image
} from 'antd'
import {
  ReloadOutlined, EyeOutlined, PauseCircleOutlined
} from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { fetchTasks, fetchTask, stopScrapeTask } from '../api'
import { useSocket } from '../hooks/useSocket'
import dayjs from 'dayjs'

export default function Tasks() {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [stoppingTaskIds, setStoppingTaskIds] = useState<Set<string>>(new Set())
  const { message } = App.useApp()
  const { lastProgress, connected } = useSocket()

  useEffect(() => { loadTasks() }, [])

  // 当 Socket 收到刮削进度时，立即刷新列表和详情
  useEffect(() => {
    if (lastProgress?.task_id) {
      // 本地先更新该任务状态，避免停止按钮继续显示
      setTasks((prev: any[]) => prev.map(t => t.id === lastProgress.task_id ? { ...t, ...lastProgress } : t))
      // 如果详情 Modal 打开的是当前任务，也同步更新
      setDetail((prev: any) => prev && prev.id === lastProgress.task_id ? { ...prev, ...lastProgress } : prev)
      // 再向后端拉取一次完整数据（包含 items 等）
      loadTasks()
      if (detailVisible && detail?.id === lastProgress.task_id) {
        refreshDetail(lastProgress.task_id)
      }
    }
  }, [lastProgress])

  const loadTasks = async () => {
    setLoading(true)
    try {
      const { data } = await fetchTasks(100)
      setTasks(data || [])
    } catch (e) {
      message.error('加载任务列表失败')
    } finally {
      setLoading(false)
    }
  }

  const refreshDetail = async (taskId: string) => {
    try {
      const { data } = await fetchTask(taskId)
      setDetail(data)
    } catch (e) {
      // 静默失败，不影响主流程
    }
  }

  const showDetail = async (taskId: string) => {
    try {
      const { data } = await fetchTask(taskId)
      setDetail(data)
      setDetailVisible(true)
    } catch (e) {
      message.error('加载任务详情失败')
    }
  }

  const handleStop = async (taskId: string) => {
    setStoppingTaskIds(prev => new Set(prev).add(taskId))
    try {
      const res = await stopScrapeTask()
      if (res.code === 0) {
        message.success(res.message)
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '停止任务失败')
    } finally {
      // 3 秒后清除本地 stopping 标记（或收到进度时清除）
      setTimeout(() => {
        setStoppingTaskIds(prev => {
          const next = new Set(prev)
          next.delete(taskId)
          return next
        })
      }, 5000)
    }
  }

  const runningTask = tasks.find(t => t.status === 'running')

  const statusMap: Record<string, { color: string; text: string }> = {
    completed: { color: 'success', text: '完成' },
    running: { color: 'processing', text: '运行中' },
    partial: { color: 'warning', text: '部分完成' },
    failed: { color: 'error', text: '失败' },
    pending: { color: 'default', text: '等待中' },
    error: { color: 'error', text: '异常' },
    stopped: { color: 'warning', text: '已停止' },
  }

  const columns = [
    {
      title: '任务ID',
      dataIndex: 'id',
      width: 120,
      render: (id: string) => (
        <Typography.Text copyable={{ text: id }} style={{ fontSize: 12 }}>
          {id.slice(0, 8)}...
        </Typography.Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => {
        const s = statusMap[status] || { color: 'default', text: status }
        return <Tag color={s.color}>{s.text}</Tag>
      },
    },
    {
      title: '类型',
      dataIndex: 'task_type',
      width: 90,
      render: (t: string) => <Tag>{t === 'manual' ? '手动' : '自动'}</Tag>,
    },
    {
      title: '源路径',
      dataIndex: 'source_path',
      ellipsis: true,
    },
    {
      title: '进度',
      key: 'progress',
      width: 160,
      render: (_: any, r: any) => (
        r.total ? (
          <Progress
            percent={Math.round(((r.completed || 0) / r.total) * 100)}
            size="small"
            status={r.status === 'running' ? 'active' : 'normal'}
            format={() => `${r.completed}/${r.total}`}
          />
        ) : `${r.completed || 0}/${r.total || 0}`
      ),
    },
    {
      title: '成功/失败',
      key: 'result',
      width: 120,
      render: (_: any, r: any) => (
        <Space>
          <Tag color="success">{r.success_count}</Tag>
          <Tag color="error">{r.failed_count}</Tag>
        </Space>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 160,
      render: (_: any, record: any) => (
        <Space>
          <Button type="link" icon={<EyeOutlined />} onClick={() => showDetail(record.id)}>
            详情
          </Button>
          {(record.status === 'running' || stoppingTaskIds.has(record.id)) && (
            <Button
              type="link"
              danger
              icon={<PauseCircleOutlined />}
              loading={stoppingTaskIds.has(record.id)}
              disabled={stoppingTaskIds.has(record.id)}
              onClick={() => handleStop(record.id)}
            >
              {stoppingTaskIds.has(record.id) ? '停止中' : '停止'}
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        任务列表
        <Tag color={connected ? 'success' : 'error'} style={{ marginLeft: 12 }}>
          {connected ? '实时连接正常' : '实时连接断开'}
        </Tag>
      </Typography.Title>
      <Card
        variant="borderless"
        extra={
          <Space>
            {runningTask && (
              <Button
                danger
                icon={<PauseCircleOutlined />}
                loading={stoppingTaskIds.has(runningTask.id)}
                disabled={stoppingTaskIds.has(runningTask.id)}
                onClick={() => handleStop(runningTask.id)}
              >
                {stoppingTaskIds.has(runningTask.id) ? '停止中' : '停止当前任务'}
              </Button>
            )}
            <Button icon={<ReloadOutlined />} onClick={loadTasks}>刷新</Button>
          </Space>
        }
      >
        <Table
          dataSource={tasks}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="middle"
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title="任务详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={900}
      >
        {detail && (
          <div>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="任务ID" span={2}>
                {detail.id}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={
                  detail.status === 'completed' ? 'success' :
                  detail.status === 'running' ? 'processing' :
                  detail.status === 'stopped' ? 'warning' : 'error'
                }>
                  {statusMap[detail.status]?.text || detail.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="类型">{detail.task_type === 'manual' ? '手动' : '自动'}</Descriptions.Item>
              <Descriptions.Item label="源路径" span={2}>{detail.source_path}</Descriptions.Item>
              <Descriptions.Item label="输出路径" span={2}>{detail.dest_path}</Descriptions.Item>
              <Descriptions.Item label="进度" span={2}>
                {detail.total ? (
                  <Progress
                    percent={Math.round(((detail.completed || 0) / detail.total) * 100)}
                    status={detail.status === 'running' ? 'active' : 'normal'}
                    format={() => `${detail.completed}/${detail.total}`}
                  />
                ) : `${detail.completed}/${detail.total}`}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">{dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
            </Descriptions>

            {detail.items && detail.items.length > 0 && (
              <>
                <Typography.Title level={5} style={{ marginTop: 16 }}>影片详情</Typography.Title>
                <Table
                  dataSource={detail.items}
                  rowKey="id"
                  size="small"
                  pagination={false}
                  scroll={{ y: 400 }}
                  columns={[
                    {
                      title: '封面',
                      dataIndex: 'cover',
                      width: 90,
                      render: (cover: string) => cover ? (
                        <Image
                          src={`/api/cover?path=${encodeURIComponent(cover)}`}
                          alt="封面"
                          style={{ width: 70, height: 100, objectFit: 'cover', borderRadius: 4 }}
                          preview={{ src: `/api/cover?path=${encodeURIComponent(cover)}` }}
                          fallback="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
                        />
                      ) : (
                        <div style={{ width: 70, height: 100, background: '#2a2a3c', borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
                          无封面
                        </div>
                      ),
                    },
                    {
                      title: '番号', dataIndex: 'dvdid', width: 140,
                      render: (id: string, record: any) => (
                        record.dest_path ? (
                          <Link to={`/movie?dvdid=${encodeURIComponent(id)}&path=${encodeURIComponent(record.dest_path)}`}>
                            {id}
                          </Link>
                        ) : id
                      ),
                    },
                    { title: '标题', dataIndex: 'title', ellipsis: true },
                    {
                      title: '状态', dataIndex: 'status', width: 80,
                      render: (s: string) => (
                        <Tag color={s === 'success' ? 'success' : s === 'failed' ? 'error' : 'default'}>
                          {s === 'success' ? '成功' : s === 'failed' ? '失败' : '等待'}
                        </Tag>
                      ),
                    },
                    { title: '结果', dataIndex: 'message', ellipsis: true },
                    { title: '原因', dataIndex: 'reason', ellipsis: true },
                    {
                      title: '输出路径',
                      dataIndex: 'dest_path',
                      ellipsis: true,
                      render: (p: string) => p || '-',
                    },
                  ]}
                />
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
