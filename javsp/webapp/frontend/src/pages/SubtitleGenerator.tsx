import { useState, useCallback, useEffect, useMemo } from 'react'
import {
  Card, Button, Space, Typography, Table, Tag, Input,
  Modal, App, Empty, Alert, Tooltip, Popconfirm, Tabs, Progress,
} from 'antd'
import {
  FolderOutlined, SoundOutlined,
  DeleteOutlined, ReloadOutlined,
  SearchOutlined, StopOutlined,
  FileTextOutlined, WarningOutlined,
} from '@ant-design/icons'
import {
  fetchSubtitlePlatform, fetchSubtitleTasks, fetchSubtitleTaskDetail,
  scanSubtitleMedia, fetchSubtitleScanResults, startSubtitleTask, stopSubtitleTask,
  generateSubtitle, generateSubtitleForVideo, deleteSubtitleTask, regenerateSubtitle,
  deleteSubtitleAudio, fetchConfig,
} from '../api'
import { useSocket } from '../hooks/useSocket'

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  running: { color: 'processing', label: '进行中' },
  audio_done: { color: 'success', label: '音频完成' },
  subtitle_running: { color: 'processing', label: '字幕生成中' },
  completed: { color: 'success', label: '已完成' },
  stopped: { color: 'warning', label: '已停止' },
  failed: { color: 'error', label: '失败' },
}

const AUDIO_STATUS: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待提取' },
  processing: { color: 'processing', label: '提取中' },
  done: { color: 'success', label: '已完成' },
  error: { color: 'error', label: '失败' },
}

const SUBTITLE_STATUS: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待生成' },
  processing: { color: 'processing', label: '生成中' },
  done: { color: 'success', label: '已完成' },
  error: { color: 'error', label: '失败' },
}

export default function SubtitleGenerator() {
  const { message } = App.useApp()
  const { lastSubtitleProgress } = useSocket()

  // 平台状态
  const [platform, setPlatform] = useState<any>(null)
  const [scanPath, setScanPath] = useState('')
  const [defaultPath, setDefaultPath] = useState('')
  const [starting, setStarting] = useState(false)
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null)

  // 配置
  const [subtitleConfig, setSubtitleConfig] = useState<any>({})

  // 扫描结果
  const [scannedFiles, setScannedFiles] = useState<any[]>([])
  const [scanning, setScanning] = useState(false)
  const [selectedFileKeys, setSelectedFileKeys] = useState<string[]>([])

  // 任务列表
  const [tasks, setTasks] = useState<any[]>([])
  const [tasksLoading, setTasksLoading] = useState(false)

  // 当前查看的任务详情
  const [selectedTask, setSelectedTask] = useState<any>(null)
  const [taskItems, setTaskItems] = useState<any[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<number[]>([])

  // Tab
  const [activeTab, setActiveTab] = useState('scan')

  // 加载平台状态
  useEffect(() => {
    fetchSubtitlePlatform().then((res: any) => {
      if (res.code === 0) setPlatform(res.data)
    }).catch(() => {})
  }, [])

  // 加载默认路径：优先使用 subtitle.scan_path，为空则回退到 checker.scan_path
  useEffect(() => {
    Promise.all([fetchConfig('subtitle'), fetchConfig('checker')]).then(([subRes, checkRes]: any) => {
      const s = subRes.code === 0 ? (subRes.data?.subtitle || {}) : {}
      const c = checkRes.code === 0 ? (checkRes.data?.checker || {}) : {}
      const defaultPath = s.scan_path || c.scan_path || ''
      setDefaultPath(defaultPath)
      setScanPath(defaultPath)
      setSubtitleConfig(s)
      if (defaultPath) {
        fetchSubtitleScanResults(defaultPath).then((res: any) => {
          if (res.code === 0 && res.data.total > 0) {
            setScannedFiles(res.data.files)
          }
        }).catch(() => {})
      }
    }).catch(() => {})
  }, [])

  // 加载任务列表
  const loadTasks = useCallback(async () => {
    setTasksLoading(true)
    try {
      const res: any = await fetchSubtitleTasks()
      if (res.code === 0) setTasks(res.data)
    } catch {} finally { setTasksLoading(false) }
  }, [])

  useEffect(() => { loadTasks() }, [loadTasks])

  // 加载任务详情
  const loadTaskDetail = useCallback(async (taskId: string) => {
    setDetailLoading(true)
    try {
      const res: any = await fetchSubtitleTaskDetail(taskId)
      if (res.code === 0) {
        setSelectedTask(res.data)
        setTaskItems(res.data.items || [])
      }
    } catch {} finally { setDetailLoading(false) }
  }, [])

  // Socket 实时进度
  useEffect(() => {
    if (lastSubtitleProgress) {
      const { task_id, phase, status } = lastSubtitleProgress
      if (task_id === runningTaskId) {
        loadTaskDetail(task_id)
        loadTasks()
        if (phase === 'audio' && status === 'completed') {
          message.success('音频提取完成，可以开始生成字幕')
        } else if (phase === 'subtitle' && status === 'completed') {
          message.success('字幕生成完成')
        }
      }
    }
  }, [lastSubtitleProgress, runningTaskId, loadTaskDetail, loadTasks, message])

  // 扫描目录
  const handleScan = useCallback(async () => {
    if (!scanPath.trim()) {
      message.warning('请输入扫描路径')
      return
    }
    setScanning(true)
    setSelectedFileKeys([])
    try {
      const res: any = await scanSubtitleMedia(scanPath.trim())
      if (res.code === 0) {
        setScannedFiles(res.data.files)
        if (res.data.total === 0) {
          message.warning('未找到媒体文件')
        } else {
          message.info(`扫描到 ${res.data.total} 个媒体文件，请勾选后提取音轨`)
        }
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '扫描失败')
    } finally { setScanning(false) }
  }, [scanPath, message])

  // 启动音频提取（只对勾选的文件）
  const handleStartAudio = useCallback(async () => {
    if (!scanPath.trim()) {
      message.warning('请输入扫描路径')
      return
    }
    if (selectedFileKeys.length === 0) {
      message.warning('请先勾选要提取音轨的视频文件')
      return
    }
    setStarting(true)
    try {
      const files = scannedFiles.filter((f) => selectedFileKeys.includes(f.video_path || f.path))
      const res: any = await startSubtitleTask({ path: scanPath.trim(), files })
      if (res.code === 0) {
        setRunningTaskId(res.data.task_id)
        message.info(`音频提取已启动，共 ${res.data.total} 个文件`)
        setSelectedFileKeys([])
        fetchSubtitleScanResults(scanPath.trim()).then((r: any) => {
          if (r.code === 0) setScannedFiles(r.data.files)
        }).catch(() => {})
        loadTasks()
        setActiveTab('audio')
        setTimeout(() => loadTaskDetail(res.data.task_id), 500)
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      const msg = e.response?.data?.message || '启动失败'
      message.error(msg)
      if (msg.includes('已不存在')) {
        fetchSubtitleScanResults(scanPath.trim()).then((r: any) => {
          if (r.code === 0) setScannedFiles(r.data.files)
        }).catch(() => {})
      }
    } finally { setStarting(false) }
  }, [scanPath, selectedFileKeys, scannedFiles, message, loadTasks, loadTaskDetail])

  // 停止任务
  const handleStop = useCallback(async (taskId: string) => {
    try {
      await stopSubtitleTask(taskId)
      message.info('停止信号已发送')
    } catch { message.error('停止失败') }
  }, [message])

  // 启动字幕生成（第二步）
  const handleGenerateSubtitle = useCallback(async (taskId: string) => {
    try {
      const res: any = await generateSubtitle(taskId)
      if (res.code === 0) {
        setRunningTaskId(taskId)
        message.info('字幕生成已启动')
        setActiveTab('subtitle')
        loadTaskDetail(taskId)
        loadTasks()
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '启动失败')
    }
  }, [message, loadTasks, loadTaskDetail])

  // 单个影片生成字幕
  const handleGenerateForVideo = useCallback(async (videoPath: string) => {
    if (!selectedTask) return
    try {
      const res: any = await generateSubtitleForVideo(selectedTask.id, videoPath)
      if (res.code === 0) {
        setRunningTaskId(selectedTask.id)
        message.info(`已启动「${selectedTask.name}」中该影片的字幕生成，共 ${res.data.count} 条音轨`)
        setActiveTab('subtitle')
        loadTaskDetail(selectedTask.id)
        loadTasks()
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '启动失败')
    }
  }, [selectedTask, message, loadTasks, loadTaskDetail])

  // 删除任务
  const handleDeleteTask = useCallback(async (taskId: string) => {
    try {
      await deleteSubtitleTask(taskId)
      message.success('任务已删除')
      if (selectedTask?.id === taskId) {
        setSelectedTask(null)
        setTaskItems([])
      }
      loadTasks()
    } catch { message.error('删除失败') }
  }, [message, selectedTask, loadTasks])

  // 重新生成字幕（重置状态为 pending，可再次点击"生成字幕"）
  const handleRegenerate = useCallback(async () => {
    if (selectedRowKeys.length === 0) return
    try {
      const res: any = await regenerateSubtitle(selectedRowKeys)
      if (res.code === 0) {
        message.success(res.message)
        if (selectedTask) loadTaskDetail(selectedTask.id)
      } else {
        message.error(res.message)
      }
    } catch { message.error('操作失败') }
  }, [selectedRowKeys, selectedTask, message, loadTaskDetail])

  // 直接生成/重新生成字幕：对已完成的音轨也会覆盖生成
  const handleGenerateForSelected = useCallback(async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要生成字幕的音轨')
      return
    }
    try {
      const res: any = await regenerateSubtitle(selectedRowKeys)
      if (res.code === 0) {
        const genRes: any = await generateSubtitle(selectedTask.id)
        if (genRes.code === 0) {
          setRunningTaskId(selectedTask.id)
          message.info('字幕生成已启动')
          loadTaskDetail(selectedTask.id)
          loadTasks()
        } else {
          message.error(genRes.message)
        }
      }
    } catch { message.error('操作失败') }
  }, [selectedRowKeys, selectedTask, message, loadTasks, loadTaskDetail])

  // 删除音轨文件
  const handleDeleteAudio = useCallback(async () => {
    const itemsWithAudio = taskItems.filter(
      (item: any) => selectedRowKeys.includes(item.id) && item.audio_path
    )
    if (itemsWithAudio.length === 0) {
      message.warning('选中项中没有已提取的音轨文件')
      return
    }
    Modal.confirm({
      title: '确认删除音轨文件',
      content: `将删除 ${itemsWithAudio.length} 个音轨文件（WAV），此操作不可恢复！`,
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          const ids = itemsWithAudio.map((i: any) => i.id)
          const res: any = await deleteSubtitleAudio(ids)
          if (res.code === 0) {
            message.success(res.message)
            setSelectedRowKeys([])
            if (selectedTask) loadTaskDetail(selectedTask.id)
          }
        } catch { message.error('删除失败') }
      },
    })
  }, [taskItems, selectedRowKeys, selectedTask, message, loadTaskDetail])

  const formatSize = (bytes: number) => {
    if (!bytes) return '-'
    let size = bytes
    for (const unit of ['B', 'KiB', 'MiB', 'GiB']) {
      if (size < 1024) return `${size.toFixed(1)} ${unit}`
      size /= 1024
    }
    return `${size.toFixed(1)} TiB`
  }

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '-'
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  // 按视频聚合进度
  const videoProgressMap = useMemo(() => {
    const map = new Map<string, { total: number; audioDone: number; subtitleDone: number; items: any[] }>()
    taskItems.forEach((item) => {
      const key = item.video_path
      if (!map.has(key)) {
        map.set(key, { total: 0, audioDone: 0, subtitleDone: 0, items: [] })
      }
      const v = map.get(key)!
      v.total += 1
      v.items.push(item)
      if (item.audio_status === 'done') v.audioDone += 1
      if (item.subtitle_status === 'done') v.subtitleDone += 1
    })
    return map
  }, [taskItems])

  // 不支持平台时显示
  if (platform && !platform.supported) {
    return (
      <div>
        <Typography.Title level={4} style={{ marginBottom: 24 }}>
          <SoundOutlined /> 字幕生成
        </Typography.Title>
        <Card variant="borderless">
          <Alert
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            message="当前平台不支持字幕生成功能"
            description={
              <div>
                <p>平台: {platform.platform} ({platform.arch})</p>
                <p>原因: {platform.reason}</p>
                <p>字幕生成功能需要 Mac Apple Silicon (M1/M2/M3/M4) 并安装 mlx-whisper。</p>
              </div>
            }
          />
        </Card>
      </div>
    )
  }

  // 扫描结果表格列
  const fileColumns = [
    {
      title: '状态', width: 120,
      render: (_: any, record: any) => (
        <Space>
          {record.file_exists === 0 ? (
            <Tag color="error">文件丢失</Tag>
          ) : record.extracted ? (
            <Tag color="success">已提取</Tag>
          ) : (
            <Tag>未提取</Tag>
          )}
        </Space>
      ),
    },
    {
      title: '文件名', dataIndex: 'video_basename', ellipsis: true,
      sorter: (a: any, b: any) => (a.video_basename || a.basename).localeCompare(b.video_basename || b.basename),
    },
    {
      title: '大小', dataIndex: 'file_size', width: 100,
      sorter: (a: any, b: any) => ((a.file_size || a.size) || 0) - ((b.file_size || b.size) || 0),
      render: (_: any, record: any) => formatSize(record.file_size || record.size),
    },
    {
      title: '路径', dataIndex: 'video_path', ellipsis: true,
      render: (_: any, record: any) => {
        const p = record.video_path || record.path
        return <Tooltip title={p}><Typography.Text ellipsis style={{ maxWidth: 300, fontFamily: 'monospace', fontSize: 11 }}>{p}</Typography.Text></Tooltip>
      },
    },
  ]

  // 任务列表列
  const taskColumns = (phase: 'audio' | 'subtitle') => [
    { title: '任务名', dataIndex: 'name', ellipsis: true },
    { title: '扫描路径', dataIndex: 'scan_path', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 120,
      render: (status: string) => {
        const s = STATUS_MAP[status] || { color: 'default', label: status }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '总进度', width: 200,
      render: (_: any, record: any) => {
        const completed = phase === 'audio' ? record.audio_completed : record.subtitle_completed
        const percent = record.total ? Math.round((completed / record.total) * 100) : 0
        return (
          <Tooltip title={`${completed} / ${record.total}`}>
            <Progress percent={percent} size="small" style={{ minWidth: 120 }} />
          </Tooltip>
        )
      },
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 170,
    },
    {
      title: '操作', width: 200,
      render: (_: any, record: any) => (
        <Space size={4}>
          {(record.status === 'running') && (
            <Button size="small" danger icon={<StopOutlined />} onClick={(e) => { e.stopPropagation(); handleStop(record.id) }}>
              停止
            </Button>
          )}
          {(phase === 'audio') && (record.status === 'audio_done' || record.status === 'stopped') && (
            <Button size="small" type="primary" icon={<FileTextOutlined />} onClick={(e) => { e.stopPropagation(); handleGenerateSubtitle(record.id) }}>
              生成字幕
            </Button>
          )}
          {record.status !== 'running' && (
            <Popconfirm title="确认删除此任务？" onConfirm={(e) => { e?.stopPropagation(); handleDeleteTask(record.id) }} onCancel={(e) => e?.stopPropagation()}>
              <Button size="small" danger icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()}>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  // 影片级进度列
  const videoProgressColumns = [
    {
      title: '视频文件', dataIndex: 'basename', ellipsis: true,
      render: (_: any, record: any) => {
        const first = record.items[0]
        return <Tooltip title={first.video_path}><Typography.Text ellipsis style={{ maxWidth: 300 }}>{first.video_basename}</Typography.Text></Tooltip>
      },
    },
    {
      title: '音频名称', ellipsis: true,
      render: (_: any, record: any) => (
        <Space wrap>
          {record.items.map((item: any) => (
            <Tooltip key={item.id} title={item.audio_path || `音轨 #${item.track_index}`}>
              <Tag color={item.audio_status === 'done' ? 'success' : item.audio_status === 'error' ? 'error' : 'default'}>
                {item.track_title || `音轨${item.track_index}`}
                {item.track_language && ` (${item.track_language})`}
              </Tag>
            </Tooltip>
          ))}
        </Space>
      ),
    },
    {
      title: '音轨进度', width: 200,
      render: (_: any, record: any) => {
        const percent = record.total ? Math.round((record.audioDone / record.total) * 100) : 0
        return <Progress percent={percent} size="small" format={() => `${record.audioDone}/${record.total}`} />
      },
    },
    {
      title: '字幕进度', width: 200,
      render: (_: any, record: any) => {
        const percent = record.total ? Math.round((record.subtitleDone / record.total) * 100) : 0
        return <Progress percent={percent} size="small" format={() => `${record.subtitleDone}/${record.total}`} />
      },
    },
    {
      title: '操作', width: 140, fixed: 'right' as const,
      render: (_: any, record: any) => (
        <Button
          size="small"
          type="primary"
          icon={<FileTextOutlined />}
          disabled={record.audioDone === 0 || selectedTask?.status === 'running' || selectedTask?.status === 'subtitle_running'}
          onClick={() => handleGenerateForVideo(record.path)}
        >
          生成字幕
        </Button>
      ),
    },
  ]

  // 音轨详情列
  const itemColumns = [
    {
      title: '音频状态', dataIndex: 'audio_status', width: 100, fixed: 'left' as const,
      filters: [
        { text: '待提取', value: 'pending' },
        { text: '已完成', value: 'done' },
        { text: '失败', value: 'error' },
      ],
      onFilter: (value: any, record: any) => record.audio_status === value,
      render: (status: string) => {
        const s = AUDIO_STATUS[status] || { color: 'default', label: status }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '字幕状态', dataIndex: 'subtitle_status', width: 100,
      filters: [
        { text: '待生成', value: 'pending' },
        { text: '已完成', value: 'done' },
        { text: '失败', value: 'error' },
      ],
      onFilter: (value: any, record: any) => record.subtitle_status === value,
      render: (status: string) => {
        const s = SUBTITLE_STATUS[status] || { color: 'default', label: status }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '文件名', dataIndex: 'video_basename', ellipsis: true,
      sorter: (a: any, b: any) => a.video_basename.localeCompare(b.video_basename),
    },
    {
      title: '音轨', width: 120,
      render: (_: any, record: any) => (
        <Space direction="vertical" size={0}>
          <Tag style={{ fontSize: 11, padding: '0 4px' }}>#{record.track_index}</Tag>
          {record.track_language && <Tag color="blue" style={{ fontSize: 11, padding: '0 4px' }}>{record.track_language}</Tag>}
          {record.track_title && <Typography.Text type="secondary" ellipsis style={{ maxWidth: 100, fontSize: 11 }}>{record.track_title}</Typography.Text>}
        </Space>
      ),
    },
    {
      title: '大小', dataIndex: 'file_size', width: 100,
      sorter: (a: any, b: any) => (a.file_size || 0) - (b.file_size || 0),
      render: (size: number) => formatSize(size),
    },
    {
      title: '时长', dataIndex: 'audio_duration', width: 80,
      render: (d: number | null) => formatDuration(d),
    },
    {
      title: '音轨路径', dataIndex: 'audio_path', ellipsis: true,
      render: (p: string | null) => p ? <Tooltip title={p}><Typography.Text ellipsis style={{ maxWidth: 200, fontFamily: 'monospace', fontSize: 11 }}>{p}</Typography.Text></Tooltip> : <Typography.Text type="secondary">-</Typography.Text>,
    },
    {
      title: '字幕路径', dataIndex: 'subtitle_path', ellipsis: true,
      render: (p: string | null) => p ? <Tooltip title={p}><Typography.Text ellipsis style={{ maxWidth: 200, fontFamily: 'monospace', fontSize: 11 }}>{p}</Typography.Text></Tooltip> : <Typography.Text type="secondary">-</Typography.Text>,
    },
    {
      title: '错误信息', dataIndex: 'errors', ellipsis: true,
      render: (errors: string | null) => errors
        ? <Tooltip title={errors}><Typography.Text type="danger" ellipsis>{errors}</Typography.Text></Tooltip>
        : <Typography.Text type="secondary">-</Typography.Text>,
    },
  ]

  const audioTasks = tasks.filter((t) => t.status !== 'completed' || t.audio_completed < t.total)
  const subtitleTasks = tasks.filter((t) => t.subtitle_completed > 0 || t.status === 'subtitle_running' || t.status === 'completed')

  const renderTaskDetail = (phase: 'audio' | 'subtitle') => {
    if (!selectedTask) return null
    const videoProgressData = Array.from(videoProgressMap.entries()).map(([path, data]) => ({ path, ...data, basename: data.items[0]?.video_basename }))
    return (
      <Card
        variant="borderless"
        title={
          <Space>
            <span>任务详情</span>
            <Tag color="blue">{selectedTask.name}</Tag>
            {(() => {
              const s = STATUS_MAP[selectedTask.status] || { color: 'default', label: selectedTask.status }
              return <Tag color={s.color}>{s.label}</Tag>
            })()}
            <Tag>音轨: {selectedTask.audio_completed}/{selectedTask.total}</Tag>
            <Tag>字幕: {selectedTask.subtitle_completed}/{selectedTask.total}</Tag>
          </Space>
        }
        extra={
          <Space>
            {(selectedTask.status === 'running') && (
              <Button danger icon={<StopOutlined />} onClick={() => handleStop(selectedTask.id)}>
                停止
              </Button>
            )}
            {(phase === 'audio') && (selectedTask.status === 'audio_done' || selectedTask.status === 'stopped' || selectedTask.status === 'completed') && (
              <Button type="primary" icon={<FileTextOutlined />} onClick={() => handleGenerateSubtitle(selectedTask.id)}>
                全部生成字幕
              </Button>
            )}
            {(phase === 'subtitle') && selectedRowKeys.length > 0 && (
              <>
                <Button type="primary" icon={<FileTextOutlined />} onClick={handleGenerateForSelected}>
                  生成选中字幕 ({selectedRowKeys.length})
                </Button>
                <Button onClick={handleRegenerate}>
                  重置选中 ({selectedRowKeys.length})
                </Button>
              </>
            )}
            {selectedRowKeys.length > 0 && (
              <Button danger icon={<DeleteOutlined />} onClick={handleDeleteAudio}>
                删除选中音轨 ({selectedRowKeys.length})
              </Button>
            )}
          </Space>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Card size="small" title="影片级进度">
            <Table
              dataSource={videoProgressData}
              columns={videoProgressColumns}
              rowKey="path"
              size="small"
              pagination={false}
              locale={{ emptyText: <Empty description="暂无进度" /> }}
            />
          </Card>
          <Card size="small" title="音轨明细">
            <Table
              dataSource={taskItems}
              columns={itemColumns}
              rowKey="id"
              size="small"
              loading={detailLoading}
              scroll={{ x: 1100 }}
              rowSelection={{
                selectedRowKeys,
                onChange: (keys) => setSelectedRowKeys(keys as number[]),
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
        </Space>
      </Card>
    )
  }

  const tabItems = [
    {
      key: 'scan',
      label: '扫描与提取',
      children: (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          {/* 扫描区域 */}
          <Card variant="borderless">
            <Space.Compact style={{ width: '100%' }}>
              <Input
                prefix={<FolderOutlined />}
                placeholder={defaultPath || '输入要扫描的目录路径...'}
                value={scanPath}
                onChange={(e) => setScanPath(e.target.value)}
                onPressEnter={handleScan}
                style={{ fontFamily: 'monospace' }}
                suffix={
                  defaultPath && scanPath !== defaultPath ? (
                    <Button type="link" size="small" onClick={() => setScanPath(defaultPath)}>恢复默认</Button>
                  ) : undefined
                }
              />
              <Button
                icon={<SearchOutlined />}
                onClick={handleScan}
                loading={scanning}
              >
                扫描
              </Button>
              <Button
                type="primary"
                icon={<SoundOutlined />}
                onClick={handleStartAudio}
                loading={starting}
                disabled={platform && !platform.supported}
              >
                提取音轨 ({selectedFileKeys.length})
              </Button>
            </Space.Compact>
          </Card>

          {/* 扫描结果 */}
          {scannedFiles.length > 0 && (
            <Card
              variant="borderless"
              title={
                <Space>
                  <span>扫描结果</span>
                  <Tag color="blue">{scannedFiles.length} 个文件</Tag>
                  <Tag color="processing">已选择 {selectedFileKeys.length} 个</Tag>
                </Space>
              }
              extra={
                <Space>
                  <Button size="small" onClick={() => setSelectedFileKeys(scannedFiles.filter((f) => f.file_exists !== 0).map((f) => f.video_path || f.path))}>全选可用</Button>
                  <Button size="small" onClick={() => setSelectedFileKeys([])}>取消全选</Button>
                </Space>
              }
            >
              <Table
                dataSource={scannedFiles}
                columns={fileColumns}
                rowKey={(record: any) => record.video_path || record.path}
                size="small"
                rowSelection={{
                  selectedRowKeys: selectedFileKeys,
                  onChange: (keys) => setSelectedFileKeys(keys as string[]),
                  getCheckboxProps: (record: any) => ({
                    disabled: record.file_exists === 0,
                  }),
                }}
                pagination={{
                  defaultPageSize: 50,
                  showSizeChanger: true,
                  pageSizeOptions: [20, 50, 200, 500],
                  showTotal: (t) => `共 ${t} 个文件`,
                }}
                locale={{ emptyText: <Empty description="暂无文件" /> }}
                rowClassName={(record: any) => record.file_exists === 0 ? 'opacity-50' : ''}
              />
            </Card>
          )}
        </Space>
      ),
    },
    {
      key: 'audio',
      label: '音频提取任务',
      children: (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Card
            variant="borderless"
            title="音频提取任务"
            extra={
              <Space>
                <Tag color="blue">并发数: {subtitleConfig.audio_concurrency ?? 2}</Tag>
                <Button icon={<ReloadOutlined />} onClick={loadTasks} loading={tasksLoading}>刷新</Button>
              </Space>
            }
          >
            <Table
              dataSource={audioTasks}
              columns={taskColumns('audio')}
              rowKey="id"
              size="small"
              loading={tasksLoading}
              pagination={false}
              locale={{ emptyText: <Empty description="暂无音频提取任务" /> }}
              onRow={(record) => ({
                onClick: () => {
                  setSelectedRowKeys([])
                  loadTaskDetail(record.id)
                },
                style: { cursor: 'pointer', background: selectedTask?.id === record.id ? 'rgba(99,102,241,0.06)' : undefined },
              })}
            />
          </Card>
          {renderTaskDetail('audio')}
        </Space>
      ),
    },
    {
      key: 'subtitle',
      label: '字幕生成任务',
      children: (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Card
            variant="borderless"
            title="字幕生成任务"
            extra={
              <Space>
                <Tag color="blue">并发数: {subtitleConfig.subtitle_concurrency ?? 1}</Tag>
                <Button icon={<ReloadOutlined />} onClick={loadTasks} loading={tasksLoading}>刷新</Button>
              </Space>
            }
          >
            <Table
              dataSource={subtitleTasks}
              columns={taskColumns('subtitle')}
              rowKey="id"
              size="small"
              loading={tasksLoading}
              pagination={false}
              locale={{ emptyText: <Empty description="暂无字幕生成任务" /> }}
              onRow={(record) => ({
                onClick: () => {
                  setSelectedRowKeys([])
                  loadTaskDetail(record.id)
                },
                style: { cursor: 'pointer', background: selectedTask?.id === record.id ? 'rgba(99,102,241,0.06)' : undefined },
              })}
            />
          </Card>
          {renderTaskDetail('subtitle')}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <SoundOutlined /> 字幕生成
      </Typography.Title>

      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* 平台状态 */}
        {platform && (
          <Card variant="borderless" size="small">
            <Space>
              <Tag color={platform.supported ? 'success' : 'warning'}>平台: {platform.platform}/{platform.arch}</Tag>
              <Tag color={platform.mlx_whisper ? 'success' : 'error'}>mlx-whisper: {platform.mlx_whisper ? '已安装' : '未安装'}</Tag>
              <Tag color={platform.ffmpeg ? 'success' : 'error'}>ffmpeg: {platform.ffmpeg ? '已安装' : '未安装'}</Tag>
              {subtitleConfig.whisper_model && <Tag color="blue">模型: {subtitleConfig.whisper_model}</Tag>}
              {subtitleConfig.whisper_language && <Tag>语言: {subtitleConfig.whisper_language}</Tag>}
              {subtitleConfig.subtitle_mode && (
                <Tag color={subtitleConfig.subtitle_mode === 'bilingual' ? 'purple' : subtitleConfig.subtitle_mode === 'chinese' ? 'orange' : 'cyan'}>
                  模式: {subtitleConfig.subtitle_mode === 'original' ? '原语言' : subtitleConfig.subtitle_mode === 'chinese' ? '仅中文' : '双语'}
                </Tag>
              )}
            </Space>
          </Card>
        )}

        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Space>
    </div>
  )
}
