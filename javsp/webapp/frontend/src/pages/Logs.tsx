import { useEffect, useState } from 'react'
import { Card, Table, Tag, Select, Space, Typography, Button, message } from 'antd'
import { ReloadOutlined, FileTextOutlined } from '@ant-design/icons'
import { fetchLogs } from '../api'
import dayjs from 'dayjs'

const LEVEL_COLORS: Record<string, string> = {
  INFO: 'blue',
  WARNING: 'orange',
  ERROR: 'red',
  DEBUG: 'default',
}

export default function Logs() {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [level, setLevel] = useState<string | undefined>(undefined)

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
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <FileTextOutlined /> 操作日志
      </Typography.Title>

      <Card bordered={false} extra={
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
    </div>
  )
}
