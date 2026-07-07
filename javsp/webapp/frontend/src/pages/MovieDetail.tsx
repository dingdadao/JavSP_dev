import { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Space, Typography, Tag, Image, Row, Col,
  List, App, Spin, Descriptions
} from 'antd'
import { ArrowLeftOutlined, SaveOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { fetchMovie, updateMovie } from '../api'

export default function MovieDetail() {
  const [searchParams] = useSearchParams()
  const dvdid = searchParams.get('dvdid') || ''
  const path = searchParams.get('path') || ''
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [movie, setMovie] = useState<any>(null)

  useEffect(() => {
    if (dvdid && path) {
      loadMovie()
    }
  }, [dvdid, path])

  const loadMovie = async () => {
    setLoading(true)
    try {
      const res = await fetchMovie(dvdid, path)
      if (res.code === 0 && res.data) {
        setMovie(res.data)
        form.setFieldsValue(res.data)
      } else {
        message.error(res.message || '加载影片信息失败')
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '加载影片信息失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async (values: any) => {
    setSaving(true)
    try {
      const res = await updateMovie(dvdid, path, values)
      if (res.code === 0) {
        message.success('保存成功')
        loadMovie()
      } else {
        message.error(res.message || '保存失败')
      }
    } catch (e: any) {
      message.error(e.response?.data?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (!dvdid || !path) {
    return (
      <Card>
        <Typography.Text type="danger">缺少影片参数</Typography.Text>
      </Card>
    )
  }

  return (
    <div>
      <Typography.Title level={4}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ marginRight: 12 }}>
          返回
        </Button>
        影片详情
      </Typography.Title>

      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={8}>
            <Card title="封面" variant="borderless">
              <Image
                src={`/api/cover?path=${encodeURIComponent(movie?.thumb?.[0] || movie?.fanart?.[0] || '')}`}
                alt={dvdid}
                style={{ width: '100%', borderRadius: 8 }}
                fallback="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
              />
              <Descriptions size="small" column={1} style={{ marginTop: 16 }}>
                <Descriptions.Item label="番号">{dvdid}</Descriptions.Item>
                <Descriptions.Item label="路径">{path}</Descriptions.Item>
                <Descriptions.Item label="NFO">{movie?.nfo_path}</Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>

          <Col xs={24} lg={16}>
            <Card
              title="NFO 信息编辑"
              variant="borderless"
              extra={
                <Space>
                  <Button icon={<ReloadOutlined />} onClick={loadMovie}>刷新</Button>
                  <Button type="primary" icon={<SaveOutlined />} onClick={() => form.submit()} loading={saving}>
                    保存
                  </Button>
                </Space>
              }
            >
              <Form form={form} layout="vertical" onFinish={handleSave}>
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item label="标题" name="title">
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item label="原始标题" name="originaltitle">
                      <Input />
                    </Form.Item>
                  </Col>
                </Row>

                <Row gutter={16}>
                  <Col span={8}>
                    <Form.Item label="年份" name="year">
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item label="发行日期" name="release_date">
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item label="时长" name="runtime">
                      <Input />
                    </Form.Item>
                  </Col>
                </Row>

                <Row gutter={16}>
                  <Col span={8}>
                    <Form.Item label="制作商" name="studio">
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item label="发行商" name="maker">
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item label="片商" name="label">
                      <Input />
                    </Form.Item>
                  </Col>
                </Row>

                <Form.Item label="简介" name="plot">
                  <Input.TextArea rows={4} />
                </Form.Item>

                <Form.Item label="标签" name="genre">
                  <Input placeholder="用逗号分隔多个标签" />
                </Form.Item>

                <Form.Item label="女优" name="actor">
                  <List
                    size="small"
                    dataSource={movie?.actor || []}
                    renderItem={(actor: any) => (
                      <List.Item>
                        <Tag>{actor.name}</Tag>
                      </List.Item>
                    )}
                  />
                </Form.Item>
              </Form>
            </Card>
          </Col>
        </Row>
      </Spin>
    </div>
  )
}
