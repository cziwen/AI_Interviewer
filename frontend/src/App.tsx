import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import InterviewPage from './pages/Interview';
import InterviewDone from './pages/InterviewDone';
import AdminLogin from './pages/AdminLogin';
import AdminInterviews from './pages/AdminInterviews';
import AdminInterviewDetail from './pages/AdminInterviewDetail';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/interview/:token" element={<InterviewPage />} />
        <Route path="/interview/:token/done" element={<InterviewDone />} />
        <Route path="/admin/login" element={<AdminLogin />} />
        <Route path="/admin/interviews" element={<AdminInterviews />} />
        <Route path="/admin/interviews/:id" element={<AdminInterviewDetail />} />
        <Route path="/" element={<Navigate to="/admin/login" />} />
      </Routes>
    </Router>
  );
}

export default App;
