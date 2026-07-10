import { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Switch, Select, InputNumber,
  Typography, Tabs, Space, Spin, Collapse, Tag, Tooltip, Alert, Table, Modal, App
} from 'antd'
import { SaveOutlined, SettingOutlined, PlusOutlined, DeleteOutlined, StarOutlined, StarFilled } from '@ant-design/icons'
import { fetchConfig, updateConfig, fetchMediaLibraries, createMediaLibrary, updateMediaLibrary, deleteMediaLibrary } from '../api'

const CRAWLER_OPTIONS = [
  { label: 'JavDB', value: 'javdb' },
  { label: 'JavBus', value: 'javbus' },
  { label: 'AirAV', value: 'airav' },
  { label: 'AVSOX', value: 'avsox' },
  { label: 'AVWiki', value: 'avwiki' },
  { label: 'Fanza', value: 'fanza' },
  { label: 'FC2', value: 'fc2' },
  { label: 'FC2Fan', value: 'fc2fan' },
  { label: 'JavLib', value: 'javlib' },
  { label: 'JavMenu', value: 'javmenu' },
  { label: 'Jav321', value: 'jav321' },
  { label: 'MGStage', value: 'mgstage' },
  { label: 'Prestige', value: 'prestige' },
  { label: 'Arzon', value: 'arzon' },
  { label: 'DL Getchu', value: 'dl_getchu' },
  { label: 'Gyutto', value: 'gyutto' },
  { label: 'NJAV', value: 'njav' },
  { label: 'MissAV', value: 'missav' },
]

const TRANSLATE_ENGINES = [
  { label: '不翻译', value: '' },
  { label: '--- 通用翻译（无需大模型）---', value: '', disabled: true },
  { label: 'Google (免费，无需配置)', value: 'google' },
  { label: 'Bing (需要 API Key)', value: 'bing' },
  { label: 'Baidu (需要 App ID + Key)', value: 'baidu' },
  { label: '--- 大模型翻译（支持 OpenAI 兼容接口）---', value: '', disabled: true },
  { label: 'OpenAI / 兼容接口', value: 'openai' },
  { label: 'Claude (Haiku)', value: 'claude' },
  { label: 'Google AI', value: 'googleai' },
  { label: '本地 AI (LM Studio)', value: 'localai' },
]

// 引擎分类：是否为大模型引擎
const isLLMEngine = (engine: string) => ['openai', 'claude', 'googleai', 'localai'].includes(engine)

// 每个配置组独立的子组件，各自持有自己的 Form 实例
function ScannerConfig({ saving, onSave }: { saving: boolean; onSave: (v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchConfig('scanner').then(({ data }) => {
      const s = data?.scanner || {}
      form.setFieldsValue({
        input_directory: s.input_directory || '',
        minimum_size: s.minimum_size || '232MiB',
        skip_nfo_dir: s.skip_nfo_dir ?? false,
        clear_skipped_on_rescan: s.clear_skipped_on_rescan ?? true,
      })
    }).finally(() => setLoading(false))
  }, [])

  return (
    <Card title="扫描设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item label="源文件夹路径" name="input_directory" extra="留空则运行时询问">
            <Input placeholder="/path/to/movies" />
          </Form.Item>
          <Form.Item label="最小文件大小" name="minimum_size">
            <Input placeholder="232MiB" />
          </Form.Item>
          <Form.Item label="跳过已有NFO的目录" name="skip_nfo_dir" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="重新扫描时清理.skipped" name="clear_skipped_on_rescan" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

function NetworkConfig({ saving, onSave }: { saving: boolean; onSave: (v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchConfig('network').then(({ data }) => {
      const n = data?.network || {}
      const mirrors = n.crawler_mirror || {}
      form.setFieldsValue({
        proxy_server: n.proxy_server || '',
        retry: n.retry ?? 3,
        timeout: n.timeout || 'PT10S',
        ssl_verification: n.ssl_verification ?? true,
        crawler_mirror: Object.entries(mirrors).map(([k, v]) => `${k}=${v}`).join('\n'),
      })
    }).finally(() => setLoading(false))
  }, [])

  return (
    <Card title="网络设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={(values) => {
          // 解析镜像地址
          const mirrors: Record<string, string> = {}
          if (values.crawler_mirror) {
            for (const line of values.crawler_mirror.split('\n')) {
              const trimmed = line.trim()
              if (!trimmed || trimmed.startsWith('#')) continue
              const idx = trimmed.indexOf('=')
              if (idx > 0) {
                mirrors[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim()
              }
            }
          }
          onSave({ ...values, crawler_mirror: mirrors })
        }}>
          <Form.Item label="代理服务器" name="proxy_server" extra="支持 http, socks5 代理，留空禁用">
            <Input placeholder="http://127.0.0.1:1080" />
          </Form.Item>
          <Form.Item label="重试次数" name="retry">
            <InputNumber min={0} max={10} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item label="超时时间" name="timeout" extra="ISO 8601 Duration 格式，如 PT10S 表示10秒">
            <Input placeholder="PT10S" />
          </Form.Item>
          <Form.Item label="SSL证书验证" name="ssl_verification" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="爬虫镜像地址" name="crawler_mirror" extra="每行一个，格式: 爬虫名=镜像地址 (如 javdb=https://mirror.example.com)，配置后优先使用镜像地址">
            <Input.TextArea
              placeholder={"javdb=https://your-mirror.example.com/javdb\njavbus=https://your-mirror.example.com/javbus"}
              rows={4}
            />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

function CrawlerConfig({ saving, onSave }: { saving: boolean; onSave: (v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchConfig('crawler').then(({ data }) => {
      const c = data?.crawler || {}
      form.setFieldsValue({
        selection_normal: c.selection_normal || [],
        selection_fc2: c.selection_fc2 || [],
        hardworking: c.hardworking ?? true,
        sleep_after_scraping: c.sleep_after_scraping || 'PT1S',
      })
    }).finally(() => setLoading(false))
  }, [])

  return (
    <Card title="爬虫设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item label="普通影片爬虫列表" name="selection_normal" extra="按优先级排序，靠前的优先使用">
            <Select mode="multiple" options={CRAWLER_OPTIONS} placeholder="选择爬虫" />
          </Form.Item>
          <Form.Item label="FC2影片爬虫列表" name="selection_fc2">
            <Select mode="multiple" options={CRAWLER_OPTIONS} placeholder="选择爬虫" />
          </Form.Item>
          <Form.Item label="努力爬取更多信息" name="hardworking" valuePropName="checked" extra="会略微增加部分站点的爬取耗时">
            <Switch />
          </Form.Item>
          <Form.Item label="刮削后等待时间" name="sleep_after_scraping" extra="ISO 8601 Duration 格式">
            <Input placeholder="PT1S" />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

const CHECKER_NFO_TITLE_PRESETS = [
  { value: '', label: '使用全局NFO标题格式' },
  { value: '{title}', label: 'Jellyfin 标准格式' },
  { value: '{num} {title}', label: 'Kodi 格式 (番号+标题)' },
  { value: '{num} - {title}', label: '飞牛 NAS 格式 (番号-标题)' },
  { value: '{actress} - {num} {title}', label: '标准格式 (女优-番号 标题)' },
]

const NAMING_VARIABLES = [
  { var: '{num}', desc: '影片番号', example: 'SSIS-001', note: '优先 DVD ID，cid 模式下为 cid' },
  { var: '{title}', desc: '影片标题（翻译后）', example: '标题内容', note: '' },
  { var: '{rawtitle}', desc: '原始标题（翻译前）', example: '原标题', note: '无论是否翻译，始终为原始标题' },
  { var: '{actress}', desc: '女优名', example: '三上悠亜', note: '多个用逗号分隔' },
  { var: '{censor}', desc: '有码/无码', example: '有码', note: '三种状态：有码/无码/不确定' },
  { var: '{score}', desc: '影片评分', example: '7.81', note: '10 分制' },
  { var: '{serial}', desc: '系列', example: '系列名', note: '' },
  { var: '{label}', desc: '番号系列标签', example: 'SSIS', note: '番号拆分后的系列前缀' },
  { var: '{director}', desc: '导演', example: '导演名', note: '' },
  { var: '{producer}', desc: '制作商', example: '制作商名', note: '' },
  { var: '{publisher}', desc: '发行商', example: '发行商名', note: '' },
  { var: '{date}', desc: '发行日期', example: '2020-05-20', note: '' },
  { var: '{year}', desc: '发行年份', example: '2020', note: '' },
]

function VariableHint() {
  return (
    <div style={{ marginTop: 4 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        可用变量（用花括号包裹）：
      </Typography.Text>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 8px', marginTop: 4 }}>
        {NAMING_VARIABLES.map((v) => (
          <Tooltip
            key={v.var}
            title={
              <div>
                <div><strong>{v.desc}</strong></div>
                <div>示例: {v.example}</div>
                {v.note && <div style={{ color: 'rgba(255,255,255,0.65)' }}>{v.note}</div>}
              </div>
            }
          >
            <Tag style={{ cursor: 'help', fontSize: 11 }}>{v.var}</Tag>
          </Tooltip>
        ))}
      </div>
      <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 4, display: 'block' }}>
        示例: {'{actress}/{num}'} / {'[{num}] {title}'} / {'{censor}/{actress}/[{num}]'}
      </Typography.Text>
    </div>
  )
}

function SummarizerConfig({ saving, onSave }: { saving: boolean; onSave: (v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchConfig('summarizer').then(({ data }) => {
      const s = data?.summarizer || {}
      form.setFieldsValue({
        output_folder_pattern: s.output_folder_pattern || '',
        move_files: s.move_files ?? true,
        basename_pattern: s.basename_pattern || '{title}',
        nfo_title_pattern: s.nfo_title_pattern || '{title}',
        checker_nfo_title_pattern: s.checker_nfo_title_pattern || '',
        checker_default_path: s.checker_default_path || '',
      })
    }).finally(() => setLoading(false))
  }, [])

  return (
    <Card title="整理设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item label="输出文件夹路径" name="output_folder_pattern">
            <Input placeholder="/path/to/output/{actress}/{num}" />
          </Form.Item>
          <Form.Item label="整理时移动文件" name="move_files" valuePropName="checked" extra="关闭则复制文件到目标目录">
            <Switch />
          </Form.Item>
          <Form.Item label="文件命名规则" name="basename_pattern">
            <Input placeholder="{title}" />
          </Form.Item>
          <Form.Item label="NFO标题格式" name="nfo_title_pattern">
            <Input placeholder="{title}" />
          </Form.Item>
          <Form.Item label="检查器NFO标题格式" name="checker_nfo_title_pattern" extra="命名检查器重新刮削时使用的NFO标题格式，留空则使用上方的NFO标题格式">
            <Select options={CHECKER_NFO_TITLE_PRESETS} />
          </Form.Item>
          <Form.Item label="文件检查器默认扫描路径" name="checker_default_path" extra="命名检查页面的默认扫描路径，可设置为外挂硬盘路径">
            <Input placeholder="/Volumes/data/movies" />
          </Form.Item>
          <VariableHint />
        </Form>
      </Spin>
    </Card>
  )
}

function TranslatorConfig({ saving, onSave }: { saving: boolean; onSave: (v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [engine, setEngine] = useState('')

  useEffect(() => {
    fetchConfig('translator').then(({ data }) => {
      const t = data?.translator || {}
      const eng = t.engine || ''
      setEngine(eng)
      form.setFieldsValue({
        engine: eng,
        translate_title: t.translate_title ?? true,
        translate_plot: t.translate_plot ?? true,
        // 通用翻译
        baidu_app_id: t.baidu_app_id || '',
        bing_api_key: t.bing_api_key || '',
        // 大模型翻译
        api_url: t.api_url || '',
        api_key: t.api_key || '',
        model: t.model || '',
      })
    }).finally(() => setLoading(false))
  }, [])

  const handleEngineChange = (val: string) => {
    setEngine(val)
  }

  // 是否为需要 API Key 的通用翻译
  const needsApiKey = (eng: string) => ['bing', 'baidu'].includes(eng)
  // 是否为大模型引擎
  const isLLM = isLLMEngine(engine)

  return (
    <Card title="翻译设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item label="翻译引擎" name="engine">
            <Select options={TRANSLATE_ENGINES} onChange={handleEngineChange} style={{ width: 320 }} />
          </Form.Item>

          {engine && (
            <Form.Item label="翻译标题" name="translate_title" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
          {engine && (
            <Form.Item label="翻译剧情简介" name="translate_plot" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}

          {/* Baidu 需要 App ID + Key */}
          {engine === 'baidu' && (
            <>
              <Form.Item label="百度翻译 App ID" name="baidu_app_id" rules={[{ required: true, message: '请输入 App ID' }]}>
                <Input placeholder="百度翻译开放平台的 App ID" />
              </Form.Item>
              <Form.Item label="百度翻译密钥" name="api_key" rules={[{ required: true, message: '请输入密钥' }]}>
                <Input.Password placeholder="百度翻译开放平台的密钥" />
              </Form.Item>
            </>
          )}

          {/* Bing 需要 API Key */}
          {engine === 'bing' && (
            <Form.Item label="Azure 认知服务密钥" name="bing_api_key" rules={[{ required: true, message: '请输入 API Key' }]}>
              <Input.Password placeholder="微软必应翻译 (Azure 认知服务) 的密钥" />
            </Form.Item>
          )}

          {/* Claude 只需要 API Key */}
          {engine === 'claude' && (
            <Form.Item label="Claude API Key" name="api_key" rules={[{ required: true, message: '请输入 API Key' }]}>
              <Input.Password placeholder="Claude API 密钥" />
            </Form.Item>
          )}

          {/* Google AI 需要 URL + Key + Model */}
          {engine === 'googleai' && (
            <>
              <Form.Item label="API 地址" name="api_url" rules={[{ required: true, message: '请输入 API 地址' }]}>
                <Input placeholder="https://generativelanguage.googleapis.com/v1beta/..." />
              </Form.Item>
              <Form.Item label="API Key" name="api_key" rules={[{ required: true, message: '请输入 API Key' }]}>
                <Input.Password placeholder="Google AI API Key" />
              </Form.Item>
              <Form.Item label="模型名称" name="model" rules={[{ required: true, message: '请输入模型名称' }]}>
                <Input placeholder="gemini-pro" />
              </Form.Item>
            </>
          )}

          {/* OpenAI 兼容接口需要 URL + Key + Model */}
          {engine === 'openai' && (
            <>
              <Form.Item label="API 地址" name="api_url" rules={[{ required: true, message: '请输入 API 地址' }]}
                extra="任何兼容 OpenAI Chat Completions 的接口地址">
                <Input placeholder="https://api.openai.com/v1/chat/completions" />
              </Form.Item>
              <Form.Item label="API Key" name="api_key"
                extra="留空则不使用密钥（部分本地部署无需密钥）">
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item label="模型名称" name="model" rules={[{ required: true, message: '请输入模型名称' }]}
                extra="例如: gpt-3.5-turbo, qwen/qwen2.5-vl-7b, llama-3.1-70b-versatile 等">
                <Input placeholder="gpt-3.5-turbo" />
              </Form.Item>
            </>
          )}

          {/* LocalAI 需要 URL + Model，Key 可选 */}
          {engine === 'localai' && (
            <>
              <Form.Item label="API 地址" name="api_url" rules={[{ required: true, message: '请输入 API 地址' }]}
                extra="LM Studio 默认地址为 http://localhost:1234">
                <Input placeholder="http://localhost:1234" />
              </Form.Item>
              <Form.Item label="API Key" name="api_key"
                extra="LM Studio 默认不需要密钥，留空即可">
                <Input.Password placeholder="留空" />
              </Form.Item>
              <Form.Item label="模型名称" name="model" rules={[{ required: true, message: '请输入模型名称' }]}
                extra="在 LM Studio 中加载的模型名称">
                <Input placeholder="hy-mt2-7b" />
              </Form.Item>
            </>
          )}

          {/* Google 免费，无需额外配置 */}
          {engine === 'google' && (
            <Alert type="info" showIcon message="Google 翻译免费使用，无需配置 API Key" />
          )}
        </Form>
      </Spin>
    </Card>
  )
}

function CoverConfig({ saving, onSave }: { saving: boolean; onSave: (v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchConfig('cover').then(({ data }) => {
      const c = data?.cover || {}
      form.setFieldsValue({
        highres: c.highres ?? true,
        add_label: c.add_label ?? false,
      })
    }).finally(() => setLoading(false))
  }, [])

  return (
    <Card title="封面设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item label="下载高清封面" name="highres" valuePropName="checked" extra="高清封面约 8-10 MiB">
            <Switch />
          </Form.Item>
          <Form.Item label="添加水印标签" name="add_label" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

function WatcherConfig({ saving, onSave }: { saving: boolean; onSave: (v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchConfig('watcher').then(({ data }) => {
      const w = data?.watcher || {}
      form.setFieldsValue({
        enabled: w.enabled ?? false,
        auto_scrape: w.auto_scrape ?? true,
      })
    }).finally(() => setLoading(false))
  }, [])

  return (
    <Card title="文件监控设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item label="启用文件监控" name="enabled" valuePropName="checked" extra="监控目录变动，自动触发刮削">
            <Switch />
          </Form.Item>
          <Form.Item label="自动刮削新文件" name="auto_scrape" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

function MediaLibraryConfig() {
  const [libraries, setLibraries] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const loadLibraries = async () => {
    setLoading(true)
    try {
      const { data } = await fetchMediaLibraries()
      setLibraries(data || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadLibraries() }, [])

  const handleAdd = () => {
    setEditId(null)
    form.resetFields()
    form.setFieldsValue({ is_default: libraries.length === 0 })
    setModalOpen(true)
  }

  const handleEdit = (record: any) => {
    setEditId(record.id)
    form.setFieldsValue({ name: record.name, path: record.path, is_default: !!record.is_default })
    setModalOpen(true)
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteMediaLibrary(id)
      message.success('媒体库已删除')
      loadLibraries()
    } catch (e) {
      message.error('删除失败')
    }
  }

  const handleSetDefault = async (id: number) => {
    try {
      await updateMediaLibrary(id, { is_default: true })
      message.success('已设为默认')
      loadLibraries()
    } catch (e) {
      message.error('操作失败')
    }
  }

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields()
      if (editId) {
        await updateMediaLibrary(editId, values)
        message.success('媒体库已更新')
      } else {
        await createMediaLibrary(values)
        message.success('媒体库已添加')
      }
      setModalOpen(false)
      loadLibraries()
    } catch (e: any) {
      if (e?.response?.data?.message) {
        message.error(e.response.data.message)
      }
    }
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name: string, record: any) => (
        <Space>
          {record.is_default ? <StarFilled style={{ color: '#f59e0b' }} /> : <StarOutlined style={{ color: 'rgba(255,255,255,0.25)' }} />}
          {name}
        </Space>
      ),
    },
    {
      title: '路径',
      dataIndex: 'path',
      ellipsis: true,
    },
    {
      title: '操作',
      width: 220,
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" onClick={() => handleEdit(record)}>编辑</Button>
          {!record.is_default && (
            <Button size="small" icon={<StarOutlined />} onClick={() => handleSetDefault(record.id)}>设为默认</Button>
          )}
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="媒体库配置"
      variant="borderless"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加媒体库</Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="媒体库用于管理多个不同的影片存储路径，刮削时可选择特定媒体库进行扫描。第一个添加的媒体库自动设为默认。"
      />
      <Table
        dataSource={libraries}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        locale={{ emptyText: '暂未配置媒体库，请添加' }}
      />
      <Modal
        title={editId ? '编辑媒体库' : '添加媒体库'}
        open={modalOpen}
        onOk={handleModalOk}
        onCancel={() => setModalOpen(false)}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：主库、外挂硬盘等" />
          </Form.Item>
          <Form.Item label="路径" name="path" rules={[{ required: true, message: '请输入路径' }]}>
            <Input placeholder="/path/to/library" />
          </Form.Item>
          <Form.Item label="设为默认" name="is_default" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default function Config() {
  const [saving, setSaving] = useState(false)
  const { message } = App.useApp()

  const handleSave = async (group: string, values: any) => {
    setSaving(true)
    try {
      const updates = Object.entries(values).map(([key, value]) => ({ group, key, value }))
      await updateConfig(updates)
      message.success('配置已保存')
    } catch (e) {
      message.error('保存配置失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        <SettingOutlined /> 配置管理
      </Typography.Title>

      <Tabs
        items={[
          {
            key: 'basic',
            label: '基本设置',
            children: (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <NetworkConfig saving={saving} onSave={(v) => handleSave('network', v)} />
                <TranslatorConfig saving={saving} onSave={(v) => handleSave('translator', v)} />
                <CoverConfig saving={saving} onSave={(v) => handleSave('cover', v)} />
              </Space>
            ),
          },
          {
            key: 'media',
            label: '媒体库配置',
            children: <MediaLibraryConfig />,
          },
          {
            key: 'scraping',
            label: '刮削设置',
            children: (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <ScannerConfig saving={saving} onSave={(v) => handleSave('scanner', v)} />
                <CrawlerConfig saving={saving} onSave={(v) => handleSave('crawler', v)} />
                <SummarizerConfig saving={saving} onSave={(v) => handleSave('summarizer', v)} />
                <WatcherConfig saving={saving} onSave={(v) => handleSave('watcher', v)} />
              </Space>
            ),
          },
        ]}
      />
    </div>
  )
}
