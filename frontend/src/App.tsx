import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import InterviewPage from './pages/Interview';
import InterviewDone from './pages/InterviewDone';
import AdminLogin from './pages/AdminLogin';
import AdminInterviews from './pages/AdminInterviews';
import AdminInterviewDetail from './pages/AdminInterviewDetail';

const RequireAdminAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const token = localStorage.getItem('admin_token');
  if (!token) {
    return <Navigate to="/admin/login" replace />;
  }
  return <>{children}</>;
};

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/interview/:token" element={<InterviewPage />} />
        <Route path="/interview/:token/done" element={<InterviewDone />} />
        <Route path="/admin/login" element={<AdminLogin />} />
        <Route 
          path="/admin/interviews" 
          element={
            <RequireAdminAuth>
              <AdminInterviews />
            </RequireAdminAuth>
          } 
        />
        <Route 
          path="/admin/interviews/:id" 
          element={
            <RequireAdminAuth>
              <AdminInterviewDetail />
            </RequireAdminAuth>
          } 
        />
        <Route path="/" element={<Navigate to="/admin/login" />} />
      </Routes>
    </Router>
  );
}

export default App;
