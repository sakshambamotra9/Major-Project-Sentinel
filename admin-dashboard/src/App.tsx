import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ControlRoom from './pages/ControlRoom';
import ExamManagement from './pages/ExamManagement';
import StudentsManagement from './pages/StudentsManagement';
import Login from './pages/Login';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(
    localStorage.getItem('sentinel_admin_authenticated') === 'true'
  );

  useEffect(() => {
    const handleStorageChange = () => {
      setIsAuthenticated(localStorage.getItem('sentinel_admin_authenticated') === 'true');
    };
    window.addEventListener('storage', handleStorageChange);
    const interval = setInterval(handleStorageChange, 500);
    return () => {
      window.removeEventListener('storage', handleStorageChange);
      clearInterval(interval);
    };
  }, []);

  return (
    <Router>
      <div className="app-container">
        {isAuthenticated && <Sidebar />}
        <main className={isAuthenticated ? "main-content" : "main-content-auth"}>
          <Routes>
            <Route 
              path="/login" 
              element={isAuthenticated ? <Navigate to="/control-room" replace /> : <Login />} 
            />
            <Route 
              path="/control-room" 
              element={isAuthenticated ? <ControlRoom /> : <Navigate to="/login" replace />} 
            />
            <Route 
              path="/exams" 
              element={isAuthenticated ? <ExamManagement /> : <Navigate to="/login" replace />} 
            />
            <Route 
              path="/students" 
              element={isAuthenticated ? <StudentsManagement /> : <Navigate to="/login" replace />} 
            />
            <Route 
              path="*" 
              element={<Navigate to={isAuthenticated ? "/control-room" : "/login"} replace />} 
            />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
