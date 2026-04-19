import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import UploadPage from './pages/UploadPage'
import SearchPage from './pages/SearchPage'
import AskPage from './pages/AskPage'
import WritePage from './pages/WritePage'
import './index.css'

function Nav() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 rounded font-medium transition-colors ${
      isActive ? 'bg-blue-700 text-white' : 'text-blue-100 hover:bg-blue-600'
    }`
  return (
    <nav className="bg-blue-800 text-white px-6 py-3 flex items-center gap-2 shadow">
      <span className="font-bold text-lg mr-4">CEEP</span>
      <NavLink to="/" end className={linkClass}>Upload</NavLink>
      <NavLink to="/search" className={linkClass}>Search</NavLink>
      <NavLink to="/ask" className={linkClass}>Ask</NavLink>
      <NavLink to="/write" className={linkClass}>Write</NavLink>
      <span className="ml-auto text-xs text-blue-300">Community Evidence & Engagement Platform</span>
    </nav>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <Nav />
        <main className="flex-1 container mx-auto px-4 py-8 max-w-4xl">
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/write" element={<WritePage />} />
          </Routes>
        </main>
        <footer className="text-center text-xs text-gray-400 py-4 border-t">
          CEEP — open source community tool.&nbsp;
          <a href="/privacy" className="underline">Privacy Notice</a>
        </footer>
      </div>
    </BrowserRouter>
  </React.StrictMode>
)
