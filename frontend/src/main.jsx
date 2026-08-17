import React from 'react'
import ReactDOM from 'react-dom/client'
import CitizenPage from './pages/CitizenPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import './styles.css'

// 只有兩個畫面，用路徑判斷就好，不用另外裝 router 套件
// （AGENTS.md：刻意不加狀態管理/路由這類套件）。
const Page = window.location.pathname.startsWith('/dashboard') ? DashboardPage : CitizenPage

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>,
)
