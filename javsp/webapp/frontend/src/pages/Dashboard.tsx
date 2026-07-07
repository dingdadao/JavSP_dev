import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Tag, Typography, Progress, List, Timeline, Space, Badge } from 'antd'
import {
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  FolderOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useSocket } from '../hooks/useSocket'
import { fetchSystemInfo, fetchTasks, fetchLogs, fetchScrapeStatus } from '../api'
import dayjs from 'dayjs'

export default function Dashboard() {
  const { connected, lastProgress, lastWatcherEvent } = useSocket()
  const [sysInfo, setSysInfo] = useState<any>(null)
  const [recentTasks, setRecentTasks] = useState<any[]>([])
  const [recentLogs, setRecentLogs] = useState<any[]>([])
  const [currentStatus, setCurrentStatus] = useState<any>(null)

  useEffect(() => {
    loadData()
    // 主动轮询当前任务状态，避免 Socket 事件丢失导致首页不刷新
    const timer = setInterval(() => {
      loadCurrentStatus()
    }, 2000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (lastProgress) loadData()
  }, [lastProgress])

  const loadCurrentStatus = async () => {
    try {
      const res = await fetchScrapeStatus()
      if (res.code === 0 && res.data) {
        setCurrentStatus(res.data)
      }
    } catch (e) {
      // 无任务时接口可能返回非 0，忽略即可
    }
  }

  const loadData = async () => {
    try {
      const [sys, tasks, logs] = await Promise.all([
        fetchSystemInfo(),
        fetchTasks(5),
        fetchLogs(10),
      ])
      setSysInfo(sys.data)
      setRecentTasks(tasks.data)
      setRecentLogs(logs.data)
    } catch (e) {
      console.error('加载数据失败', e)
    }
  }

  // 优先显示进行中的状态：Socket 或轮询任一处于 running 都优先展示
  const progress = lastProgress?.status === 'running'
    ? lastProgress
    : currentStatus?.status === 'running'
      ? currentStatus
      : lastProgress || currentStatus
  const isRunning = progress?.status === 'running'

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        仪表盘
      </Typography.Title>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="总任务数"
              value={sysInfo?.total_tasks || 0}
              prefix={<PlayCircleOutlined />}
              valueStyle={{ color: '#6366f1' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="成功任务"
              value={sysInfo?.success_tasks || 0}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#22c55e' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="失败任务"
              value={sysInfo?.failed_tasks || 0}
              prefix={<CloseCircleOutlined />}
              valueStyle={{ color: '#ef4444' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="监控路径"
              value={sysInfo?.watch_paths_count || 0}
              prefix={<FolderOutlined />}
              valueStyle={{ color: '#f59e0b' }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <Card
            title={<Space><ThunderboltOutlined />实时刮削进度</Space>}
            extra={
              <Badge
                status={connected ? 'success' : 'error'}
                text={connected ? '已连接' : '未连接'}
              />
            }
          >
            {isRunning && progress ? (
              <div>
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <div>
                    <Typography.Text type="secondary">
                      {progress.message}
                    </Typography.Text>
                    {progress.current && (
                      <Tag color="processing" style={{ marginLeft: 8 }}>
                        <VideoCameraOutlined /> {progress.current}
                      </Tag>
                    )}
                  </div>
                  <Progress
                    percent={progress.total ? Math.round((progress.completed! / progress.total) * 100) : 0}
                    status="active"
                    strokeColor={{ from: '#6366f1', to: '#22c55e' }}
                    format={() => `${progress.completed || 0} / ${progress.total || 0}`}
                  />
                  <Space>
                    <Tag color="success">成功: {progress.success || 0}</Tag>
                    <Tag color="error">失败: {progress.failed || 0}</Tag>
                  </Space>
                </Space>
              </div>
            ) : progress && progress.status !== 'running' ? (
              <div>
                <Typography.Text type="success" style={{ fontSize: 16 }}>
                  {progress.message}
                </Typography.Text>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0' }}>
                <PlayCircleOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />
                <div style={{ marginTop: 16, color: 'rgba(255,255,255,0.35)' }}>
                  当前无运行任务，前往 <Typography.Link href="/scrape">开始刮削</Typography.Link>
                </div>
              </div>
            )}

            {lastWatcherEvent && (
              <div style={{ marginTop: 16, padding: '8px 12px', background: 'rgba(245,158,11,0.1)', borderRadius: 8 }}>
                <Typography.Text type="warning">
                  <FolderOutlined /> {lastWatcherEvent.message}
                </Typography.Text>
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="最近任务" style={{ height: '100%' }}>
            <List
              size="small"
              dataSource={recentTasks}
              locale={{ emptyText: '暂无任务记录' }}
              renderItem={(task: any) => (
                <List.Item>
                  <List.Item.Meta
                    title={
                      <Space>
                        <Tag color={
                          task.status === 'completed' ? 'success' :
                          task.status === 'running' ? 'processing' :
                          task.status === 'partial' ? 'warning' : 'error'
                        }>
                          {task.status === 'completed' ? '完成' :
                           task.status === 'running' ? '运行中' :
                           task.status === 'partial' ? '部分完成' : '失败'}
                        </Tag>
                        <Typography.Text copyable={{ text: task.id }}>
                          {task.id?.slice(0, 8)}
                        </Typography.Text>
                      </Space>
                    }
                    description={
                      <Space size="small">
                        <span>{task.completed}/{task.total} 部</span>
                        <span style={{ color: 'rgba(255,255,255,0.35)' }}>
                          {dayjs(task.created_at).format('MM-DD HH:mm')}
                        </span>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="操作日志">
            <Timeline
              items={recentLogs.map((log: any) => ({
                color: log.level === 'ERROR' ? 'red' : log.level === 'WARNING' ? 'orange' : 'blue',
                children: (
                  <Space>
                    <Tag color={log.level === 'ERROR' ? 'error' : log.level === 'WARNING' ? 'warning' : 'processing'}>
                      {log.level}
                    </Tag>
                    <span>{log.message}</span>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {dayjs(log.created_at).format('HH:mm:ss')}
                    </Typography.Text>
                  </Space>
                ),
              }))}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
