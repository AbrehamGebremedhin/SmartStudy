import { useEffect, lazy, Suspense } from 'react'
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

const MCQ = lazy(() => import('./pages/MCQ'))
const MockExam = lazy(() => import('./pages/MockExam'))
const Flashcards = lazy(() => import('./pages/Flashcards'))
const Notes = lazy(() => import('./pages/Notes'))
const Chat = lazy(() => import('./pages/Chat'))
const History = lazy(() => import('./pages/History'))
const Review = lazy(() => import('./pages/Review'))

function AppShell() {
  return (
    <div className="app-shell">
      <Sidebar />
      <MobileHeader />
      <div className="main">
        <Suspense fallback={null}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/mcq" element={<MCQ />} />
            <Route path="/mock-exam" element={<MockExam />} />
            <Route path="/flashcards" element={<Flashcards />} />
            <Route path="/review" element={<Review />} />
            <Route path="/notes" element={<Notes />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/chat/:sessionId" element={<Chat />} />
            <Route path="/history" element={<History />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
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
