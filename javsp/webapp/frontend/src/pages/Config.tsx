import { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Switch, Select, InputNumber,
  Typography, Tabs, Space, Spin, Tag, Tooltip, Alert, Table, Modal, App
} from 'antd'
import {
  SaveOutlined, SettingOutlined, PlusOutlined, DeleteOutlined,
  StarOutlined, StarFilled, QuestionCircleOutlined
} from '@ant-design/icons'
import { fetchConfig, updateConfig, fetchMediaLibraries, createMediaLibrary, updateMediaLibrary, deleteMediaLibrary } from '../api'

/* ========== Tip 工具函数 ========== */
function Tip({ text }: { text: string }) {
  return (
    <Tooltip title={text} placement="top">
      <QuestionCircleOutlined style={{ marginLeft: 4, color: 'rgba(255,255,255,0.35)', cursor: 'help' }} />
    </Tooltip>
  )
}

/* ========== 常量 ========== */
const CRAWLER_OPTIONS = [
  { label: 'JavDB', value: 'javdb' },
  { label: 'JavBus', value: 'javbus' },
  { label: 'AirAV', value: 'airav' },
  { label: 'AVSOX', value: 'avsox' },
  { label: 'AVWiki', value: 'avwiki' },
  { label: 'Fanza', value: 'fanza' },
  { label: 'FC2', value: 'fc2' },
  { label: 'FC2Fan', value: 'fc2fan' },
  { label: 'FC2PPVDB', value: 'fc2ppvdb' },
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

const isLLMEngine = (engine: string) => ['openai', 'claude', 'googleai', 'localai'].includes(engine)

const NAMING_VARIABLES = [
  { var: '{num}', desc: '影片番号', example: 'SSIS-001', note: '优先 DVD ID，cid 模式下为 cid' },
  { var: '{title}', desc: '影片标题（翻译后）', example: '标题内容' },
  { var: '{rawtitle}', desc: '原始标题（翻译前）', example: '原标题', note: '无论是否翻译，始终为原始标题' },
  { var: '{actress}', desc: '女优名', example: '三上悠亜', note: '多个用逗号分隔' },
  { var: '{censor}', desc: '有码/无码', example: '有码', note: '三种状态：有码/无码/不确定' },
  { var: '{score}', desc: '影片评分', example: '7.81', note: '10 分制' },
  { var: '{serial}', desc: '系列', example: '系列名' },
  { var: '{label}', desc: '番号系列标签', example: 'SSIS', note: '番号拆分后的系列前缀' },
  { var: '{director}', desc: '导演', example: '导演名' },
  { var: '{producer}', desc: '制作商', example: '制作商名' },
  { var: '{publisher}', desc: '发行商', example: '发行商名' },
  { var: '{date}', desc: '发行日期', example: '2020-05-20' },
  { var: '{year}', desc: '发行年份', example: '2020' },
]

const CHECKER_NFO_TITLE_PRESETS = [
  { value: '', label: '使用全局NFO标题格式' },
  { value: '{title}', label: 'Jellyfin 标准格式' },
  { value: '{num} {title}', label: 'Kodi 格式 (番号+标题)' },
  { value: '{num} - {title}', label: '飞牛 NAS 格式 (番号-标题)' },
  { value: '{actress} - {num} {title}', label: '标准格式 (女优-番号 标题)' },
]

/* ========== 变量提示组件 ========== */
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

/* ========== 文件相关：扫描设置 ========== */
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
          <Form.Item
            label={<span>源文件夹路径<Tip text="要扫描的影片文件夹路径。留空则运行时询问。支持变量如 /Volumes/data/download" /></span>}
            name="input_directory"
          >
            <Input placeholder="/path/to/movies" />
          </Form.Item>
          <Form.Item
            label={<span>最小文件大小<Tip text="匹配番号时忽略小于此大小的文件。格式如 232MiB、1GiB。过小的文件通常不是影片" /></span>}
            name="minimum_size"
          >
            <Input placeholder="232MiB" />
          </Form.Item>
          <Form.Item
            label={<span>跳过已有NFO的目录<Tip text="开启后，如果目录下已有 .nfo 文件，将跳过该目录不再重新刮削。适合增量扫描" /></span>}
            name="skip_nfo_dir" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>重新扫描时清理 .skipped<Tip text="开启后，重新扫描时会清除之前的 .skipped 标记文件，解决文件数不变的问题" /></span>}
            name="clear_skipped_on_rescan" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

/* ========== 文件相关：整理设置 ========== */
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
        file_basename_pattern: s.file_basename_pattern || '',
        nfo_title_pattern: s.nfo_title_pattern || '{title}',
        checker_nfo_title_pattern: s.checker_nfo_title_pattern || '',
        checker_default_path: s.checker_default_path || '',
        hard_link: s.hard_link ?? false,
        length_maximum: s.length_maximum ?? 250,
        max_actress_count: s.max_actress_count ?? 10,
        remove_trailing_actor_name: s.remove_trailing_actor_name ?? true,
        cover_basename: s.cover_basename || 'poster',
        fanart_basename: s.fanart_basename || 'fanart',
        nfo_basename: s.nfo_basename || '[{num}]',
        extra_fanarts_enabled: s.extra_fanarts_enabled ?? true,
        extra_fanarts_concurrent: s.extra_fanarts_concurrent ?? 3,
        extra_fanarts_max: s.extra_fanarts_max ?? 6,
      })
    }).finally(() => setLoading(false))
  }, [])

  return (
    <Card title="整理与命名" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item
            label={<span>输出文件夹路径<Tip text="整理后文件存放的根目录。支持变量，如 /Movies/{actress}/{num}。女优名会自动创建子文件夹" /></span>}
            name="output_folder_pattern"
          >
            <Input placeholder="/path/to/output/{actress}/{num}" />
          </Form.Item>
          <Form.Item
            label={<span>移动文件（否则复制）<Tip text="开启：将文件移动到目标目录（节省空间）；关闭：复制文件到目标目录（保留原文件）" /></span>}
            name="move_files" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>文件命名规则<Tip text="影片、封面、NFO 等文件的命名规则。支持变量，如 {title}、[{num}] {title}" /></span>}
            name="basename_pattern"
          >
            <Input placeholder="{title}" />
          </Form.Item>
          <Form.Item
            label={<span>NFO 标题格式<Tip text="NFO 文件中 <title> 字段的格式。Jellyfin/Emby 等媒体管理器会显示此标题" /></span>}
            name="nfo_title_pattern"
          >
            <Input placeholder="{title}" />
          </Form.Item>
          <Form.Item
            label={<span>影片文件单独命名规则<Tip text="影片文件（mkv/mp4等）的独立命名规则，留空则使用上方的通用命名规则。支持变量如 {num}-{title}" /></span>}
            name="file_basename_pattern"
          >
            <Input placeholder="留空则与通用命名规则相同" />
          </Form.Item>
          <Form.Item
            label={<span>硬链接模式<Tip text="开启后使用硬链接代替移动/复制文件，不占用额外磁盘空间，但要求源和目标在同一分区" /></span>}
            name="hard_link" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>最大文件路径长度<Tip text="允许的最长文件路径（字符数）。超过此长度的路径会被自动截短，避免系统限制导致文件无法保存" /></span>}
            name="length_maximum"
          >
            <InputNumber min={100} max={500} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label={<span>最大女优数量<Tip text="路径中 {actress} 变量最多包含多少名女优。设为 1 表示只取第一女优名作为子文件夹" /></span>}
            name="max_actress_count"
          >
            <InputNumber min={1} max={50} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label={<span>删除标题尾部女优名<Tip text="有些网站会在标题末尾附带女优名，开启后会自动删除，避免标题重复冗长" /></span>}
            name="remove_trailing_actor_name" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>封面文件名<Tip text="封面图片的文件名（不含扩展名）。如 poster → poster.jpg" /></span>}
            name="cover_basename"
          >
            <Input placeholder="poster" />
          </Form.Item>
          <Form.Item
            label={<span>横版封面文件名<Tip text="横版封面图片的文件名（不含扩展名）。如 fanart → fanart.jpg" /></span>}
            name="fanart_basename"
          >
            <Input placeholder="fanart" />
          </Form.Item>
          <Form.Item
            label={<span>NFO 文件名<Tip text="NFO 文件的命名规则（不含扩展名）。支持变量，如 [{num}] → [ABCD-123].nfo" /></span>}
            name="nfo_basename"
          >
            <Input placeholder="[{num}]" />
          </Form.Item>
          <Form.Item
            label={<span>下载剧照<Tip text="是否下载剧照到 extrafanart 文件夹。Jellyfin/Emby 等媒体管理器会展示这些剧照" /></span>}
            name="extra_fanarts_enabled" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>并发下载剧照数量<Tip text="同时下载几张剧照。增大可加快下载速度，但可能被站点限流" /></span>}
            name="extra_fanarts_concurrent"
          >
            <InputNumber min={1} max={10} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label={<span>最大剧照数量<Tip text="最多下载几张剧照。设为 0 表示不限制，下载所有可用剧照" /></span>}
            name="extra_fanarts_max"
          >
            <InputNumber min={0} max={20} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label={<span>检查器 NFO 标题格式<Tip text="命名检查器重新刮削时使用的 NFO 标题格式。留空则使用上方的全局 NFO 标题格式" /></span>}
            name="checker_nfo_title_pattern"
          >
            <Select options={CHECKER_NFO_TITLE_PRESETS} />
          </Form.Item>
          <Form.Item
            label={<span>文件检查器默认扫描路径<Tip text="命名检查页面的默认扫描路径。可设置为外挂硬盘路径，方便快速检查" /></span>}
            name="checker_default_path"
          >
            <Input placeholder="/Volumes/data/movies" />
          </Form.Item>
          <VariableHint />
        </Form>
      </Spin>
    </Card>
  )
}

/* ========== 文件相关：封面设置 ========== */
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
          <Form.Item
            label={<span>下载高清封面<Tip text="高清封面约 8-10 MiB，普通封面约 200-500 KiB。网络不佳时建议关闭以提升速度" /></span>}
            name="highres" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>添加水印标签<Tip text="在封面上添加水印标签（如「字幕」「破解」等），便于在媒体管理器中快速识别" /></span>}
            name="add_label" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

/* ========== 文件相关：媒体库管理 ========== */
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
      title="媒体库"
      variant="borderless"
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加媒体库</Button>}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="媒体库用于管理多个不同的影片存储路径。刮削页面可选择特定媒体库进行扫描。第一个添加的媒体库自动设为默认。"
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

/* ========== 刮削相关：爬虫设置（含镜像地址） ========== */
function CrawlerConfig({ saving, onSave }: { saving: boolean; onSave: (group: string, v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetchConfig('crawler'),
      fetchConfig('network'),
    ]).then(([crawlerRes, networkRes]) => {
      const c = crawlerRes.data?.crawler || {}
      const mirrors = networkRes.data?.network?.crawler_mirror || {}
      form.setFieldsValue({
        selection_normal: c.selection_normal || [],
        selection_fc2: c.selection_fc2 || [],
        hardworking: c.hardworking ?? true,
        sleep_after_scraping: c.sleep_after_scraping || 'PT1S',
        required_keys: c.required_keys || ['cover', 'title'],
        respect_site_avid: c.respect_site_avid ?? true,
        use_javdb_cover: c.use_javdb_cover || 'fallback',
        normalize_actress_name: c.normalize_actress_name ?? true,
        crawler_mirror: Object.entries(mirrors).map(([k, v]) => `${k}=${v}`).join('\n'),
      })
    }).finally(() => setLoading(false))
  }, [])

  const handleSubmit = (values: any) => {
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
    const { crawler_mirror, ...crawlerValues } = values
    onSave('crawler', crawlerValues)
    onSave('network', { crawler_mirror: mirrors })
  }

  return (
    <Card title="爬虫设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item
            label={<span>普通影片爬虫列表<Tip text="按优先级排序，靠前的优先使用。多个爬虫并行抓取后汇总数据，排名靠前的字段优先被采用。建议保留 javdb 作为首选" /></span>}
            name="selection_normal"
          >
            <Select mode="multiple" options={CRAWLER_OPTIONS} placeholder="选择爬虫" />
          </Form.Item>
          <Form.Item
            label={<span>FC2 影片爬虫列表<Tip text="FC2 影片使用的爬虫列表。FC2 影片编号格式与普通影片不同，需要专门的爬虫" /></span>}
            name="selection_fc2"
          >
            <Select mode="multiple" options={CRAWLER_OPTIONS} placeholder="选择爬虫" />
          </Form.Item>
          <Form.Item
            label={<span>努力爬取更多信息<Tip text="开启后会尝试从每个站点抓取更多信息字段（如预告片、更多剧照等）。会略微增加部分站点的爬取耗时" /></span>}
            name="hardworking" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>刮削后等待时间<Tip text="每刮削一部影片后的等待时间，ISO 8601 Duration 格式。如 PT1S = 1秒，PT0S = 不等待。用于避免被站点限流" /></span>}
            name="sleep_after_scraping"
          >
            <Input placeholder="PT1S" />
          </Form.Item>
          <Form.Item
            label={<span>必要字段<Tip text="爬虫至少要获取到哪些字段才算抓取成功。缺少这些字段的爬虫结果会被丢弃" /></span>}
            name="required_keys"
          >
            <Select mode="multiple" options={[
              { value: 'cover', label: '封面' },
              { value: 'title', label: '标题' },
              { value: 'actress', label: '女优' },
              { value: 'genre', label: '标签' },
              { value: 'studio', label: '片商' },
            ]} placeholder="选择必要字段" />
          </Form.Item>
          <Form.Item
            label={<span>尊重网页番号<Tip text="使用网页上显示的番号作为最终番号（会对大小写进行更正）。关闭则始终使用文件名解析的番号" /></span>}
            name="respect_site_avid" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>使用 javdb 封面<Tip text="是否使用 javdb 站点的封面。yes=始终使用, no=不使用, fallback=其他爬虫没有封面时作为备选" /></span>}
            name="use_javdb_cover"
          >
            <Select options={[
              { value: 'fallback', label: '备选 (fallback)' },
              { value: 'yes', label: '始终使用 (yes)' },
              { value: 'no', label: '不使用 (no)' },
            ]} />
          </Form.Item>
          <Form.Item
            label={<span>统一女优艺名<Tip text="开启后会将同一个女优的多个艺名统一为一个名字。如「三上悠亚」和「三上悠亜」会被统一" /></span>}
            name="normalize_actress_name" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>爬虫镜像地址<Tip text="配置自建镜像或反向代理地址，配置后优先使用镜像而非直连站点。每行一个，格式：爬虫名=地址。如 javdb=https://mirror.example.com。留空或清空则不使用镜像" /></span>}
            name="crawler_mirror"
          >
            <Input.TextArea
              placeholder={"javdb=https://your-mirror.example.com/javdb\njavbus=https://your-mirror.example.com/javbus\nairav=https://your-mirror.example.com/airav"}
              rows={4}
            />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

/* ========== 刮削相关：翻译设置 ========== */
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
        baidu_app_id: t.baidu_app_id || '',
        bing_api_key: t.bing_api_key || '',
        api_url: t.api_url || '',
        api_key: t.api_key || '',
        model: t.model || '',
      })
    }).finally(() => setLoading(false))
  }, [])

  const handleEngineChange = (val: string) => {
    setEngine(val)
  }

  return (
    <Card title="翻译设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item
            label={<span>翻译引擎<Tip text="选择翻译引擎。Google 免费但质量一般；大模型翻译质量最好但需要 API；留空则不翻译标题和简介" /></span>}
            name="engine"
          >
            <Select options={TRANSLATE_ENGINES} onChange={handleEngineChange} style={{ width: 320 }} />
          </Form.Item>

          {engine && (
            <Form.Item
              label={<span>翻译标题<Tip text="是否将影片标题翻译为中文。关闭则保留原始日文标题" /></span>}
              name="translate_title" valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          )}
          {engine && (
            <Form.Item
              label={<span>翻译剧情简介<Tip text="是否将影片剧情简介翻译为中文。关闭则保留原始语言" /></span>}
              name="translate_plot" valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          )}

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

          {engine === 'bing' && (
            <Form.Item label="Azure 认知服务密钥" name="bing_api_key" rules={[{ required: true, message: '请输入 API Key' }]}>
              <Input.Password placeholder="微软必应翻译 (Azure 认知服务) 的密钥" />
            </Form.Item>
          )}

          {engine === 'claude' && (
            <Form.Item label="Claude API Key" name="api_key" rules={[{ required: true, message: '请输入 API Key' }]}>
              <Input.Password placeholder="Claude API 密钥" />
            </Form.Item>
          )}

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

          {engine === 'openai' && (
            <>
              <Form.Item
                label="API 地址"
                name="api_url"
                rules={[{ required: true, message: '请输入 API 地址' }]}
                extra="任何兼容 OpenAI Chat Completions 的接口地址"
              >
                <Input placeholder="https://api.openai.com/v1/chat/completions" />
              </Form.Item>
              <Form.Item
                label="API Key"
                name="api_key"
                extra="留空则不使用密钥（部分本地部署无需密钥）"
              >
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item
                label="模型名称"
                name="model"
                rules={[{ required: true, message: '请输入模型名称' }]}
                extra="例如: gpt-3.5-turbo, qwen/qwen2.5-vl-7b, llama-3.1-70b-versatile"
              >
                <Input placeholder="gpt-3.5-turbo" />
              </Form.Item>
            </>
          )}

          {engine === 'localai' && (
            <>
              <Form.Item
                label="API 地址"
                name="api_url"
                rules={[{ required: true, message: '请输入 API 地址' }]}
                extra="LM Studio 默认地址为 http://localhost:1234"
              >
                <Input placeholder="http://localhost:1234" />
              </Form.Item>
              <Form.Item
                label="API Key"
                name="api_key"
                extra="LM Studio 默认不需要密钥，留空即可"
              >
                <Input.Password placeholder="留空" />
              </Form.Item>
              <Form.Item
                label="模型名称"
                name="model"
                rules={[{ required: true, message: '请输入模型名称' }]}
                extra="在 LM Studio 中加载的模型名称"
              >
                <Input placeholder="hy-mt2-7b" />
              </Form.Item>
            </>
          )}

          {engine === 'google' && (
            <Alert type="info" showIcon message="Google 翻译免费使用，无需配置 API Key。翻译质量中等，适合日常使用。" />
          )}
        </Form>
      </Spin>
    </Card>
  )
}

/* ========== 网络相关：网络设置 ========== */
function NetworkConfig({ saving, onSave }: { saving: boolean; onSave: (v: any) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchConfig('network').then(({ data }) => {
      const n = data?.network || {}
      form.setFieldsValue({
        proxy_server: n.proxy_server || '',
        retry: n.retry ?? 3,
        timeout: n.timeout || 'PT10S',
        ssl_verification: n.ssl_verification ?? true,
      })
    }).finally(() => setLoading(false))
  }, [])

  return (
    <Card title="网络设置" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item
            label={<span>代理服务器<Tip text="全局代理地址，支持 http 和 socks5/socks5h 协议。留空则不使用代理。例：http://127.0.0.1:1080 或 socks5://127.0.0.1:1080" /></span>}
            name="proxy_server"
          >
            <Input placeholder="http://127.0.0.1:1080" />
          </Form.Item>
          <Form.Item
            label={<span>重试次数<Tip text="网络请求失败时的重试次数。通常 3 次即可。设为 0 则不重试" /></span>}
            name="retry"
          >
            <InputNumber min={0} max={10} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item
            label={<span>超时时间<Tip text="网络请求超时时间，ISO 8601 Duration 格式。PT10S=10秒，PT30S=30秒。网络较慢时可适当增大" /></span>}
            name="timeout"
          >
            <Input placeholder="PT10S" />
          </Form.Item>
          <Form.Item
            label={<span>SSL 证书验证<Tip text="是否验证 HTTPS 证书。关闭可解决部分自签证书的报错，但安全性降低。正常情况建议开启" /></span>}
            name="ssl_verification" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

/* ========== 网络相关：文件监控 ========== */
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
    <Card title="文件监控" variant="borderless" extra={
      <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={() => form.submit()}>保存</Button>
    }>
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item
            label={<span>启用文件监控<Tip text="监控指定目录的文件变动，检测到新文件时自动触发刮削。需要配合「文件监控」页面添加监控路径" /></span>}
            name="enabled" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label={<span>自动刮削新文件<Tip text="检测到新文件后是否自动开始刮削。关闭则仅通知不自动处理" /></span>}
            name="auto_scrape" valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Spin>
    </Card>
  )
}

/* ========== 主页面 ========== */
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
            key: 'file',
            label: '文件设置',
            children: (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <ScannerConfig saving={saving} onSave={(v) => handleSave('scanner', v)} />
                <SummarizerConfig saving={saving} onSave={(v) => handleSave('summarizer', v)} />
                <CoverConfig saving={saving} onSave={(v) => handleSave('cover', v)} />
                <MediaLibraryConfig />
              </Space>
            ),
          },
          {
            key: 'scrape',
            label: '刮削设置',
            children: (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <CrawlerConfig saving={saving} onSave={handleSave} />
                <TranslatorConfig saving={saving} onSave={(v) => handleSave('translator', v)} />
              </Space>
            ),
          },
          {
            key: 'network',
            label: '网络设置',
            children: (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <NetworkConfig saving={saving} onSave={(v) => handleSave('network', v)} />
                <WatcherConfig saving={saving} onSave={(v) => handleSave('watcher', v)} />
              </Space>
            ),
          },
        ]}
      />
    </div>
  )
}
