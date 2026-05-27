import React, { useState } from 'react';
import { Shield, KeyRound, Mail, CheckCircle2, AlertTriangle } from 'lucide-react';
import './ExamManagement.css'; // Leverage existing dashboard styles

export default function Settings() {
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [otp, setOtp] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSendOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUsername.trim() || !newPassword.trim()) {
      setErrorMsg("Please enter both a username and password.");
      return;
    }
    setIsSubmitting(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      const response = await fetch('http://127.0.0.1:8000/api/v1/admin/send_otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: newUsername.trim(),
          password: newPassword.trim(),
        }),
      });

      const data = await response.json();
      if (response.ok) {
        setOtpSent(true);
        setSuccessMsg(data.message || "Verification code successfully sent to registered email!");
      } else {
        setErrorMsg(data.detail || "Failed to send verification code. Please try again.");
      }
    } catch (err) {
      setErrorMsg("Failed to communicate with authentication server.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleVerifyAndRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!otp.trim()) {
      setErrorMsg("Please enter the 6-digit verification code.");
      return;
    }
    setIsSubmitting(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      const response = await fetch('http://127.0.0.1:8000/api/v1/admin/verify_otp_and_register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: newUsername.trim(),
          password: newPassword.trim(),
          otp: otp.trim(),
        }),
      });

      const data = await response.json();
      if (response.ok) {
        setSuccessMsg(data.message || "Administrator registered successfully!");
        setNewUsername('');
        setNewPassword('');
        setOtp('');
        setOtpSent(false);
      } else {
        setErrorMsg(data.detail || "Invalid code or registration failed.");
      }
    } catch (err) {
      setErrorMsg("Failed to complete registration process.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="management-container">
      <div className="page-header">
        <div>
          <h1>System Settings</h1>
          <p className="subtitle">Configure system security and register administrative accounts.</p>
        </div>
      </div>

      <div style={{ maxWidth: '600px', marginTop: '20px' }} className="exam-card glass-panel">
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px', borderBottom: '1px solid var(--border-light)', paddingBottom: '15px' }}>
          <Shield size={24} style={{ color: 'var(--primary)' }} />
          <h2 style={{ margin: 0, fontSize: '20px', color: 'var(--text-main)' }}>Register New Administrator</h2>
        </div>

        <p style={{ color: 'var(--text-muted)', fontSize: '14px', lineHeight: '1.6', marginBottom: '20px' }}>
          To add a new administrator, fill in the credentials below. For security, a 6-digit verification code will be sent to the primary email (<strong>2022a6r040@mietjammu.in</strong>) before the user can be registered.
        </p>

        {successMsg && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', backgroundColor: 'rgba(16, 185, 129, 0.15)', border: '1px solid rgba(16, 185, 129, 0.3)', color: '#34d399', padding: '12px', borderRadius: '8px', marginBottom: '20px', fontSize: '14px' }}>
            <CheckCircle2 size={18} />
            <span>{successMsg}</span>
          </div>
        )}

        {errorMsg && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', backgroundColor: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#f87171', padding: '12px', borderRadius: '8px', marginBottom: '20px', fontSize: '14px' }}>
            <AlertTriangle size={18} />
            <span>{errorMsg}</span>
          </div>
        )}

        {!otpSent ? (
          <form onSubmit={handleSendOtp} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div className="form-group">
              <label>Admin Username</label>
              <input
                type="text"
                value={newUsername}
                onChange={e => setNewUsername(e.target.value)}
                placeholder="Enter new admin username"
                required
                disabled={isSubmitting}
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>

            <div className="form-group">
              <label>Password / Passcode</label>
              <input
                type="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                placeholder="Enter admin password"
                required
                disabled={isSubmitting}
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="action-btn primary"
              style={{ padding: '12px 20px', fontWeight: 'bold', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginTop: '10px' }}
            >
              <Mail size={18} />
              {isSubmitting ? "Generating OTP..." : "Send Verification Code"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerifyAndRegister} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ backgroundColor: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.2)', padding: '12px', borderRadius: '8px', fontSize: '14px', color: '#93c5fd', marginBottom: '10px' }}>
              Username: <strong>{newUsername}</strong>
            </div>

            <div className="form-group">
              <label>Enter 6-Digit OTP</label>
              <input
                type="text"
                value={otp}
                onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="Enter OTP code"
                required
                disabled={isSubmitting}
                style={{ width: '100%', boxSizing: 'border-box', letterSpacing: '8px', fontSize: '20px', textAlign: 'center', fontWeight: 'bold' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
              <button
                type="submit"
                disabled={isSubmitting}
                className="action-btn primary"
                style={{ flex: 1, padding: '12px 20px', fontWeight: 'bold', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
              >
                <KeyRound size={18} />
                {isSubmitting ? "Verifying..." : "Register Administrator"}
              </button>

              <button
                type="button"
                onClick={() => setOtpSent(false)}
                disabled={isSubmitting}
                className="action-btn secondary"
                style={{ padding: '12px 20px' }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
