import { useEffect, useState } from 'react'
import {
  Card, Button, Space, Typography, Table, Tag, Switch,
  Input, Modal, App, Empty, Tooltip, List
} from 'antd'
import {
  FolderOutlined, PlusOutlined, DeleteOutlined,
  ReloadOutlined, EyeOutlined, FolderAddOutlined,
} from '@ant-design/icons'
import { useSocket } from '../hooks/useSocket'
import { fetchWatcher, addWatchPath, removeWatchPath, toggleWatchPath } from '../api'
import dayjs from 'dayjs'

export default function Watcher() {
  const { lastWatcherEvent } = useSocket()
  const [watchData, setWatchData] = useState<any>({ enabled: false, paths: [] })
  const [loading, setLoading] = useState(false)
  const [addModalVisible, setAddModalVisible] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [events, setEvents] = useState<any[]>([])
  const { message } = App.useApp()

  useEffect(() => { loadData() }, [])

  useEffect(() => {
    if (lastWatcherEvent) {
      setEvents((prev) => [lastWatcherEvent, ...prev].slice(0, 50))
    }
  }, [lastWatcherEvent])

  const loadData = async () => {
    setLoading(true)
    try {
      const { data } = await fetchWatcher()
      setWatchData(data || { enabled: false, paths: [] })
    } catch (e) {
      message.error('加载监控数据失败')
    } finally {
      setLoading(false)
    }
  }

  const handleAdd = async () => {
    if (!newPath.trim()) return
    try {
      const res = await addWatchPath(newPath.trim())
      if (res.code === 0) {
        message.success('监控路径已添加')
        setAddModalVisible(false)
        setNewPath('')
        loadData()
      } else {
        message.error(res.message)
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '添加失败')
    }
  }

  const handleRemove = async (path: string) => {
    Modal.confirm({
      title: '确认移除',
      content: `确定要移除监控路径: ${path} ?`,
      onOk: async () => {
        try {
          await removeWatchPath(path)
          message.success('已移除')
          loadData()
        } catch (e) {
          message.error('移除失败')
        }
      },
    })
  }

  const handleToggle = async (path: string, enabled: boolean) => {
    try {
      await toggleWatchPath(path, enabled)
      loadData()
    } catch (e) {
      message.error('操作失败')
    }
  }

  const columns = [
    {
      title: '监控路径',
      dataIndex: 'path',
      ellipsis: true,
      render: (path: string) => (
        <Space><FolderOutlined />{path}</Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 100,
      render: (enabled: number, record: any) => (
        <Switch
          checked={enabled === 1}
          onChange={(checked) => handleToggle(record.path, checked)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      ),
    },
    {
      title: '添加时间',
      dataIndex: 'created_at',
      width: 180,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 80,
      render: (_: any, record: any) => (
        <Button type="link" danger icon={<DeleteOutlined />} onClick={() => handleRemove(record.path)}>
          移除
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <FolderOutlined /> 文件监控
      </Typography.Title>

      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Card
          variant="borderless"
          title={
            <Space>
              监控路径列表
              <Tag color={watchData.enabled ? 'success' : 'default'}>
                {watchData.enabled ? '监控已启用' : '监控未启用'}
              </Tag>
            </Space>
          }
          extra={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddModalVisible(true)}>
                添加路径
              </Button>
            </Space>
          }
        >
          <Table
            dataSource={watchData.paths}
            columns={columns}
            rowKey="id"
            loading={loading}
            pagination={false}
            size="middle"
            locale={{ emptyText: <Empty description="暂无监控路径，请先在配置管理中启用监控并添加路径" /> }}
          />
        </Card>

        <Card title="实时监控事件" variant="borderless">
          {events.length > 0 ? (
            <List
              size="small"
              dataSource={events}
              renderItem={(event: any, index: number) => (
                <List.Item>
                  <Space>
                    <Tag color="processing">{event.type}</Tag>
                    <span>{event.message}</span>
                    {event.files && (
                      <Tag>{event.files.length} 个文件</Tag>
                    )}
                  </Space>
                </List.Item>
              )}
            />
          ) : (
            <Empty description="暂无监控事件" />
          )}
        </Card>
      </Space>

      <Modal
        title="添加监控路径"
        open={addModalVisible}
        onOk={handleAdd}
        onCancel={() => { setAddModalVisible(false); setNewPath('') }}
        okText="添加"
        cancelText="取消"
      >
        <Input
          prefix={<FolderAddOutlined />}
          placeholder="输入要监控的目录路径"
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onPressEnter={handleAdd}
        />
      </Modal>
    </div>
  )
}
