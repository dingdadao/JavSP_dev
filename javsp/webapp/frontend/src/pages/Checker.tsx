import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import {
  Card, Button, Space, Typography, Table, Tag, Input,
  Modal, App, Empty, Checkbox, Select, DatePicker, Collapse, Progress, Tooltip, Radio,
} from 'antd'
import {
  FolderOutlined, SearchOutlined,
  CheckCircleOutlined, ToolOutlined,
  FilterOutlined, ThunderboltOutlined, CloudDownloadOutlined,
} from '@ant-design/icons'
import { fetchCheckerScan, fetchCheckerScanCache, fixCheckerIssues, fetchCheckerDefaultPath, repairChecker, fetchCheckerTasks, fetchCheckerTaskDetail, mergeCheckerDuplicates, fetchCheckerLogs } from '../api'
import { useSocket } from '../hooks/useSocket'
import dayjs from 'dayjs'

interface ScanResult {
  video_path: string
  video_basename: string
  expected_video_name?: string
  video_needs_rename?: boolean
  nfo_path: string | null
  nfo_basename: string | null
  expected_nfo: string
  expected_nfo_name: string
  poster_path: string | null
  poster_basename: string
  expected_poster: string
  expected_poster_name: string
  fanart_path: string | null
  fanart_basename: string
  expected_fanart: string
  expected_fanart_name: string
  avid: string
  avid_source: string
  variant?: string
  issues: string[]
  mismatch_fields: string[]
  has_poster: boolean
  has_fanart: boolean
  convention: string
  fixed?: boolean
  repaired?: boolean
  created_time?: number
  image_orientation_issue?: string
}

interface ScanData {
  path: string
  total: number
  ok_count: number
  mismatch_count: number
  results: ScanResult[]
  convention: string
}

const CONVENTIONS = [
  { value: 'avid', label: '番号命名 (推荐)' },
  { value: 'fnos', label: '飞牛 NAS (视频文件名)' },
  { value: 'jellyfin', label: 'Jellyfin 媒体库' },
  { value: 'kodi', label: 'Kodi 媒体库' },
  { value: 'standard', label: '标准 (通用)' },
]

const FIELD_LABELS: Record<string, string> = {
  video: '视频文件',
  nfo: 'NFO',
  poster: 'Poster',
  fanart: 'Fanart',
  poster_crop: 'Poster 需裁剪',
  poster_swap: '图放反了',
  fanart_crop: 'Fanart 需裁剪',
}

export default function Checker() {
  const { message } = App.useApp()
  const { lastRepairProgress, lastFixProgress, lastScanProgress } = useSocket()

  const [scanPath, setScanPath] = useState('')
  const [defaultPath, setDefaultPath] = useState('')
  const [convention] = useState('avid')
  const [scanning, setScanning] = useState(false)
  const [scanTaskId, setScanTaskId] = useState<string | null>(null)
  const [scanProgress, setScanProgress] = useState<{ dirs_scanned: number; total_dirs: number; current: string } | null>(null)
  const [scanData, setScanData] = useState<ScanData | null>(null)
  const [fromCache, setFromCache] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [showAll, setShowAll] = useState(false)

  // 搜索/筛选
  const [searchKeyword, setSearchKeyword] = useState('')
  const [timeFilterEnabled, setTimeFilterEnabled] = useState(false)
  const [filterType, setFilterType] = useState<'modified' | 'created'>('modified')
  const [timeAfter, setTimeAfter] = useState<dayjs.Dayjs | null>(null)
  const [timeBefore, setTimeBefore] = useState<dayjs.Dayjs | null>(null)

  // 修复/刮削
  const [fixConvention, setFixConvention] = useState('avid')
  const fixConventionRef = useRef('avid')
  // 同步 ref
  fixConventionRef.current = fixConvention
  const [repairTaskId, setRepairTaskId] = useState<string | null>(null)
  const [fixTaskId, setFixTaskId] = useState<string | null>(null)
  const [repairProgress, setRepairProgress] = useState<{ completed: number; total: number; current: string; status?: string } | null>(null)
  const [fixProgress, setFixProgress] = useState<{ completed: number; total: number; current: string; status?: string } | null>(null)
  const [taskHistory, setTaskHistory] = useState<any[]>([])
  const [actionLogs, setActionLogs] = useState<any[]>([])

  // 已完成修复/刮削的 video_path 集合
  const [completedPaths, setCompletedPaths] = useState<Set<string>>(new Set())

  // 图片方向筛选
  const [imageOrientationOnly, setImageOrientationOnly] = useState(false)

  // 已完成项自动从勾选中移除
  useEffect(() => {
    if (completedPaths.size > 0) {
      setSelectedKeys(prev => prev.filter(k => !completedPaths.has(k)))
    }
  }, [completedPaths])

  // 监听刮削进度
  useEffect(() => {
    if (!lastRepairProgress) return
    const p = lastRepairProgress
    if (p.task_id === repairTaskId) {
      if (p.status === 'completed') {
        // 先更新进度到 100%，延迟清除
        setRepairProgress({
          completed: p.total || p.completed || 0,
          total: p.total || 0,
          current: p.current || '',
          status: 'completed',
        })
        const sc = p.success || 0
        const fc = p.failed || 0
        if (fc > 0) {
          message.warning(`刮削完成: ${sc} 成功, ${fc} 失败`, 5)
        } else {
          message.success(`刮削完成: ${sc} 部影片`, 5)
        }
        setRepairTaskId(null)
        // 延迟清除进度条，让用户能看到完成状态
        const timer = setTimeout(() => setRepairProgress(null), 3000)
        // 逐个标记已修复的项
        fetchCheckerTaskDetail(p.task_id).then((res: any) => {
          if (res?.data?.success) {
            const fixed = res.data.success.map((s: any) => s.video_path)
            setCompletedPaths(prev => new Set([...prev, ...fixed]))
          }
        }).catch(() => {})
        loadTaskHistory()
        loadActionLogs()
        return () => clearTimeout(timer)
      } else {
        setRepairProgress({
          completed: p.completed || 0,
          total: p.total || 0,
          current: p.current || '',
          status: 'running',
        })
      }
    }
  }, [lastRepairProgress])

  // 监听修复进度
  useEffect(() => {
    if (!lastFixProgress) return
    const p = lastFixProgress
    if (p.task_id === fixTaskId) {
      if (p.status === 'completed') {
        setFixProgress({
          completed: p.total || p.completed || 0,
          total: p.total || 0,
          current: p.current || '',
          status: 'completed',
        })
        const sc = p.success || 0
        const fc = p.failed || 0
        if (fc > 0) {
          message.warning(`修复完成: ${sc} 成功, ${fc} 失败`, 5)
        } else {
          message.success(`修复完成: ${sc} 项`, 5)
        }
        setFixTaskId(null)
        const timer = setTimeout(() => setFixProgress(null), 3000)
        // 逐个标记已修复的项
        fetchCheckerTaskDetail(p.task_id).then((res: any) => {
          if (res?.data?.success) {
            const fixed = res.data.success.map((s: any) => s.video_path)
            setCompletedPaths(prev => new Set([...prev, ...fixed]))
          }
        }).catch(() => {})
        loadTaskHistory()
        loadActionLogs()
        return () => clearTimeout(timer)
      } else {
        setFixProgress({
          completed: p.completed || 0,
          total: p.total || 0,
          current: p.current || '',
          status: 'running',
        })
      }
    }
  }, [lastFixProgress])

  // 监听扫描进度
  useEffect(() => {
    if (!lastScanProgress) return
    const p = lastScanProgress
    if (p.task_id !== scanTaskId) return
    if (p.status === 'running') {
      setScanProgress({
        dirs_scanned: p.dirs_scanned || 0,
        total_dirs: p.total_dirs || 0,
        current: p.current || '',
      })
    } else if (p.status === 'completed') {
      setScanning(false)
      setScanTaskId(null)
      setScanProgress(null)
      if (p.data) {
        setScanData(p.data)
        setFromCache(false)
        message.success(p.message || '扫描完成')
      }
    } else if (p.status === 'failed') {
      setScanning(false)
      setScanTaskId(null)
      setScanProgress(null)
      message.error(p.message || '扫描失败')
    }
  }, [lastScanProgress])

  const loadTaskHistory = useCallback(async () => {
    try {
      const { data } = await fetchCheckerTasks()
      if (data?.data) {
        setTaskHistory(data.data.history || [])
      }
    } catch { /* ignore */ }
  }, [])

  const loadActionLogs = useCallback(async () => {
    try {
      const { data } = await fetchCheckerLogs()
      if (data?.data) {
        setActionLogs(data.data.logs || [])
      }
    } catch { /* ignore */ }
  }, [])

  // 加载默认路径并尝试读取缓存
  useEffect(() => {
    fetchCheckerDefaultPath().then(({ data }: any) => {
      const p = data?.default_path || ''
      if (p) {
        setDefaultPath(p)
        setScanPath(p)
        // 自动尝试加载缓存
        fetchCheckerScanCache(p).then((cacheRes: any) => {
          if (cacheRes.code === 0 && cacheRes.data) {
            setScanData(cacheRes.data)
            setFromCache(true)
          }
        }).catch(() => {})
      }
    }).catch(() => {})
    loadTaskHistory()
    loadActionLogs()
  }, [])

  const ORIENTATION_FIELDS = ['poster_crop', 'poster_swap', 'fanart_crop']

  const displayedResults = useMemo(() => {
    let list = (scanData?.results || [])
    // 按状态筛选
    if (!showAll) {
      list = list.filter(r => r.mismatch_fields.length > 0)
    }
    // 按关键词搜索（番号、文件名）
    if (searchKeyword.trim()) {
      const kw = searchKeyword.trim().toLowerCase()
      list = list.filter(r =>
        (r.avid && r.avid.toLowerCase().includes(kw)) ||
        r.video_basename.toLowerCase().includes(kw) ||
        r.video_path.toLowerCase().includes(kw)
      )
    }
    // 按创建时间筛选
    if (timeFilterEnabled && (timeAfter || timeBefore)) {
      list = list.filter(r => {
        if (!r.created_time) return false
        const ts = r.created_time * 1000 // 秒转毫秒
        if (timeAfter && ts < timeAfter.valueOf()) return false
        if (timeBefore && ts > timeBefore.valueOf()) return false
        return true
      })
    }
    // 图片方向筛选（已修复的从列表中移除）
    if (imageOrientationOnly) {
      list = list.filter(r => r.mismatch_fields.some(f => ORIENTATION_FIELDS.includes(f)) && !completedPaths.has(r.video_path))
    }
    return list
  }, [scanData, showAll, searchKeyword, timeFilterEnabled, timeAfter, timeBefore, imageOrientationOnly, completedPaths])

  const handleScan = useCallback(async (forceRefresh = false) => {
    if (!scanPath.trim()) {
      message.warning('请输入扫描路径')
      return
    }
    setSelectedKeys([])
    setSelectedDupAvids(new Set())
    setCompletedPaths(new Set())
    // 先尝试加载缓存
    if (!forceRefresh) {
      try {
        const cacheRes: any = await fetchCheckerScanCache(scanPath.trim())
        if (cacheRes.code === 0 && cacheRes.data) {
          setScanData(cacheRes.data)
          setFromCache(true)
          message.success('已加载缓存结果，点击"重新扫描"可刷新')
          return
        }
      } catch { /* ignore, fallback to new scan */ }
    }
    setScanning(true)
    setScanData(null)
    setFromCache(false)
    setScanProgress({ dirs_scanned: 0, total_dirs: 0, current: '' })
    try {
      const reqParams: any = { path: scanPath.trim(), convention }
      if (timeFilterEnabled) {
        if (timeAfter) reqParams[`${filterType}_after`] = timeAfter.toISOString()
        if (timeBefore) reqParams[`${filterType}_before`] = timeBefore.toISOString()
      }
      const res: any = await fetchCheckerScan(reqParams)
      if (res.code === 0) {
        setScanTaskId(res.data.task_id)
        message.info('扫描任务已创建，正在后台扫描...')
      } else {
        message.error(res.message)
        setScanning(false)
        setScanProgress(null)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '扫描失败')
      setScanning(false)
      setScanProgress(null)
    }
  }, [scanPath, convention, timeFilterEnabled, filterType, timeAfter, timeBefore, message])

  // 批量修复（重命名视频文件 + 配套文件）
  const handleFix = useCallback(async () => {
    // 只选中需要修复命名的项（排除需要刮削和只需图片方向修复的）
    const renamable = (scanData?.results || [])
      .filter(r => selectedKeys.includes(r.video_path))
      .filter(r => !completedPaths.has(r.video_path))
      .filter(r => needsFix(r))

    if (renamable.length === 0) {
      message.warning('选中项中没有需要修复命名的')
      return
    }

    const items = renamable.map(r => ({
      video_path: r.video_path,
      nfo_path: r.nfo_path,
      poster_path: r.poster_path,
      fanart_path: r.fanart_path,
      mismatch_fields: r.mismatch_fields.filter(f => !ORIENTATION_FIELDS.includes(f)),
    }))

    const selectedLabel = CONVENTIONS.find(c => c.value === fixConventionRef.current)?.label || fixConventionRef.current

    Modal.confirm({
      title: '确认批量修复',
      width: 520,
      content: (
        <div>
          <p>将对选中的 <b>{items.length}</b> 项按 <b style={{ color: '#1890ff' }}>{selectedLabel}</b> 标准修复：</p>
          <ul>
            <li>重命名视频文件为番号</li>
            <li>修正 .nfo / poster / fanart 文件名</li>
          </ul>
          {renamable.length < selectedKeys.length && (
            <p style={{ color: '#faad14' }}>已自动跳过 {selectedKeys.length - renamable.length} 个无法识别番号的项目</p>
          )}
          <div style={{ marginTop: 12 }}>
            <span style={{ marginRight: 12 }}>目标标准：</span>
            <Radio.Group
              defaultValue={fixConventionRef.current}
              onChange={(e) => { fixConventionRef.current = e.target.value }}
              optionType="button"
              size="small"
            >
              {CONVENTIONS.map(c => (
                <Radio.Button key={c.value} value={c.value}>{c.label}</Radio.Button>
              ))}
            </Radio.Group>
          </div>
          <p style={{ color: '#faad14', marginTop: 12 }}>此操作将重命名文件，确认继续？</p>
        </div>
      ),
      okText: '确认修复',
      cancelText: '取消',
      onOk: async () => {
        setFixConvention(fixConventionRef.current)
        try {
          const res = await fixCheckerIssues(items, fixConventionRef.current)
          if (res.code === 0) {
            setFixTaskId(res.data.task_id)
            setFixProgress({ completed: 0, total: items.length, current: '' })
            message.info(res.message)
          } else {
            message.error(res.message)
          }
        } catch (e: any) {
          message.error(e.response?.data?.message || '修复失败')
        }
      },
    })
  }, [scanData, selectedKeys, message, handleScan])

  // 单行刮削
  const handleRepairSingle = useCallback(async (videoPath: string) => {
    Modal.confirm({
      title: '重新刮削',
      content: '重新抓取元数据 + 下载封面，覆盖已有文件。后台异步执行。',
      okText: '刮削',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await repairChecker([videoPath])
          if (res.code === 0) {
            setRepairTaskId(res.data.task_id)
            setRepairProgress({ completed: 0, total: 1, current: '' })
            message.info(res.message)
          } else {
            message.error(res.message)
          }
        } catch (e: any) {
          message.error(e.response?.data?.message || '刮削失败')
        }
      },
    })
  }, [message])

  // 计算重复番号组（相同 avid 即为重复，-C/-U/-UC 也属于同一番号）
  const [selectedDupAvids, setSelectedDupAvids] = useState<Set<string>>(new Set())

  const duplicateGroups = (() => {
    if (!scanData) return [] as { avid: string; files: string[]; key: string }[]
    const map = new Map<string, string[]>()
    for (const r of scanData.results) {
      if (!r.avid) continue
      const arr = map.get(r.avid) || []
      arr.push(r.video_path)
      map.set(r.avid, arr)
    }
    return [...map.entries()]
      .filter(([_, files]) => files.length > 1)
      .map(([avid, files]) => ({ avid, files, key: avid }))
  })()

  const handleMerge = useCallback(async (avid: string, videoPaths: string[]) => {
    Modal.confirm({
      title: `合并重复番号: ${avid}`,
      content: (
        <div>
          <p>发现番号 <b>{avid}</b> 有 <b>{videoPaths.length}</b> 个文件：</p>
          <ul>
            {videoPaths.map((p, i) => <li key={i}>{p.split('/').pop()}</li>)}
          </ul>
          <p>将按 <b>-UC(无修正) &gt; -C(字幕) &gt; -U(普通) &gt; 文件大小</b> 优先保留最佳，其余<b>直接删除</b>。</p>
        </div>
      ),
      okText: '合并',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await mergeCheckerDuplicates(videoPaths)
          if (res.code === 0) {
            message.success(res.message, 5)
            loadActionLogs()
            const kept = res.data.kept
            const deleted = res.data.deleted || []
            const deletedSet = new Set<string>(deleted
              .map((d: any) => videoPaths.find((vp: string) => vp.endsWith(d.path)) || '')
              .filter(Boolean))
            setCompletedPaths(prev => new Set([...prev, kept, ...deletedSet]))
            // 有实际删除：移除被删行；无删除（已被之前操作处理）：移除多余的旧行
            const removeSet = deletedSet.size > 0 ? deletedSet :
              new Set(videoPaths.filter((vp: string) => vp !== kept))
            if (scanData && removeSet.size > 0) {
              setScanData({
                ...scanData,
                results: scanData.results.filter(r => !removeSet.has(r.video_path)),
                total: scanData.total - removeSet.size,
                mismatch_count: scanData.mismatch_count - removeSet.size,
              })
            }
          } else {
            message.error(res.message)
          }
        } catch (e: any) {
          message.error(e.response?.data?.message || '合并失败')
        }
      },
    })
  }, [message, scanData])

  const handleBatchMerge = useCallback(async () => {
    const groups = duplicateGroups.filter(g => selectedDupAvids.has(g.avid))
    if (groups.length === 0) {
      message.warning('请选择要合并的重复番号')
      return
    }
    const totalFiles = groups.reduce((sum, g) => sum + g.files.length - 1, 0)
    Modal.confirm({
      title: `批量合并 ${groups.length} 个重复番号`,
      content: (
        <div>
          <p>将对 <b>{groups.length}</b> 个番号进行合并，共删除 <b>{totalFiles}</b> 个多余文件。</p>
          <p style={{ color: '#faad14' }}>按 -UC &gt; -C &gt; -U &gt; 文件大小 优先保留最佳。</p>
        </div>
      ),
      okText: '合并',
      cancelText: '取消',
      onOk: async () => {
        for (const g of groups) {
          try {
            const res = await mergeCheckerDuplicates(g.files)
            if (res.code === 0) {
              const kept = res.data.kept
              const deleted = res.data.deleted || []
              const deletedPaths: string[] = deleted
                .map((d: any) => g.files.find((vp: string) => vp.endsWith(d.path)) || '')
                .filter(Boolean)
              // 标记保留文件和已删除文件为已完成
              const allDone = new Set<string>([kept, ...deletedPaths])
              setCompletedPaths(prev => new Set([...prev, ...allDone]))
              if (scanData && deletedPaths.length > 0) {
                const ds = new Set(deletedPaths)
                setScanData(prev => prev ? {
                  ...prev,
                  results: prev.results.filter(r => !ds.has(r.video_path)),
                  total: prev.total - ds.size,
                  mismatch_count: prev.mismatch_count - ds.size,
                } : null)
              } else if (deleted.length === 0 && g.files.length > 1) {
                // 服务器返回空删除（已被之前操作处理），从表格移除多余行
                const others = new Set(g.files.filter((f: string) => f !== kept))
                setScanData(prev => prev ? {
                  ...prev,
                  results: prev.results.filter(r => !others.has(r.video_path)),
                  total: prev.total - others.size,
                  mismatch_count: prev.mismatch_count - others.size,
                } : null)
              }
            }
          } catch { /* continue */ }
        }
        loadActionLogs()
        message.success(`合并完成: ${groups.length} 个番号`, 5)
        setSelectedDupAvids(new Set())
      },
    })
  }, [duplicateGroups, selectedDupAvids, message, scanData])

  const toggleAllDups = () => {
    if (selectedDupAvids.size === duplicateGroups.length) {
      setSelectedDupAvids(new Set())
    } else {
      setSelectedDupAvids(new Set(duplicateGroups.map(g => g.avid)))
    }
  }

  const toggleAllMismatched = () => {
    const mismatched = (scanData?.results || [])
      .filter(r => r.mismatch_fields.length > 0)
      .filter(r => !completedPaths.has(r.video_path))
      .map(r => r.video_path)
    setSelectedKeys(selectedKeys.length === mismatched.length ? [] : mismatched)
  }

  const renderMatch = (current: string | null, expected: string) => {
    if (!current) return <Tag color="red">缺失</Tag>
    if (current === expected) {
      return <span style={{ color: '#52c41a', wordBreak: 'break-all' }}>{current}</span>
    }
    return (
      <div>
        <div style={{ color: '#ff4d4f', textDecoration: 'line-through', wordBreak: 'break-all' }}>
          {current}
        </div>
        <div style={{ color: '#52c41a', fontSize: 12, wordBreak: 'break-all' }}>
          → {expected}
        </div>
      </div>
    )
  }

  // 计算每个 avid 的重复数
  const dupCountMap = new Map<string, number>()
  if (scanData) {
    for (const r of scanData.results) {
      if (!r.avid) continue
      dupCountMap.set(r.avid, (dupCountMap.get(r.avid) || 0) + 1)
    }
  }

  const columns = [
    {
      title: '视频文件',
      dataIndex: 'video_basename',
      key: 'video',
      width: 240,
      ellipsis: true,
      render: (_: string, record: ScanResult) => (
        <div>
          <div style={{ fontWeight: 500, wordBreak: 'break-all' }}>{record.video_basename}</div>
          {record.video_needs_rename && record.expected_video_name && (
            <div style={{ fontSize: 12, color: '#faad14' }}>
              → {record.expected_video_name}
            </div>
          )}
          {!record.video_needs_rename && (
            <div style={{ fontSize: 12, color: '#888' }}>
              {(() => { const ps = record.video_path; return ps.substring(ps.lastIndexOf('/') + 1) || ps.substring(ps.lastIndexOf('\\') + 1) })()}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '番号',
      dataIndex: 'avid',
      key: 'avid',
      width: 120,
      render: (avid: string, record: ScanResult) => {
        if (!avid) return <Tag color="red">未识别</Tag>
        return (
          <div>
            <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{avid}</span>
            {record.avid_source && (
              <div style={{ fontSize: 11, color: '#888' }}>
                来源: {record.avid_source === 'filename' ? '文件名' : record.avid_source === 'nfo' ? 'NFO' : '路径'}
              </div>
            )}
          </div>
        )
      },
    },
    {
      title: '重复',
      key: 'merge',
      width: 80,
      render: (_: any, record: ScanResult) => {
        const cnt = dupCountMap.get(record.avid) || 1
        if (cnt <= 1) return null
        if (completedPaths.has(record.video_path)) return <Typography.Text type="secondary">已合并</Typography.Text>
        const dupFiles = (scanData?.results || []).filter(r => r.avid === record.avid).map(r => r.video_path)
        return (
          <Button
            type="link"
            size="small"
            danger
            disabled={repairTaskId !== null || fixTaskId !== null}
            onClick={() => handleMerge(record.avid, dupFiles)}
          >
            {cnt}个文件
          </Button>
        )
      },
    },
    {
      title: '创建时间',
      key: 'created_time',
      width: 150,
      render: (_: any, record: ScanResult) => {
        if (!record.created_time) return <Typography.Text type="secondary">-</Typography.Text>
        const cnt = dupCountMap.get(record.avid) || 1
        if (cnt > 1) {
          const dupFiles = (scanData?.results || []).filter(r => r.avid === record.avid && r.avid)
          return (
            <div style={{ fontSize: 12 }}>
              {dupFiles.map((r, i) => (
                <div key={i} style={{ color: r.video_path === record.video_path ? '#1890ff' : '#888' }}>
                  {r.created_time ? dayjs(r.created_time * 1000).format('YY-MM-DD HH:mm') : '-'}
                  <span style={{ color: '#bbb', marginLeft: 4 }}>{r.video_basename.substring(0, 8)}...</span>
                </div>
              ))}
            </div>
          )
        }
        return dayjs(record.created_time * 1000).format('YY-MM-DD HH:mm')
      },
    },
    {
      title: 'NFO',
      key: 'nfo',
      width: 200,
      ellipsis: true,
      render: (_: any, record: ScanResult) => renderMatch(
        record.nfo_basename ? record.nfo_basename + '.nfo' : null,
        record.expected_nfo_name
      ),
    },
    {
      title: 'Poster',
      key: 'poster',
      width: 180,
      ellipsis: true,
      render: (_: any, record: ScanResult) => renderMatch(
        record.poster_basename || null,
        record.expected_poster_name
      ),
    },
    {
      title: 'Fanart',
      key: 'fanart',
      width: 180,
      ellipsis: true,
      render: (_: any, record: ScanResult) => renderMatch(
        record.fanart_basename || null,
        record.expected_fanart_name
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 130,
      render: (_: any, record: ScanResult) => {
        if (completedPaths.has(record.video_path)) {
          return <Tag icon={<CheckCircleOutlined />} color="success">已处理</Tag>
        }
        if (record.mismatch_fields.length === 0) {
          return <Tag icon={<CheckCircleOutlined />} color="success">正常</Tag>
        }
        return (
          <Space size={[2, 2]} wrap>
            {record.mismatch_fields.map(f => {
              const isOrientation = ORIENTATION_FIELDS.includes(f)
              const label = isOrientation && record.image_orientation_issue ? record.image_orientation_issue : (FIELD_LABELS[f] || f)
              return (
                <Tag key={f} color={isOrientation ? 'warning' : (record.issues.some(i => i.includes('可重新')) && !record[`${f}_path` as keyof ScanResult] ? 'red' : 'orange')} style={{ fontSize: 11 }}>
                  {label}
                </Tag>
              )
            })}
          </Space>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: any, record: ScanResult) => {
        if (completedPaths.has(record.video_path)) return <Typography.Text type="secondary">已完成</Typography.Text>
        const rowNeedsScrape = record.avid && (!record.nfo_path || !record.poster_path || !record.fanart_path)
        const rowNeedsFix = !rowNeedsScrape && record.avid && record.mismatch_fields.filter(f => !ORIENTATION_FIELDS.includes(f)).length > 0
        const rowNeedsCrop = !rowNeedsScrape && !rowNeedsFix && record.mismatch_fields.some(f => ORIENTATION_FIELDS.includes(f))
        return (
          <Space size={0}>
            {rowNeedsScrape && (
              <Tooltip title="刮削">
                <Button
                  type="link"
                  size="small"
                  icon={<CloudDownloadOutlined />}
                  disabled={repairTaskId !== null}
                  onClick={() => handleRepairSingle(record.video_path)}
                />
              </Tooltip>
            )}
            {rowNeedsFix && (
              <Tooltip title="修复命名">
                <Button
                  type="link"
                  size="small"
                  icon={<ThunderboltOutlined />}
                  disabled={fixTaskId !== null}
                  onClick={() => {
                    Modal.confirm({
                      title: '修复命名',
                      content: '将重命名视频文件为番号，并修正配套文件名称。',
                      okText: '修复',
                      cancelText: '取消',
                      onOk: async () => {
                        const items = [{
                          video_path: record.video_path,
                          nfo_path: record.nfo_path,
                          poster_path: record.poster_path,
                          fanart_path: record.fanart_path,
                          mismatch_fields: record.mismatch_fields.filter(f => !ORIENTATION_FIELDS.includes(f)),
                        }]
                        try {
                          const res = await fixCheckerIssues(items, fixConvention)
                          if (res.code === 0) {
                            setFixTaskId(res.data.task_id)
                            setFixProgress({ completed: 0, total: 1, current: '' })
                            message.info(res.message)
                          } else {
                            message.error(res.message)
                          }
                        } catch (e: any) {
                          message.error(e.response?.data?.message || '修复失败')
                        }
                      },
                    })
                  }}
                />
              </Tooltip>
            )}
            {rowNeedsCrop && (
              <Tooltip title="修复图片方向">
                <Button
                  type="link"
                  size="small"
                  icon={<ThunderboltOutlined />}
                  disabled={fixTaskId !== null}
                  onClick={() => {
                    Modal.confirm({
                      title: '修复图片方向',
                      content: record.image_orientation_issue || '重新裁剪或交换图片方向',
                      okText: '修复',
                      cancelText: '取消',
                      onOk: async () => {
                        const items = [{
                          video_path: record.video_path,
                          nfo_path: record.nfo_path,
                          poster_path: record.poster_path,
                          fanart_path: record.fanart_path,
                          mismatch_fields: record.mismatch_fields.filter(f => ORIENTATION_FIELDS.includes(f)),
                        }]
                        try {
                          const res = await fixCheckerIssues(items, fixConvention)
                          if (res.code === 0) {
                            setFixTaskId(res.data.task_id)
                            setFixProgress({ completed: 0, total: 1, current: '' })
                            message.info(res.message)
                          } else {
                            message.error(res.message)
                          }
                        } catch (e: any) {
                          message.error(e.response?.data?.message || '修复失败')
                        }
                      },
                    })
                  }}
                />
              </Tooltip>
            )}
            <Tooltip title="重新刮削">
              <Button
                type="link"
                size="small"
                icon={<CloudDownloadOutlined />}
                disabled={repairTaskId !== null}
                onClick={() => handleRepairSingle(record.video_path)}
              />
            </Tooltip>
          </Space>
        )
      },
    },
  ]

  const rowSelection = {
    selectedRowKeys: selectedKeys,
    onChange: (keys: React.Key[]) => setSelectedKeys(keys as string[]),
    getCheckboxProps: (record: ScanResult) => ({
      disabled: completedPaths.has(record.video_path),
    }),
  }

  // 需要刮削的项：缺少 NFO 或缺少封面（文件不存在）
  const needsScrape = useCallback((r: ScanResult) => {
    return r.avid && (!r.nfo_path || !r.poster_path || !r.fanart_path)
  }, [])

  // 需要修复命名的项（有文件但命名不对，且不需要刮削）
  const needsFix = useCallback((r: ScanResult) => {
    if (needsScrape(r)) return false
    const fixFields = r.mismatch_fields.filter(f => !ORIENTATION_FIELDS.includes(f))
    return r.avid && fixFields.length > 0
  }, [needsScrape])

  // 需要图片方向修复的项（命名正确，只有方向问题）
  const needsCrop = useCallback((r: ScanResult) => {
    if (needsScrape(r)) return false
    if (needsFix(r)) return false
    return r.mismatch_fields.some(f => ORIENTATION_FIELDS.includes(f))
  }, [needsScrape, needsFix])

  // 各按钮可操作数量（互斥）
  const selectedUncompleted = (scanData?.results || [])
    .filter(r => selectedKeys.includes(r.video_path))
    .filter(r => !completedPaths.has(r.video_path))

  const scrapeableCount = selectedUncompleted.filter(r => needsScrape(r)).length
  const fixableCount = selectedUncompleted.filter(r => needsFix(r)).length
  const cropFixableCount = (scanData?.results || [])
    .filter(r => !completedPaths.has(r.video_path))
    .filter(r => needsCrop(r))
    .length

  // 刮削按钮（选中项中需要刮削的）
  const handleBatchRepairFiltered = useCallback(async () => {
    const paths = selectedUncompleted.filter(r => needsScrape(r)).map(r => r.video_path)
    if (paths.length === 0) {
      message.warning('选中项中没有需要刮削的（缺少 NFO 或封面）')
      return
    }
    Modal.confirm({
      title: '确认批量刮削',
      content: (
        <div>
          <p>将对 <b>{paths.length}</b> 部影片重新抓取元数据并下载封面，覆盖已有文件。</p>
          <p style={{ color: '#faad14' }}>此操作在后台异步执行，右上角会在完成后收到通知。</p>
        </div>
      ),
      okText: '开始刮削',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await repairChecker(paths)
          if (res.code === 0) {
            setRepairTaskId(res.data.task_id)
            setRepairProgress({ completed: 0, total: paths.length, current: '' })
            message.info(res.message)
          } else {
            message.error(res.message)
          }
        } catch (e: any) {
          message.error(e.response?.data?.message || '刮削失败')
        }
      },
    })
  }, [selectedUncompleted, needsScrape, message])

  // 一键修复图片方向
  const handleCropFix = useCallback(async () => {
    const items = (scanData?.results || [])
      .filter(r => !completedPaths.has(r.video_path))
      .filter(r => r.mismatch_fields.some(f => ORIENTATION_FIELDS.includes(f)) && r.avid)
      .map(r => ({
        video_path: r.video_path,
        nfo_path: r.nfo_path,
        poster_path: r.poster_path,
        fanart_path: r.fanart_path,
        mismatch_fields: r.mismatch_fields.filter(f => ORIENTATION_FIELDS.includes(f)),
      }))
    if (items.length === 0) {
      message.warning('没有需要修复图片方向的项')
      return
    }
    Modal.confirm({
      title: '一键修复图片方向',
      content: `将对 ${items.length} 项的 poster 重新裁剪为竖图（从已有 fanart 裁剪）。`,
      okText: '修复',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await fixCheckerIssues(items, fixConventionRef.current)
          if (res.code === 0) {
            setFixTaskId(res.data.task_id)
            setFixProgress({ completed: 0, total: items.length, current: '' })
            message.info(res.message)
          } else {
            message.error(res.message)
          }
        } catch (e: any) {
          message.error(e.response?.data?.message || '修复失败')
        }
      },
    })
  }, [scanData, completedPaths, message])

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <ToolOutlined /> 文件命名检查
      </Typography.Title>

      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* 扫描输入区 */}
        <Card variant="borderless">
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {/* 路径输入 */}
            <Space.Compact style={{ width: '100%' }}>
              <Input
                prefix={<FolderOutlined />}
                placeholder={defaultPath || '输入要扫描的目录路径...'}
                value={scanPath}
                onChange={(e) => setScanPath(e.target.value)}
                onPressEnter={() => handleScan(true)}
                style={{ fontFamily: 'monospace' }}
                suffix={
                  defaultPath && scanPath !== defaultPath ? (
                    <Button type="link" size="small" onClick={() => setScanPath(defaultPath)}>恢复默认</Button>
                  ) : undefined
                }
              />
              <Button type="primary" icon={<SearchOutlined />} onClick={() => handleScan(true)} loading={scanning}>
                扫描
              </Button>
            </Space.Compact>

            {/* 时间筛选 */}
            <Collapse
              ghost
              size="small"
              items={[{
                key: 'filter',
                label: (
                  <Space>
                    <FilterOutlined />
                    <span>时间筛选</span>
                    {timeFilterEnabled && (
                      <Tag color="blue" style={{ marginLeft: 8 }}>
                        {filterType === 'modified' ? '修改时间' : '创建时间'}
                        {timeAfter ? ` ≥ ${timeAfter.format('MM-DD HH:mm')}` : ''}
                        {timeBefore ? ` ≤ ${timeBefore.format('MM-DD HH:mm')}` : ''}
                      </Tag>
                    )}
                  </Space>
                ),
                children: (
                  <Space wrap align="center">
                    <Checkbox checked={timeFilterEnabled} onChange={(e) => setTimeFilterEnabled(e.target.checked)}>
                      启用
                    </Checkbox>
                    <Select
                      value={filterType}
                      onChange={(v) => setFilterType(v)}
                      style={{ width: 120 }}
                      options={[
                        { value: 'modified', label: '按修改时间' },
                        { value: 'created', label: '按创建时间' },
                      ]}
                      disabled={!timeFilterEnabled}
                    />
                    <DatePicker
                      showTime
                      placeholder="开始时间"
                      value={timeAfter}
                      onChange={setTimeAfter}
                      disabled={!timeFilterEnabled}
                      style={{ width: 200 }}
                    />
                    <span style={{ color: '#888' }}>至</span>
                    <DatePicker
                      showTime
                      placeholder="结束时间"
                      value={timeBefore}
                      onChange={setTimeBefore}
                      disabled={!timeFilterEnabled}
                      style={{ width: 200 }}
                    />
                    {timeFilterEnabled && (
                      <Space size={4}>
                        <Button
                          size="small"
                          type="link"
                          onClick={() => { setTimeAfter(dayjs().subtract(1, 'month')); setTimeBefore(null) }}
                        >
                          近一个月
                        </Button>
                        <Button size="small" onClick={() => { setTimeAfter(null); setTimeBefore(null); setTimeFilterEnabled(false) }}>
                          清除
                        </Button>
                      </Space>
                    )}
                  </Space>
                ),
              }]}
            />
          </Space>
        </Card>

        {/* 扫描进度条 */}
        {scanProgress && (
          <Card variant="borderless" size="small" title={<span><SearchOutlined /> 扫描中...</span>}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <span>已扫描 {scanProgress.dirs_scanned}{scanProgress.total_dirs > 0 ? ` / ${scanProgress.total_dirs}` : ''} 个目录</span>
              {scanProgress.current && (
                <Typography.Text type="secondary" ellipsis style={{ maxWidth: '100%' }}>
                  {scanProgress.current}
                </Typography.Text>
              )}
              <Progress
                status="active"
                percent={scanProgress.total_dirs > 0 ? Math.round((scanProgress.dirs_scanned / scanProgress.total_dirs) * 100) : 0}
                showInfo={scanProgress.total_dirs > 0}
              />
            </Space>
          </Card>
        )}
        {/* 刮削进度条 */}
        {repairProgress && (
          <Card variant="borderless" size="small" title={<span><CloudDownloadOutlined /> 刮削任务</span>}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <span>{repairProgress.status === 'completed' ? '刮削完成' : `正在刮削: ${repairProgress.current}`}</span>
              <Progress
                status={repairProgress.status === 'completed' ? 'success' : 'active'}
                percent={Math.round((repairProgress.completed / (repairProgress.total || 1)) * 100)}
              />
              <Typography.Text type="secondary">{repairProgress.completed}/{repairProgress.total}</Typography.Text>
            </Space>
          </Card>
        )}
        {/* 修复进度条 */}
        {fixProgress && (
          <Card variant="borderless" size="small" title={<span><ThunderboltOutlined /> 修复任务</span>}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <span>{fixProgress.status === 'completed' ? '修复完成' : `正在修复: ${fixProgress.current}`}</span>
              <Progress
                status={fixProgress.status === 'completed' ? 'success' : 'active'}
                percent={Math.round((fixProgress.completed / (fixProgress.total || 1)) * 100)}
              />
              <Typography.Text type="secondary">{fixProgress.completed}/{fixProgress.total}</Typography.Text>
            </Space>
          </Card>
        )}

        {/* 重复番号提示 */}
        {duplicateGroups.length > 0 && (
          <Card
            variant="borderless"
            size="small"
            title={
              <Space>
                <span>重复番号</span>
                <Tag color="warning">{duplicateGroups.length} 组</Tag>
              </Space>
            }
            extra={
              <Space>
                <Checkbox
                  checked={selectedDupAvids.size === duplicateGroups.length}
                  indeterminate={selectedDupAvids.size > 0 && selectedDupAvids.size < duplicateGroups.length}
                  onChange={toggleAllDups}
                >
                  全选
                </Checkbox>
                <Button
                  type="primary"
                  danger
                  size="small"
                  disabled={selectedDupAvids.size === 0}
                  onClick={handleBatchMerge}
                >
                  批量合并 ({selectedDupAvids.size})
                </Button>
              </Space>
            }
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              {duplicateGroups.map((g) => (
                <div key={g.avid} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Checkbox
                    style={{ marginRight: 4 }}
                    checked={selectedDupAvids.has(g.avid)}
                    onChange={(e) => {
                      setSelectedDupAvids(prev => {
                        const next = new Set(prev)
                        e.target.checked ? next.add(g.avid) : next.delete(g.avid)
                        return next
                      })
                    }}
                  />
                  <Tag color="blue">{g.avid}</Tag>
                  <Space size={4} wrap style={{ flex: 1 }}>
                    {g.files.map((f, i) => (
                      <Tag key={i} style={{ fontSize: 11 }}>{f.split('/').pop()}</Tag>
                    ))}
                  </Space>
                  <Button size="small" onClick={() => handleMerge(g.avid, g.files)}>单个合并</Button>
                </div>
              ))}
            </Space>
          </Card>
        )}

        {/* 结果区域 */}
        {scanData && (
          <Card
            variant="borderless"
            title={
              <Space>
                <span>扫描结果</span>
                {fromCache && <Tag color="orange">缓存</Tag>}
                <Tag color="blue">{scanData.path}</Tag>
                <Tag color="success">{scanData.ok_count} 正常</Tag>
                {scanData.mismatch_count > 0 && (
                  <Tag color="error">{scanData.mismatch_count} 不匹配</Tag>
                )}
              </Space>
            }
            extra={
              <Space wrap>
                <Input.Search
                  placeholder="搜索番号、文件名"
                  allowClear
                  style={{ width: 220 }}
                  onSearch={(v) => setSearchKeyword(v)}
                  onChange={(e) => { if (!e.target.value) setSearchKeyword('') }}
                />
                <Checkbox checked={showAll} onChange={(e) => setShowAll(e.target.checked)}>
                  显示全部
                </Checkbox>
                <Checkbox
                  checked={selectedKeys.length > 0 && selectedKeys.length === (scanData.results.filter(r => r.mismatch_fields.length > 0).length)}
                  indeterminate={selectedKeys.length > 0 && selectedKeys.length < (scanData.results.filter(r => r.mismatch_fields.length > 0).length)}
                  onChange={toggleAllMismatched}
                >
                  全选不匹配项
                </Checkbox>
                <Checkbox checked={imageOrientationOnly} onChange={(e) => setImageOrientationOnly(e.target.checked)}>
                  仅显示图片方向问题
                </Checkbox>
                <Button
                  type="primary"
                  danger
                  icon={<CloudDownloadOutlined />}
                  onClick={handleBatchRepairFiltered}
                  loading={repairTaskId !== null}
                  disabled={scrapeableCount === 0}
                >
                  刮削 ({scrapeableCount})
                </Button>
                <Button
                  icon={<ThunderboltOutlined />}
                  onClick={handleFix}
                  loading={fixTaskId !== null}
                  disabled={fixableCount === 0}
                >
                  修复命名 ({fixableCount})
                </Button>
                <Button
                  icon={<ThunderboltOutlined />}
                  onClick={handleCropFix}
                  loading={fixTaskId !== null}
                  disabled={cropFixableCount === 0}
                >
                  修复图片方向 ({cropFixableCount})
                </Button>
              </Space>
            }
          >
            <Table
              dataSource={displayedResults}
              columns={columns}
              rowKey="video_path"
              rowSelection={rowSelection}
              rowClassName={(record: ScanResult) => completedPaths.has(record.video_path) ? 'checker-row-completed' : ''}
              loading={scanning}
              pagination={{ defaultPageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 200, 500], showTotal: (t) => `共 ${t} 项` }}
              size="small"
              scroll={{ x: 1000 }}
              locale={{ emptyText: <Empty description={scanning ? '扫描中...' : '所有文件命名正常'} /> }}
            />
          </Card>
        )}

        {/* 操作日志卡片 */}
        {actionLogs.length > 0 && (
          <Card variant="borderless" size="small" title="操作日志">
            <Table
              dataSource={actionLogs.slice(0, 20)}
              rowKey={(r, i) => `${r.time}-${i}`}
              size="small"
              pagination={false}
              columns={[
                { title: '番号', dataIndex: 'avid', width: 100, render: (a: string) => a ? <Tag>{a}</Tag> : null },
                {
                  title: '操作', width: 60,
                  render: (_: any, r: any) => (
                    <Tag color={r.type === 'merge' ? 'red' : r.type === 'fix' ? 'blue' : 'purple'}>
                      {r.type === 'merge' ? '合并' : r.type === 'fix' ? '修复' : '刮削'}
                    </Tag>
                  ),
                },
                { title: '详情', ellipsis: true, render: (_: any, r: any) => {
                  if (r.error) return <Typography.Text type="danger">{r.error}</Typography.Text>
                  return <Space size={2}>{r.actions?.map((a: any, i: number) => (
                    <Tag key={i} color={a.deleted ? 'red' : 'green'} style={{ fontSize: 11 }}>
                      {a.deleted ? `删:${a.deleted}` : a.to ? `${a.type}:${a.to}` : a.kept ? `保留:${a.kept}` : ''}
                    </Tag>
                  ))}</Space>
                }},
                { title: '时间', width: 150, render: (_: any, r: any) => dayjs(r.time * 1000).format('HH:mm:ss') },
              ]}
            />
          </Card>
        )}

        {/* 任务历史卡片 */}
        {taskHistory.length > 0 && (
          <Card variant="borderless" size="small" title="最近任务">
            <Table
              dataSource={taskHistory.slice(0, 5)}
              rowKey="task_id"
              size="small"
              pagination={false}
              columns={[
                { title: '类型', dataIndex: 'type', width: 80, render: (t: string) => <Tag color={t === 'fix' ? 'blue' : 'purple'}>{t === 'fix' ? '修复' : '刮削'}</Tag> },
                { title: '状态', width: 80, render: (_: any, r: any) => <Tag color={r.status === 'completed' ? 'success' : 'default'}>{r.status === 'completed' ? '完成' : r.status}</Tag> },
                { title: '结果', width: 150, render: (_: any, r: any) => `${r.success_count} 成功 / ${r.failed_count} 失败` },
                { title: '时间', dataIndex: 'end_time', width: 170, render: (t: number) => dayjs(t * 1000).format('MM-DD HH:mm:ss') },
                {
                  title: '明细', width: 70,
                  render: (_: any, r: any) => (
                    <Button type="link" size="small" onClick={() => {
                      Modal.info({
                        title: `${r.type === 'fix' ? '修复' : '刮削'} 任务明细`,
                        width: 600,
                        content: (
                          <div>
                            {r.success && r.success.length > 0 && (
                              <div>
                                <Typography.Text strong style={{ color: '#52c41a' }}>成功 ({r.success.length}):</Typography.Text>
                                <ul style={{ maxHeight: 200, overflow: 'auto', margin: '8px 0', paddingLeft: 20 }}>
                                  {r.success.map((s: any, i: number) => (
                                    <li key={i}>
                                      <code>{s.avid || s.video_path?.split('/').pop()}</code>
                                      {s.actions?.map((a: any, j: number) => <Tag key={j} color="green" style={{ marginLeft: 8 }}>{a.type}: {a.to || a.from}</Tag>)}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {r.failed && r.failed.length > 0 && (
                              <div>
                                <Typography.Text strong style={{ color: '#ff4d4f' }}>失败 ({r.failed.length}):</Typography.Text>
                                <ul style={{ maxHeight: 200, overflow: 'auto', margin: '8px 0', paddingLeft: 20 }}>
                                  {r.failed.map((f: any, i: number) => (
                                    <li key={i}>
                                      <code>{f.video_path?.split('/').pop()}</code>
                                      <Tag color="red" style={{ marginLeft: 8 }}>{f.error}</Tag>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </div>
                        ),
                      })
                    }}>
                      查看
                    </Button>
                  ),
                },
              ]}
            />
          </Card>
        )}
      </Space>
    </div>
  )
}
