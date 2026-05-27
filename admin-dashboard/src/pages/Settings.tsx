import React, { useState } from 'react';
import { Shield, CheckCircle2, AlertTriangle, UserPlus } from 'lucide-react';
import { supabase } from '../supabase';
import './ExamManagement.css'; // Leverage existing dashboard styles

export default function Settings() {
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleRegisterAdmin = async (e: React.FormEvent) => {
    e.preventDefault();
    const username = newUsername.trim();
    const password = newPassword.trim();

    if (!username || !password) {
      setErrorMsg("Please enter both a username and password.");
      return;
    }
    setIsSubmitting(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      // Direct insertion to Supabase 'admins' table
      const { error } = await supabase
        .from('admins')
        .upsert({ username, password }, { onConflict: 'username' });

      if (error) throw error;

      setSuccessMsg(`Administrator '${username}' successfully registered!`);
      setNewUsername('');
      setNewPassword('');
    } catch (err: any) {
      console.error("Supabase admin registration error:", err);
      setErrorMsg(err.message || "Failed to register administrator in Supabase.");
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
          To add a new administrator, fill in the credentials below. The new credentials will be saved directly to the database.
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

        <form onSubmit={handleRegisterAdmin} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
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
            <UserPlus size={18} />
            {isSubmitting ? "Registering..." : "Register Administrator"}
          </button>
        </form>
      </div>
    </div>
  );
}
