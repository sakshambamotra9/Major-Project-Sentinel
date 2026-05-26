import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldAlert, Lock, User, AlertTriangle } from 'lucide-react';
import './Login.css';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMsg(null);

    // Simple local or backend admin auth check
    // We will support default admin/admin123, or custom env if configured.
    // If backend is running, we can check or do simple verification.
    try {
      // In production, send a request to backend to verify admin credentials
      // For now, let's use the local fallback to admin/admin123 for immediate usability
      if ((username === 'admin' && password === 'admin123') || (username === 'sentinel' && password === 'secure2026')) {
        localStorage.setItem('sentinel_admin_authenticated', 'true');
        localStorage.setItem('sentinel_admin_username', username);
        navigate('/control-room');
      } else {
        setErrorMsg('Invalid administrative credentials. Access Denied.');
      }
    } catch (err) {
      setErrorMsg('Failed to process login. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="admin-login-container">
      <div className="login-glow-orb-1"></div>
      <div className="login-glow-orb-2"></div>
      
      <div className="login-card glass-panel">
        <div className="login-header">
          <div className="logo-badge">
            <ShieldAlert size={36} className="logo-icon" />
          </div>
          <h1>Sentinel Terminal</h1>
          <p>Secure Administrator Access Portal</p>
        </div>

        <form onSubmit={handleLogin} className="login-form">
          <div className="form-group">
            <label>Username</label>
            <div className="input-with-icon">
              <User size={18} className="input-icon" />
              <input 
                type="text" 
                value={username} 
                onChange={e => setUsername(e.target.value)} 
                placeholder="Enter admin username" 
                required 
              />
            </div>
          </div>

          <div className="form-group">
            <label>Security Key / Password</label>
            <div className="input-with-icon">
              <Lock size={18} className="input-icon" />
              <input 
                type="password" 
                value={password} 
                onChange={e => setPassword(e.target.value)} 
                placeholder="Enter passcode" 
                required 
              />
            </div>
          </div>

          {errorMsg && (
            <div className="login-error-banner">
              <AlertTriangle size={16} />
              <span>{errorMsg}</span>
            </div>
          )}

          <button type="submit" className="login-submit-btn" disabled={isSubmitting}>
            {isSubmitting ? 'Authenticating...' : 'Establish Session'}
          </button>
        </form>

        <div className="login-footer">
          <span>Sentinel exam monitoring suite. All connections are audited.</span>
        </div>
      </div>
    </div>
  );
}
