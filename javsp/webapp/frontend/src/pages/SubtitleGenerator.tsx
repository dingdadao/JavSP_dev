import { useState, useCallback, useEffect, useMemo } from 'react'
import {
  Card, Button, Space, Typography, Table, Tag, Input,
  Modal, App, Empty, Alert, Tooltip, Popconfirm, Tabs, Progress,
  Radio,
} from 'antd'
import {
  FolderOutlined, SoundOutlined,
  DeleteOutlined, ReloadOutlined,
  SearchOutlined, StopOutlined,
  FileTextOutlined, WarningOutlined,
  AudioOutlined,
} from '@ant-design/icons'
import {
  fetchSubtitlePlatform, fetchSubtitleTasks, fetchSubtitleTaskDetail,
  scanSubtitleMedia, fetchSubtitleScanResults, startSubtitleTask, stopSubtitleTask,
  generateSubtitle, generateSubtitleForVideo, deleteSubtitleTask, regenerateSubtitle,
  deleteSubtitleAudio, fetchConfig, searchSubtitle, batchSearchSubtitles, downloadSubtitle,
  batchDownloadSubtitles, batchDeleteAudio, batchDeleteSubtitle,
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

const SEARCH_STATUS: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待搜索' },
  searching: { color: 'processing', label: '搜索中' },
  found: { color: 'success', label: '有结果' },
  not_found: { color: 'warning', label: '无结果' },
  error: { color: 'error', label: '搜索失败' },
}

const DOWNLOAD_STATUS: Record<string, { color: string; label: string }> = {
  has_subtitle: { color: 'success', label: '已下载（已跳过）' },
  auto_downloaded: { color: 'blue', label: '已自动下载' },
  needs_manual: { color: 'warning', label: '需手动选择' },
  no_results: { color: 'error', label: '无匹配结果' },
  error: { color: 'error', label: '下载失败' },
}

const FILTER_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'no_sub_no_audio', label: '无字幕无音轨' },
  { value: 'has_sub_no_audio', label: '有字幕无音轨' },
  { value: 'no_sub_has_audio', label: '无字幕有音轨' },
  { value: 'has_sub_has_audio', label: '有字幕有音轨' },
  { value: 'has_search', label: '搜索有结果' },
  { value: 'no_sub_has_search', label: '无字幕有搜索结果' },
]

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

  // 字幕搜索
  const [searching, setSearching] = useState(false)
  const [searchModalVisible, setSearchModalVisible] = useState(false)
  const [currentSearchVideo, setCurrentSearchVideo] = useState<any>(null)
  const [currentSearchResults, setCurrentSearchResults] = useState<any[]>([])
  const [searchModalLoading, setSearchModalLoading] = useState(false)

  // 筛选和批量操作
  const [filterType, setFilterType] = useState('all')
  const [batchDeletingAudio, setBatchDeletingAudio] = useState(false)
  const [batchDeletingSubtitle, setBatchDeletingSubtitle] = useState(false)
  const [batchDownloading, setBatchDownloading] = useState(false)
  const [batchDownloadResult, setBatchDownloadResult] = useState<any>(null)
  const [batchDownloadModalVisible, setBatchDownloadModalVisible] = useState(false)

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

  // 搜索单个视频的字幕
  const handleSearchSubtitle = useCallback(async (video: any) => {
    setCurrentSearchVideo(video)
    setCurrentSearchResults([])
    setSearchModalVisible(true)
    setSearchModalLoading(true)
    try {
      const res: any = await searchSubtitle(video.video_path || video.path)
      if (res.code === 0) {
        setCurrentSearchResults(res.data.results || [])
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '搜索失败')
    } finally {
      setSearchModalLoading(false)
    }
  }, [message])

  // 批量搜索字幕
  const handleBatchSearchSubtitles = useCallback(async () => {
    if (selectedFileKeys.length === 0) {
      message.warning('请先勾选要搜索字幕的视频文件')
      return
    }
    setSearching(true)
    try {
      const files = scannedFiles.filter((f) => {
        if (!selectedFileKeys.includes(f.video_path || f.path)) return false
        if (f.local_subtitle_path || (f.subtitle_count && f.subtitle_count > 0)) return false
        return true
      })
      if (files.length === 0) {
        message.warning('所选文件均已有字幕，已跳过')
        setSearching(false)
        return
      }
      const skippedCount = selectedFileKeys.length - files.length
      const res: any = await batchSearchSubtitles(files)
      if (res.code === 0) {
        const msg = skippedCount > 0
          ? `批量搜索完成，搜索 ${res.data.total} 个文件，跳过 ${skippedCount} 个已有字幕的文件`
          : `批量搜索完成，共搜索 ${res.data.total} 个文件`
        message.success(msg)
        fetchSubtitleScanResults(scanPath.trim()).then((r: any) => {
          if (r.code === 0) setScannedFiles(r.data.files)
        }).catch(() => {})
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '批量搜索失败')
    } finally {
      setSearching(false)
    }
  }, [selectedFileKeys, scannedFiles, scanPath, message])

  // 批量下载字幕（自动匹配偏好语言，未匹配则手动选择）
  const handleBatchDownloadSubtitles = useCallback(async () => {
    if (selectedFileKeys.length === 0) {
      message.warning('请先勾选要下载字幕的视频文件')
      return
    }
    setBatchDownloading(true)
    try {
      const files = scannedFiles.filter((f) => selectedFileKeys.includes(f.video_path || f.path))
      const res: any = await batchDownloadSubtitles(files)
      if (res.code === 0) {
        setBatchDownloadResult(res.data)
        setBatchDownloadModalVisible(true)
        const { counts } = res.data
        message.success(
          `批量下载完成：已有字幕 ${counts.has_subtitle}，自动下载 ${counts.auto_downloaded}，需手动选择 ${counts.needs_manual}，无结果 ${counts.no_results}，失败 ${counts.error}`
        )
        fetchSubtitleScanResults(scanPath.trim()).then((r: any) => {
          if (r.code === 0) setScannedFiles(r.data.files)
        }).catch(() => {})
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '批量下载失败')
    } finally {
      setBatchDownloading(false)
    }
  }, [selectedFileKeys, scannedFiles, scanPath, message])

  // 下载选中的字幕
  const handleDownloadSubtitle = useCallback(async (subtitleResult: any) => {
    if (!currentSearchVideo) return
    setSearchModalLoading(true)
    try {
      const videoPath = currentSearchVideo.video_path || currentSearchVideo.path
      const videoDir = currentSearchVideo.video_dir || currentSearchVideo.dir
      const videoBasename = currentSearchVideo.video_basename || currentSearchVideo.basename
      const res: any = await downloadSubtitle({
        video_path: videoPath,
        video_dir: videoDir,
        video_basename: videoBasename,
        subtitle_result: subtitleResult,
      })
      if (res.code === 0) {
        message.success(`字幕下载成功: ${subtitleResult.source === 'xunlei' ? '迅雷' : '射手网'}`)
        setSearchModalVisible(false)
        fetchSubtitleScanResults(scanPath.trim()).then((r: any) => {
          if (r.code === 0) setScannedFiles(r.data.files)
        }).catch(() => {})
        // 如果从批量下载弹窗进入，下载成功后从结果列表中移除该条记录
        if (batchDownloadModalVisible) {
          const downloadedPath = currentSearchVideo.video_path || currentSearchVideo.path
          setBatchDownloadResult((prev: any) => {
            if (!prev) return prev
            const newResults = prev.results.filter((r: any) => (r.video_path || r.path) !== downloadedPath)
            const newCounts = { ...prev.counts }
            if (newCounts.needs_manual > 0) newCounts.needs_manual -= 1
            newCounts.auto_downloaded = (newCounts.auto_downloaded || 0) + 1
            return { ...prev, counts: newCounts, results: newResults }
          })
        }
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '下载失败')
    } finally {
      setSearchModalLoading(false)
    }
  }, [currentSearchVideo, scanPath, message, batchDownloadModalVisible])

  // 批量删除音轨
  const handleBatchDeleteAudio = useCallback(async () => {
    if (selectedFileKeys.length === 0) {
      message.warning('请先勾选要删除音轨的视频文件')
      return
    }
    setBatchDeletingAudio(true)
    try {
      const files = scannedFiles.filter((f) => selectedFileKeys.includes(f.video_path || f.path))
      const res: any = await batchDeleteAudio(files)
      if (res.code === 0) {
        message.success(`批量删除音轨完成: 删除 ${res.data.deleted} 个, 跳过 ${res.data.skipped} 个, 失败 ${res.data.failed} 个`)
        fetchSubtitleScanResults(scanPath.trim()).then((r: any) => {
          if (r.code === 0) setScannedFiles(r.data.files)
        }).catch(() => {})
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '批量删除失败')
    } finally {
      setBatchDeletingAudio(false)
    }
  }, [selectedFileKeys, scannedFiles, scanPath, message])

  // 批量删除字幕
  const handleBatchDeleteSubtitle = useCallback(async () => {
    if (selectedFileKeys.length === 0) {
      message.warning('请先勾选要删除字幕的视频文件')
      return
    }
    setBatchDeletingSubtitle(true)
    try {
      const files = scannedFiles.filter((f) => selectedFileKeys.includes(f.video_path || f.path))
      const res: any = await batchDeleteSubtitle(files)
      if (res.code === 0) {
        message.success(`批量删除字幕完成: 删除 ${res.data.deleted} 个, 跳过 ${res.data.skipped} 个, 失败 ${res.data.failed} 个`)
        fetchSubtitleScanResults(scanPath.trim()).then((r: any) => {
          if (r.code === 0) setScannedFiles(r.data.files)
        }).catch(() => {})
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '批量删除失败')
    } finally {
      setBatchDeletingSubtitle(false)
    }
  }, [selectedFileKeys, scannedFiles, scanPath, message])

  // 筛选逻辑
  const filteredFiles = useMemo(() => {
    if (filterType === 'all') return scannedFiles

    return scannedFiles.filter((file) => {
      const hasSub = file.local_subtitle_path || (file.subtitle_count && file.subtitle_count > 0)
      const hasAudio = file.local_audio_path || file.extracted
      const hasSearch = file.search_status === 'found'

      switch (filterType) {
        case 'no_sub_no_audio':
          return !hasSub && !hasAudio
        case 'has_sub_no_audio':
          return hasSub && !hasAudio
        case 'no_sub_has_audio':
          return !hasSub && hasAudio
        case 'has_sub_has_audio':
          return hasSub && hasAudio
        case 'has_search':
          return hasSearch
        case 'no_sub_has_search':
          return !hasSub && hasSearch
        default:
          return true
      }
    })
  }, [scannedFiles, filterType])

  // 选中文件状态统计
  const selectedStats = useMemo(() => {
    const selected = scannedFiles.filter((f) => selectedFileKeys.includes(f.video_path || f.path))
    return {
      hasAudio: selected.some((f) => f.local_audio_path || f.extracted),
      hasSub: selected.some((f) => f.local_subtitle_path || (f.subtitle_count && f.subtitle_count > 0)),
      hasNoSubNoAudio: selected.some((f) => !f.local_subtitle_path && !f.local_audio_path && !f.extracted),
      hasSearch: selected.some((f) => f.search_status === 'found'),
    }
  }, [selectedFileKeys, scannedFiles])

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

  // 平台不支持时的警告提示（不再完全屏蔽，保留字幕搜索下载功能）
  const showPlatformWarning = platform && !platform.supported

  // 扫描结果表格列
  const fileColumns = [
    {
      title: '状态', width: 150,
      render: (_: any, record: any) => (
        <Space>
          {record.file_exists === 0 ? (
            <Tag color="error">文件丢失</Tag>
          ) : record.extracted ? (
            <Tag color="success">已提取</Tag>
          ) : (
            <Tag>未提取</Tag>
          )}
          {record.local_audio_path && <Tag color="blue"><AudioOutlined /> 音轨</Tag>}
        </Space>
      ),
    },
    {
      title: '字幕', width: 150,
      render: (_: any, record: any) => {
        const hasSub = record.local_subtitle_path || (record.subtitle_count && record.subtitle_count > 0)
        if (hasSub) {
          return (
            <Space>
              <Tag color="green"><FileTextOutlined /> 已下载</Tag>
              {record.subtitle_count && record.subtitle_count > 1 && (
                <Tag color="orange">{record.subtitle_count} 条</Tag>
              )}
            </Space>
          )
        }
        if (record.search_status === 'found') {
          const resultCount = record.search_results ? JSON.parse(record.search_results).length : 0
          return (
            <Space>
              <Tag color="purple"><SearchOutlined /> 可下载</Tag>
              {resultCount > 0 && <Tag>{resultCount} 条</Tag>}
            </Space>
          )
        }
        return <Tag>无字幕</Tag>
      },
    },
    {
      title: '字幕搜索', width: 120,
      render: (_: any, record: any) => {
        const status = record.search_status || 'pending'
        const s = SEARCH_STATUS[status] || { color: 'default', label: status }
        return (
          <Space>
            <Tag color={s.color}>{s.label}</Tag>
          </Space>
        )
      },
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
    {
      title: '操作', width: 200,
      render: (_: any, record: any) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<SearchOutlined />}
            onClick={() => handleSearchSubtitle(record)}
            disabled={record.file_exists === 0 || searching}
          >
            搜索字幕
          </Button>
          {record.search_status === 'found' && (
            <Button
              size="small"
              type="primary"
              icon={<FileTextOutlined />}
              onClick={() => handleSearchSubtitle(record)}
            >
              选择字幕
            </Button>
          )}
        </Space>
      ),
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
              <Button
                icon={<SearchOutlined />}
                onClick={handleBatchSearchSubtitles}
                loading={searching}
              >
                批量搜索字幕 ({selectedFileKeys.length})
              </Button>
              <Button
                type="primary"
                icon={<FileTextOutlined />}
                onClick={handleBatchDownloadSubtitles}
                loading={batchDownloading}
              >
                批量下载字幕 ({selectedFileKeys.length})
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
                  <Radio.Group
                    value={filterType}
                    onChange={(e) => setFilterType(e.target.value)}
                    buttonStyle="solid"
                    size="small"
                  >
                    {FILTER_OPTIONS.map((opt) => (
                      <Radio.Button key={opt.value} value={opt.value}>
                        {opt.label}
                      </Radio.Button>
                    ))}
                  </Radio.Group>
                  <Button size="small" onClick={() => setSelectedFileKeys(filteredFiles.map((f) => f.video_path || f.path))}>全选</Button>
                  <Button size="small" onClick={() => setSelectedFileKeys(filteredFiles.filter((f) => f.file_exists !== 0).map((f) => f.video_path || f.path))}>全选可用</Button>
                  <Button size="small" onClick={() => setSelectedFileKeys([])}>取消全选</Button>
                </Space>
              }
            >
              {selectedFileKeys.length > 0 && (
                <Card
                  variant="outlined"
                  size="small"
                  style={{ marginBottom: 16 }}
                >
                  <Space wrap>
                    <Button
                      size="small"
                      type="primary"
                      icon={<SoundOutlined />}
                      onClick={handleStartAudio}
                      loading={starting}
                      disabled={platform && !platform.supported}
                    >
                      批量提取音轨 ({selectedFileKeys.length})
                    </Button>
                    <Button
                      size="small"
                      icon={<SearchOutlined />}
                      onClick={handleBatchSearchSubtitles}
                      loading={searching}
                    >
                      批量搜索字幕 ({selectedFileKeys.length})
                    </Button>
                    <Button
                      size="small"
                      type="primary"
                      icon={<FileTextOutlined />}
                      onClick={handleBatchDownloadSubtitles}
                      loading={batchDownloading}
                    >
                      批量下载字幕 ({selectedFileKeys.length})
                    </Button>
                    <Button
                      size="small"
                      icon={<AudioOutlined />}
                      onClick={handleBatchDeleteAudio}
                      loading={batchDeletingAudio}
                      disabled={!selectedStats.hasAudio}
                      danger
                    >
                      批量删除音轨
                    </Button>
                    <Button
                      size="small"
                      icon={<FileTextOutlined />}
                      onClick={handleBatchDeleteSubtitle}
                      loading={batchDeletingSubtitle}
                      disabled={!selectedStats.hasSub}
                      danger
                    >
                      批量删除字幕
                    </Button>
                  </Space>
                </Card>
              )}
              <Table
                dataSource={filteredFiles}
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

        {showPlatformWarning && (
          <Alert
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            message="当前平台不支持AI字幕生成"
            description={
              <div>
                <p>平台: {platform.platform} ({platform.arch})</p>
                <p>原因: {platform.reason}</p>
                <p>AI字幕生成功能需要 Mac Apple Silicon (M1/M2/M3/M4) 并安装 mlx-whisper。</p>
                <p>您仍可以使用字幕搜索和下载功能。</p>
              </div>
            }
            style={{ marginBottom: 16 }}
          />
        )}

        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Space>

      {/* 字幕搜索结果弹窗 */}
      <Modal
        title={`字幕搜索 - ${currentSearchVideo?.video_basename || currentSearchVideo?.basename || ''}`}
        open={searchModalVisible}
        onCancel={() => setSearchModalVisible(false)}
        footer={null}
        width={700}
        loading={searchModalLoading}
      >
        {currentSearchResults.length > 0 ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Alert
              type="success"
              message={`搜索到 ${currentSearchResults.length} 条字幕结果`}
              description="请选择要下载的字幕，下载后将保存为与视频同名的 .srt 文件"
              showIcon
            />
            <Table
              dataSource={currentSearchResults}
              rowKey="id"
              size="small"
              pagination={false}
              columns={[
                {
                  title: '来源', width: 80,
                  render: (_: any, record: any) => (
                    <Tag color={record.source === 'xunlei' ? 'blue' : 'green'}>
                      {record.source === 'xunlei' ? '迅雷' : '射手网'}
                    </Tag>
                  ),
                },
                {
                  title: '语言', width: 80,
                  render: (_: any, record: any) => <Tag>{record.language}</Tag>,
                },
                {
                  title: '文件名', dataIndex: 'filename', ellipsis: true,
                },
                {
                  title: '编码', width: 80, dataIndex: 'encoding',
                },
                {
                  title: '操作', width: 100,
                  render: (_: any, record: any) => (
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => handleDownloadSubtitle(record)}
                      loading={searchModalLoading}
                    >
                      下载
                    </Button>
                  ),
                },
              ]}
            />
          </Space>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Alert
              type="warning"
              message="未搜索到字幕"
              description="可以尝试通过提取音轨，使用 AI 大模型生成字幕"
              showIcon
            />
            <Button
              type="primary"
              icon={<SoundOutlined />}
              onClick={() => {
                setSearchModalVisible(false)
                setSelectedFileKeys([currentSearchVideo?.video_path || currentSearchVideo?.path])
                handleStartAudio()
              }}
              disabled={platform && !platform.supported}
            >
              提取音轨生成字幕
            </Button>
          </Space>
        )}
      </Modal>

      {/* 批量下载结果弹窗 */}
      <Modal
        title="批量下载字幕结果"
        open={batchDownloadModalVisible}
        onCancel={() => setBatchDownloadModalVisible(false)}
        footer={null}
        width={800}
      >
        {batchDownloadResult && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Alert
              type="info"
              message="下载统计"
              description={
                <Space wrap>
                  <Tag color="default">共 {batchDownloadResult.counts.total} 个</Tag>
                  <Tag color="success">已有字幕 {batchDownloadResult.counts.has_subtitle}</Tag>
                  <Tag color="blue">自动下载 {batchDownloadResult.counts.auto_downloaded}</Tag>
                  <Tag color="warning">需手动选择 {batchDownloadResult.counts.needs_manual}</Tag>
                  <Tag color="error">无结果 {batchDownloadResult.counts.no_results}</Tag>
                  <Tag color="error">失败 {batchDownloadResult.counts.error}</Tag>
                </Space>
              }
              showIcon
            />
            <Table
              dataSource={batchDownloadResult.results}
              rowKey="video_path"
              size="small"
              pagination={{ pageSize: 10, showSizeChanger: true }}
              columns={[
                {
                  title: '状态', width: 120,
                  render: (_: any, record: any) => {
                    const s = DOWNLOAD_STATUS[record.status] || { color: 'default', label: record.status }
                    return <Tag color={s.color}>{s.label}</Tag>
                  },
                },
                { title: '文件名', dataIndex: 'video_basename', ellipsis: true },
                { title: '说明', dataIndex: 'message', ellipsis: true },
                {
                  title: '操作', width: 120,
                  render: (_: any, record: any) => (
                    record.status === 'needs_manual' ? (
                      <Button
                        size="small"
                        icon={<SearchOutlined />}
                        onClick={() => handleSearchSubtitle(record)}
                      >
                        选择字幕
                      </Button>
                    ) : null
                  ),
                },
              ]}
            />
          </Space>
        )}
      </Modal>
    </div>
  )
}
