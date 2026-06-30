import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import NotFound from './pages/NotFound'
import { AuthProvider, useAuth } from './context/AuthContext'
import { syncOnLogin, startProgressSync } from './lib/progressSync'
import Sidebar from './components/layout/Sidebar'
import MobileHeader from './components/layout/MobileHeader'
import BottomNav from './components/layout/BottomNav'
import GamifyLayer from './components/ui/GamifyLayer'
import Login from './pages/Login'
import Home from './pages/Home'
import MCQ from './pages/MCQ'
import MockExam from './pages/MockExam'
import Flashcards from './pages/Flashcards'
import Notes from './pages/Notes'
import Chat from './pages/Chat'
import History from './pages/History'

function AppShell() {
  return (
    <div className="app-shell">
      <Sidebar />
      <MobileHeader />
      <div className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/mcq" element={<MCQ />} />
          <Route path="/mock-exam" element={<MockExam />} />
          <Route path="/flashcards" element={<Flashcards />} />
          <Route path="/notes" element={<Notes />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/chat/:sessionId" element={<Chat />} />
          <Route path="/history" element={<History />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
      <GamifyLayer />
      <BottomNav />
    </div>
  )
}

function PrivateRoute({ children }) {
  const { user, loading } = useAuth()
  useEffect(() => {
    if (!user) return
    startProgressSync()
    syncOnLogin()
  }, [user])
  if (loading) return null
  return user ? children : <Navigate to="/login" replace />
}

function Router() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <PrivateRoute>
            <AppShell />
          </PrivateRoute>
        }
      />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Router />
      </AuthProvider>
    </BrowserRouter>
  )
}
