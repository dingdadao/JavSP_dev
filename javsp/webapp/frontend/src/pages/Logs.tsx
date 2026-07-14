import { useEffect, useState, useRef, useCallback } from 'react'
import { Card, Table, Tag, Select, Space, Typography, Button, App, Tabs, Input, Switch, Checkbox } from 'antd'
import { ReloadOutlined, FileTextOutlined, VerticalAlignBottomOutlined, SearchOutlined } from '@ant-design/icons'
import { fetchLogs, fetchAppLogs } from '../api'
import dayjs from 'dayjs'

const LEVEL_COLORS: Record<string, string> = {
  INFO: 'blue',
  WARNING: 'orange',
  ERROR: 'red',
  DEBUG: 'default',
}

function OperationLogs() {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [level, setLevel] = useState<string | undefined>(undefined)
  const { message } = App.useApp()

  useEffect(() => { loadLogs() }, [level])

  const loadLogs = async () => {
    setLoading(true)
    try {
      const { data } = await fetchLogs(200, level)
      setLogs(data || [])
    } catch (e) {
      message.error('加载日志失败')
    } finally {
      setLoading(false)
    }
  }

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '级别',
      dataIndex: 'level',
      width: 90,
      render: (level: string) => (
        <Tag color={LEVEL_COLORS[level] || 'default'}>{level}</Tag>
      ),
    },
    {
      title: '模块',
      dataIndex: 'module',
      width: 100,
    },
    {
      title: '消息',
      dataIndex: 'message',
      ellipsis: true,
    },
    {
      title: '详情',
      dataIndex: 'details',
      ellipsis: true,
      render: (d: string) => d || '-',
    },
  ]

  return (
    <Card variant="borderless" extra={
      <Space>
        <Select
          allowClear
          placeholder="按级别筛选"
          style={{ width: 140 }}
          value={level}
          onChange={setLevel}
          options={[
            { label: '全部', value: undefined },
            { label: 'INFO', value: 'INFO' },
            { label: 'WARNING', value: 'WARNING' },
            { label: 'ERROR', value: 'ERROR' },
            { label: 'DEBUG', value: 'DEBUG' },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={loadLogs}>刷新</Button>
      </Space>
    }>
      <Table
        dataSource={logs}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true }}
      />
    </Card>
  )
}

function AppLogs() {
  const [lines, setLines] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [level, setLevel] = useState<string | undefined>(undefined)
  const [search, setSearch] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const containerRef = useRef<HTMLDivElement>(null)
  const { message } = App.useApp()

  const loadLogs = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await fetchAppLogs({ level, search, limit: 500 })
      setLines(data?.lines || [])
      setTotal(data?.total || 0)
    } catch {
      message.error('加载日志失败')
    } finally {
      setLoading(false)
    }
  }, [level, search, message])

  useEffect(() => { loadLogs() }, [level])

  // 自动刷新
  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(loadLogs, 3000)
    return () => clearInterval(timer)
  }, [autoRefresh, loadLogs])

  // 自动滚动到底部
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = 0
    }
  }, [lines, autoScroll])

  const getLevelColor = (level: string) => {
    if (level === 'ERROR') return '#ff4d4f'
    if (level === 'WARNING') return '#faad14'
    if (level === 'INFO') return '#1890ff'
    return '#888'
  }

  return (
    <Card
      variant="borderless"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索关键词"
            allowClear
            style={{ width: 200 }}
            onSearch={(v) => { setSearch(v); setTimeout(loadLogs, 100) }}
            enterButton={<SearchOutlined />}
          />
          <Select
            allowClear
            placeholder="级别"
            style={{ width: 110 }}
            value={level}
            onChange={setLevel}
            options={[
              { label: '全部', value: undefined },
              { label: 'INFO', value: 'INFO' },
              { label: 'WARNING', value: 'WARNING' },
              { label: 'ERROR', value: 'ERROR' },
              { label: 'DEBUG', value: 'DEBUG' },
            ]}
          />
          <Checkbox checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)}>
            自动刷新
          </Checkbox>
          <Checkbox checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)}>
            自动滚动
          </Checkbox>
          <Button icon={<ReloadOutlined />} onClick={loadLogs} loading={loading}>刷新</Button>
        </Space>
      }
    >
      <div style={{ marginBottom: 8, color: '#888', fontSize: 12 }}>
        共 {total} 条日志，显示最新 {lines.length} 条
      </div>
      <div
        ref={containerRef}
        style={{
          height: 'calc(100vh - 280px)',
          overflow: 'auto',
          background: '#1e1e2e',
          borderRadius: 8,
          padding: '12px 16px',
          fontFamily: 'Menlo, Monaco, "Courier New", monospace',
          fontSize: 12,
          lineHeight: 1.8,
        }}
      >
        {lines.length === 0 ? (
          <div style={{ color: '#666', textAlign: 'center', padding: 40 }}>暂无日志</div>
        ) : (
          lines.map((line, i) => (
            <div
              key={i}
              style={{
                color: '#d4d4d4',
                borderBottom: '1px solid rgba(255,255,255,0.03)',
                padding: '2px 0',
                wordBreak: 'break-all',
              }}
            >
              <span style={{ color: '#6a9955' }}>{line.time}</span>
              {' '}
              <span style={{ color: getLevelColor(line.level), fontWeight: 600 }}>[{line.level}]</span>
              {' '}
              <span style={{ color: '#569cd6' }}>{line.module}</span>
              <span style={{ color: '#888' }}>: </span>
              <span>{line.message}</span>
            </div>
          ))
        )}
      </div>
    </Card>
  )
}

export default function Logs() {
  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <FileTextOutlined /> 日志
      </Typography.Title>
      <Tabs
        defaultActiveKey="app"
        items={[
          { key: 'app', label: '应用日志', children: <AppLogs /> },
          { key: 'ops', label: '操作日志', children: <OperationLogs /> },
        ]}
      />
    </div>
  )
}
