import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Card, Button, Space, Typography, Table, Tag, Input,
  Modal, App, Empty, Progress, Tooltip, Popconfirm,
} from 'antd'
import {
  FolderOutlined, BugOutlined,
  DeleteOutlined, ReloadOutlined,
  PlayCircleOutlined, StopOutlined,
} from '@ant-design/icons'
import {
  fetchCheckerIntegrity, fetchCheckerDefaultPath,
  resumeCheckerIntegrity, stopCheckerIntegrity,
  fetchCheckerIntegrityTasks, fetchCheckerIntegrityTaskDetail,
  deleteCheckerIntegrityVideos, deleteCheckerIntegrityTask,
} from '../api'
import { useSocket } from '../hooks/useSocket'
import dayjs from 'dayjs'

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  running: { color: 'processing', label: '运行中' },
  completed: { color: 'success', label: '已完成' },
  stopped: { color: 'warning', label: '已停止' },
  failed: { color: 'error', label: '失败' },
}

const ITEM_STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待检查' },
  ok: { color: 'success', label: '正常' },
  error: { color: 'error', label: '损坏' },
}

export default function IntegrityCheck() {
  const { message } = App.useApp()
  const { lastIntegrityProgress } = useSocket()

  const [scanPath, setScanPath] = useState('')
  const [defaultPath, setDefaultPath] = useState('')
  const [starting, setStarting] = useState(false)
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null)
  const [currentFile, setCurrentFile] = useState('')

  // 任务列表
  const [tasks, setTasks] = useState<any[]>([])
  const [tasksLoading, setTasksLoading] = useState(false)

  // 当前查看的任务详情
  const [selectedTask, setSelectedTask] = useState<any>(null)
  const [taskItems, setTaskItems] = useState<any[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<number[]>([])
  const [deleting, setDeleting] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 加载默认路径
  useEffect(() => {
    fetchCheckerDefaultPath().then(({ data }: any) => {
      const p = data?.default_path || ''
      if (p) {
        setDefaultPath(p)
        setScanPath(p)
      }
    }).catch(() => {})
    loadTasks()
  }, [])

  // 监听实时进度
  useEffect(() => {
    if (!lastIntegrityProgress) return
    const p = lastIntegrityProgress
    if (p.task_id !== runningTaskId) return

    if (p.status === 'running') {
      setCurrentFile(p.current || '')
    } else if (p.status === 'completed') {
      setRunningTaskId(null)
      setCurrentFile('')
      message.success(`完整性检查完成: 正常 ${p.ok_count ?? '?'} 个, 损坏 ${p.error_count ?? '?'} 个`)
      loadTasks()
      if (selectedTask?.id === p.task_id) {
        loadTaskDetail(p.task_id)
      }
    } else if (p.status === 'stopped') {
      setRunningTaskId(null)
      setCurrentFile('')
      message.info('完整性检查已停止')
      loadTasks()
      if (selectedTask?.id === p.task_id) {
        loadTaskDetail(p.task_id)
      }
    } else if (p.status === 'failed') {
      setRunningTaskId(null)
      setCurrentFile('')
      message.error(p.message || '完整性检查失败')
      loadTasks()
    }
  }, [lastIntegrityProgress])

  // 自动刷新运行中的任务详情
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (runningTaskId && selectedTask?.id === runningTaskId) {
      pollRef.current = setInterval(() => {
        loadTaskDetail(runningTaskId)
      }, 3000)
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [runningTaskId, selectedTask?.id])

  const loadTasks = useCallback(async () => {
    setTasksLoading(true)
    try {
      const res: any = await fetchCheckerIntegrityTasks()
      if (res.code === 0) {
        setTasks(res.data || [])
        // 恢复运行中的任务状态
        const running = (res.data || []).find((t: any) => t.status === 'running')
        if (running && !runningTaskId) {
          setRunningTaskId(running.id)
        }
      }
    } catch { /* ignore */ }
    finally { setTasksLoading(false) }
  }, [runningTaskId])

  const loadTaskDetail = useCallback(async (taskId: string) => {
    setDetailLoading(true)
    try {
      const res: any = await fetchCheckerIntegrityTaskDetail(taskId)
      if (res.code === 0) {
        setSelectedTask(res.data)
        setTaskItems(res.data.items || [])
      }
    } catch { /* ignore */ }
    finally { setDetailLoading(false) }
  }, [])

  const handleStart = useCallback(async () => {
    if (!scanPath.trim()) {
      message.warning('请输入扫描路径')
      return
    }
    setStarting(true)
    try {
      const res: any = await fetchCheckerIntegrity({ path: scanPath.trim() })
      if (res.code === 0) {
        setRunningTaskId(res.data.task_id)
        setCurrentFile('')
        setSelectedRowKeys([])
        message.info(`完整性检查已启动，共 ${res.data.total} 个文件`)
        loadTasks()
        // 自动查看新任务
        setTimeout(() => loadTaskDetail(res.data.task_id), 500)
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '启动失败')
    } finally { setStarting(false) }
  }, [scanPath, message, loadTasks, loadTaskDetail])

  const handleStop = useCallback(async (taskId: string) => {
    try {
      await stopCheckerIntegrity(taskId)
      message.info('停止信号已发送')
    } catch { message.error('停止失败') }
  }, [message])

  const handleResume = useCallback(async (taskId: string) => {
    try {
      const res: any = await resumeCheckerIntegrity(taskId)
      if (res.code === 0) {
        setRunningTaskId(taskId)
        message.info('完整性检查已恢复')
        loadTasks()
        loadTaskDetail(taskId)
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '恢复失败')
    }
  }, [message, loadTasks, loadTaskDetail])

  const handleDeleteTask = useCallback(async (taskId: string) => {
    try {
      await deleteCheckerIntegrityTask(taskId)
      message.success('任务已删除')
      if (selectedTask?.id === taskId) {
        setSelectedTask(null)
        setTaskItems([])
      }
      loadTasks()
    } catch { message.error('删除失败') }
  }, [message, selectedTask, loadTasks])

  const handleDeleteSelected = useCallback(async () => {
    const errorItems = taskItems.filter(
      (item: any) => item.status === 'error' && selectedRowKeys.includes(item.id)
    )
    if (errorItems.length === 0) {
      message.warning('选中项中没有损坏的视频')
      return
    }
    Modal.confirm({
      title: '确认删除',
      width: 520,
      content: (
        <div>
          <p>将删除 <b style={{ color: '#ff4d4f' }}>{errorItems.length}</b> 个损坏的视频文件：</p>
          <ul style={{ maxHeight: 200, overflow: 'auto' }}>
            {errorItems.map((item: any, i: number) => (
              <li key={i}><code>{item.video_basename}</code></li>
            ))}
          </ul>
          <p style={{ color: '#faad14', marginTop: 12 }}>
            此操作不可恢复！将同时删除文件、清理数据库记录，若目录下无其他媒体文件则一并删除目录。
          </p>
        </div>
      ),
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setDeleting(true)
        try {
          const paths = errorItems.map((item: any) => item.video_path)
          const ids = errorItems.map((item: any) => item.id)
          const res: any = await deleteCheckerIntegrityVideos(paths, ids)
          if (res.code === 0) {
            const { deleted, failed } = res.data
            if (deleted.length > 0) {
              const dirDeleted = deleted.filter((d: any) => d.dir_deleted)
              const alreadyGone = deleted.filter((d: any) => d.already_gone)
              let msg = `已删除 ${deleted.length} 个文件`
              if (alreadyGone.length > 0) msg += ` (${alreadyGone.length} 个已不存在)`
              if (dirDeleted.length > 0) msg += `，已清理 ${dirDeleted.length} 个空目录`
              message.success(msg)
              setSelectedRowKeys([])
              if (selectedTask) loadTaskDetail(selectedTask.id)
              loadTasks()
            }
            if (failed.length > 0) {
              message.error(`${failed.length} 个文件删除失败`)
            }
          } else {
            message.error(res.message)
          }
        } catch (e: any) {
          message.error(e.response?.data?.message || '删除失败')
        } finally { setDeleting(false) }
      },
    })
  }, [taskItems, selectedRowKeys, selectedTask, message, loadTasks, loadTaskDetail])

  const formatSize = (bytes: number) => {
    if (!bytes) return '-'
    let size = bytes
    for (const unit of ['B', 'KiB', 'MiB', 'GiB']) {
      if (size < 1024) return `${size.toFixed(1)} ${unit}`
      size /= 1024
    }
    return `${size.toFixed(1)} TiB`
  }

  // 任务列表表格列
  const taskColumns = [
    {
      title: '路径', dataIndex: 'scan_path', ellipsis: true,
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (status: string) => {
        const s = STATUS_MAP[status] || { color: 'default', label: status }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '进度', width: 160,
      render: (_: any, record: any) => (
        <span>{record.completed} / {record.total}</span>
      ),
    },
    {
      title: '结果', width: 150,
      render: (_: any, record: any) => (
        <Space size={4}>
          <Tag color="success">{record.ok_count}</Tag>
          {record.error_count > 0 && <Tag color="error">{record.error_count}</Tag>}
        </Space>
      ),
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 170,
      render: (t: string) => t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-',
    },
    {
      title: '操作', width: 200,
      render: (_: any, record: any) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => {
            setSelectedRowKeys([])
            loadTaskDetail(record.id)
          }}>
            查看
          </Button>
          {record.status === 'running' && (
            <Button type="link" size="small" danger onClick={() => handleStop(record.id)}>
              停止
            </Button>
          )}
          {(record.status === 'stopped' || record.status === 'failed') && (
            <Button type="link" size="small" onClick={() => handleResume(record.id)}>
              继续
            </Button>
          )}
          <Popconfirm title="确认删除此任务？" onConfirm={() => handleDeleteTask(record.id)}>
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // 详情表格列
  const itemColumns = [
    {
      title: '状态', dataIndex: 'status', width: 80, fixed: 'left' as const,
      filters: [
        { text: '待检查', value: 'pending' },
        { text: '正常', value: 'ok' },
        { text: '损坏', value: 'error' },
      ],
      onFilter: (value: any, record: any) => record.status === value,
      render: (status: string) => {
        const s = ITEM_STATUS_MAP[status] || { color: 'default', label: status }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '文件名', dataIndex: 'video_basename', ellipsis: true,
      sorter: (a: any, b: any) => a.video_basename.localeCompare(b.video_basename),
    },
    {
      title: '大小', dataIndex: 'file_size', width: 100,
      sorter: (a: any, b: any) => (a.file_size || 0) - (b.file_size || 0),
      render: (size: number) => formatSize(size),
    },
    {
      title: '错误信息', dataIndex: 'errors', ellipsis: true,
      render: (errors: string | null) => errors
        ? <Tooltip title={errors}><Typography.Text type="danger" ellipsis>{errors}</Typography.Text></Tooltip>
        : <Typography.Text type="secondary">-</Typography.Text>,
    },
    {
      title: '检查时间', dataIndex: 'checked_at', width: 170,
      render: (t: string) => t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-',
    },
  ]

  const errorCount = taskItems.filter((i: any) => i.status === 'error').length
  const isRunning = selectedTask?.status === 'running' || !!runningTaskId

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <BugOutlined /> 视频完整性检查
      </Typography.Title>

      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* 启动区域 */}
        <Card variant="borderless">
          <Space.Compact style={{ width: '100%' }}>
            <Input
              prefix={<FolderOutlined />}
              placeholder={defaultPath || '输入要检查的目录路径...'}
              value={scanPath}
              onChange={(e) => setScanPath(e.target.value)}
              onPressEnter={handleStart}
              style={{ fontFamily: 'monospace' }}
              suffix={
                defaultPath && scanPath !== defaultPath ? (
                  <Button type="link" size="small" onClick={() => setScanPath(defaultPath)}>恢复默认</Button>
                ) : undefined
              }
            />
            <Button
              type="primary"
              icon={<BugOutlined />}
              onClick={handleStart}
              loading={starting}
            >
              开始检查
            </Button>
            {isRunning && (
              <Button
                danger
                icon={<StopOutlined />}
                onClick={() => runningTaskId && handleStop(runningTaskId)}
              >
                停止
              </Button>
            )}
          </Space.Compact>
        </Card>

        {/* 运行状态 */}
        {isRunning && (
          <Card variant="borderless" size="small" title={<span><BugOutlined /> 正在检查...</span>}>
            <Space direction="vertical" style={{ width: '100%' }}>
              {currentFile && (
                <Typography.Text type="secondary" ellipsis style={{ maxWidth: '100%' }}>
                  当前: {currentFile}
                </Typography.Text>
              )}
              {selectedTask && (
                <>
                  <Progress
                    status="active"
                    percent={selectedTask.total > 0 ? Math.round((selectedTask.completed / selectedTask.total) * 100) : 0}
                    showInfo
                  />
                  <Space size={8}>
                    <Tag color="default">待检查: {selectedTask.total - selectedTask.completed}</Tag>
                    <Tag color="success">正常: {selectedTask.ok_count}</Tag>
                    {selectedTask.error_count > 0 && <Tag color="error">损坏: {selectedTask.error_count}</Tag>}
                  </Space>
                </>
              )}
            </Space>
          </Card>
        )}

        {/* 任务历史 */}
        <Card
          variant="borderless"
          title="检查任务"
          extra={<Button icon={<ReloadOutlined />} onClick={loadTasks} loading={tasksLoading}>刷新</Button>}
        >
          <Table
            dataSource={tasks}
            columns={taskColumns}
            rowKey="id"
            size="small"
            loading={tasksLoading}
            pagination={false}
            locale={{ emptyText: <Empty description="暂无检查任务" /> }}
            onRow={(record) => ({
              onClick: () => {
                setSelectedRowKeys([])
                loadTaskDetail(record.id)
              },
              style: { cursor: 'pointer', background: selectedTask?.id === record.id ? 'rgba(99,102,241,0.06)' : undefined },
            })}
          />
        </Card>

        {/* 任务详情 */}
        {selectedTask && (
          <Card
            variant="borderless"
            title={
              <Space>
                <span>检查详情</span>
                <Tag color="blue">{selectedTask.scan_path}</Tag>
                {(() => {
                  const s = STATUS_MAP[selectedTask.status] || { color: 'default', label: selectedTask.status }
                  return <Tag color={s.color}>{s.label}</Tag>
                })()}
                <Tag color="success">{selectedTask.ok_count} 正常</Tag>
                {selectedTask.error_count > 0 && <Tag color="error">{selectedTask.error_count} 损坏</Tag>}
                <Tag>待检查: {selectedTask.total - selectedTask.completed}</Tag>
              </Space>
            }
            extra={
              <Space>
                {(selectedTask.status === 'stopped' || selectedTask.status === 'failed') && (
                  <Button icon={<PlayCircleOutlined />} onClick={() => handleResume(selectedTask.id)}>
                    继续检查
                  </Button>
                )}
                {selectedTask.status === 'running' && (
                  <Button danger icon={<StopOutlined />} onClick={() => handleStop(selectedTask.id)}>
                    停止
                  </Button>
                )}
                {errorCount > 0 && (
                  <Button
                    onClick={() => {
                      const errorIds = taskItems.filter((i: any) => i.status === 'error').map((i: any) => i.id)
                      setSelectedRowKeys(errorIds)
                    }}
                  >
                    全选损坏 ({errorCount})
                  </Button>
                )}
                {selectedRowKeys.length > 0 && errorCount > 0 && (
                  <Button
                    type="primary"
                    danger
                    icon={<DeleteOutlined />}
                    loading={deleting}
                    onClick={handleDeleteSelected}
                  >
                    删除选中损坏文件 ({selectedRowKeys.length})
                  </Button>
                )}
              </Space>
            }
          >
            <Table
              dataSource={taskItems}
              columns={itemColumns}
              rowKey="id"
              size="small"
              loading={detailLoading}
              scroll={{ x: 900 }}
              rowSelection={{
                selectedRowKeys,
                onChange: (keys) => setSelectedRowKeys(keys as number[]),
                getCheckboxProps: (record: any) => ({
                  disabled: record.status !== 'error',
                }),
              }}
              pagination={{
                defaultPageSize: 50,
                showSizeChanger: true,
                pageSizeOptions: [20, 50, 200, 500],
                showTotal: (t) => `共 ${t} 项`,
              }}
              locale={{ emptyText: <Empty description="暂无检查项" /> }}
            />
          </Card>
        )}
      </Space>
    </div>
  )
}
