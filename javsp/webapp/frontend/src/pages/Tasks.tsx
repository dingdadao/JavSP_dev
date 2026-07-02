import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space, Typography, Modal, Descriptions, message } from 'antd'
import { ReloadOutlined, EyeOutlined } from '@ant-design/icons'
import { fetchTasks, fetchTask } from '../api'
import dayjs from 'dayjs'

export default function Tasks() {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [detailVisible, setDetailVisible] = useState(false)

  useEffect(() => { loadTasks() }, [])

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

  const showDetail = async (taskId: string) => {
    try {
      const { data } = await fetchTask(taskId)
      setDetail(data)
      setDetailVisible(true)
    } catch (e) {
      message.error('加载任务详情失败')
    }
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
        const map: Record<string, { color: string; text: string }> = {
          completed: { color: 'success', text: '完成' },
          running: { color: 'processing', text: '运行中' },
          partial: { color: 'warning', text: '部分完成' },
          failed: { color: 'error', text: '失败' },
          pending: { color: 'default', text: '等待中' },
          error: { color: 'error', text: '异常' },
        }
        const s = map[status] || { color: 'default', text: status }
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
      width: 120,
      render: (_: any, r: any) => `${r.completed}/${r.total}`,
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
      width: 80,
      render: (_: any, record: any) => (
        <Button type="link" icon={<EyeOutlined />} onClick={() => showDetail(record.id)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>任务列表</Typography.Title>
      <Card
        bordered={false}
        extra={<Button icon={<ReloadOutlined />} onClick={loadTasks}>刷新</Button>}
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
        width={800}
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
                  detail.status === 'running' ? 'processing' : 'error'
                }>{detail.status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="类型">{detail.task_type === 'manual' ? '手动' : '自动'}</Descriptions.Item>
              <Descriptions.Item label="源路径">{detail.source_path}</Descriptions.Item>
              <Descriptions.Item label="输出路径">{detail.dest_path}</Descriptions.Item>
              <Descriptions.Item label="进度">{detail.completed}/{detail.total}</Descriptions.Item>
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
                  columns={[
                    { title: '番号', dataIndex: 'dvdid', width: 140 },
                    {
                      title: '状态', dataIndex: 'status', width: 80,
                      render: (s: string) => (
                        <Tag color={s === 'success' ? 'success' : s === 'failed' ? 'error' : 'default'}>
                          {s === 'success' ? '成功' : s === 'failed' ? '失败' : '等待'}
                        </Tag>
                      ),
                    },
                    { title: '消息', dataIndex: 'message', ellipsis: true },
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
