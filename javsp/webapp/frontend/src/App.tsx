import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import { Layout, Menu, Typography, Badge } from 'antd'
import {
  DashboardOutlined,
  PlayCircleOutlined,
  SettingOutlined,
  FolderOutlined,
  UnorderedListOutlined,
  FileTextOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import Dashboard from './pages/Dashboard'
import Scrape from './pages/Scrape'
import Tasks from './pages/Tasks'
import Config from './pages/Config'
import Watcher from './pages/Watcher'
import Logs from './pages/Logs'
import MovieDetail from './pages/MovieDetail'
import Checker from './pages/Checker'
import { SocketProvider } from './hooks/useSocket'

const { Header, Sider, Content } = Layout

function AppLayout() {
  const location = useLocation()

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: <Link to="/">仪表盘</Link> },
    { key: '/scrape', icon: <PlayCircleOutlined />, label: <Link to="/scrape">开始刮削</Link> },
    { key: '/tasks', icon: <UnorderedListOutlined />, label: <Link to="/tasks">任务列表</Link> },
    { key: '/config', icon: <SettingOutlined />, label: <Link to="/config">配置管理</Link> },
    { key: '/watcher', icon: <FolderOutlined />, label: <Link to="/watcher">文件监控</Link> },
    { key: '/logs', icon: <FileTextOutlined />, label: <Link to="/logs">操作日志</Link> },
    { key: '/checker', icon: <ToolOutlined />, label: <Link to="/checker">命名检查</Link> },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={220}
        style={{
          background: '#1a1a2e',
          borderRight: '1px solid rgba(99,102,241,0.15)',
        }}
      >
        <div style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderBottom: '1px solid rgba(99,102,241,0.15)',
        }}>
          <Typography.Title level={4} style={{ margin: 0, color: '#6366f1' }}>
            Jav Manager
          </Typography.Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          style={{ background: 'transparent', borderRight: 0, marginTop: 8 }}
        />
      </Sider>
      <Layout>
        <Header style={{
          background: '#1e1e2e',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <Typography.Text style={{ color: 'rgba(255,255,255,0.65)' }}>
            汇总多站点数据的 AV 元数据刮削器
          </Typography.Text>
          <Badge status="processing" text={<span style={{ color: 'rgba(255,255,255,0.45)' }}>运行中</span>} />
        </Header>
        <Content style={{ margin: 16, overflow: 'auto' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/scrape" element={<Scrape />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/config" element={<Config />} />
            <Route path="/watcher" element={<Watcher />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/movie" element={<MovieDetail />} />
            <Route path="/checker" element={<Checker />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <SocketProvider>
        <AppLayout />
      </SocketProvider>
    </BrowserRouter>
  )
}
