import { useState, useEffect } from 'react';
import { supabase } from '../supabase';
import './ControlRoom.css';

const getCleanCid = (cid: string | null): string => {
  if (!cid) return "";
  const trimmed = cid.trim();
  if (trimmed.includes('/ipfs/')) {
    const parts = trimmed.split('/ipfs/');
    return parts[parts.length - 1].split('?')[0];
  }
  if (trimmed.includes('pinata.cloud/')) {
    const parts = trimmed.split('/');
    return parts[parts.length - 1].split('?')[0];
  }
  return trimmed;
};

interface Session {
  id: string;
  student_id: string;
  student_name?: string;
  semester?: string;
  exam_id: string;
  status: string;
  risk_score: number;
  risk_label: string;
  started_at: any;
  last_updated: any;
  violations: Array<{
    type: string;
    time: string;
    cid: string | null;
  }>;
}

export default function ControlRoom() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSession, setSelectedSession] = useState<Session | null>(null);

  useEffect(() => {
    const fetchInitialSessions = async () => {
      try {
        const { data, error } = await supabase
          .from('sessions')
          .select('*')
          .order('last_updated', { ascending: false });
        
        if (error) throw error;
        
        if (data) {
          const activeSessions = data.map(s => ({ id: s.student_id, ...s }) as Session);
          setSessions(activeSessions);
          
          if (selectedSession) {
            const updated = activeSessions.find(s => s.id === selectedSession.id);
            if (updated) setSelectedSession(updated);
          }
        }
      } catch (error: any) {
        console.error("Supabase fetch error:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchInitialSessions();

    const channel = supabase
      .channel('sessions-realtime')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'sessions' },
        () => {
          fetchInitialSessions();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [selectedSession]);

  const unpinCids = async (cids: string[]) => {
    for (const cid of cids) {
      if (!cid) continue;
      const cleanCid = getCleanCid(cid);
      try {
        await fetch(`http://127.0.0.1:8000/api/v1/ipfs/unpin/${cleanCid}`, {
          method: 'DELETE'
        });
        console.log(`Unpinned CID: ${cleanCid}`);
      } catch (e) {
        console.warn(`Failed to unpin CID ${cleanCid}:`, e);
      }
    }
  };

  const forceTerminateSession = async (studentId: string) => {
    if (window.confirm("Are you sure you want to FORCE TERMINATE this student's live exam?")) {
      const { error } = await supabase
        .from('sessions')
        .update({ 
          status: 'terminated', 
          termination_reason: 'Terminated by Admin' 
        })
        .eq('student_id', studentId);
      if (error) {
        alert("Failed to force terminate session: " + error.message);
      } else {
        alert("Session force terminated successfully. The student will be locked out immediately.");
      }
    }
  };

  const deleteSession = async (studentId: string) => {
    if (window.confirm("Are you sure you want to delete this session? This will also delete its violation images from Pinata IPFS.")) {
      const session = sessions.find(s => s.student_id === studentId);
      const cids = session?.violations?.map(v => v.cid).filter((cid): cid is string => !!cid) || [];

      if (cids.length > 0) {
        await unpinCids(cids);
      }

      const { error } = await supabase
        .from('sessions')
        .delete()
        .eq('student_id', studentId);
      if (error) {
        alert("Failed to delete session: " + error.message);
      } else {
        setSelectedSession(null);
      }
    }
  };

  const clearAllSessions = async () => {
    if (window.confirm("Are you sure you want to clear ALL past exam sessions? This will also delete all their violation images from Pinata IPFS. This action is irreversible.")) {
      const allCids: string[] = [];
      sessions.forEach(s => {
        s.violations?.forEach(v => {
          if (v.cid) allCids.push(v.cid);
        });
      });

      if (allCids.length > 0) {
        await unpinCids(allCids);
      }

      const { error } = await supabase
        .from('sessions')
        .delete()
        .neq('student_id', '');
      if (error) {
        alert("Failed to clear sessions: " + error.message);
      } else {
        setSelectedSession(null);
      }
    }
  };

  const getRiskColor = (label: string) => {
    switch(label) {
      case 'Low': return 'var(--success)';
      case 'Moderate': return 'var(--warning)';
      case 'High': return '#f97316';
      case 'Very High': return 'var(--danger)';
      default: return 'var(--text-muted)';
    }
  };

  return (
    <div className="control-room">
      <header className="page-header">
        <div>
          <h1>Live Control Room</h1>
          <p>Monitor active exam sessions and AI proctoring telemetry.</p>
        </div>
        <div className="stats-pills" style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
          <button 
            className="danger" 
            onClick={clearAllSessions}
            style={{ padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', background: '#dc2626', color: 'white', border: 'none' }}
          >
            🗑️ Clear All Sessions
          </button>
          <div className="pill">Active Sessions: {sessions.filter(s => s.status === 'active').length}</div>
          <div className="pill danger">Terminated: {sessions.filter(s => s.status === 'terminated').length}</div>
        </div>
      </header>

      <div className="dashboard-grid">
        <div className="sessions-list">
          {loading ? (
            <div className="loading">Connecting to Supabase...</div>
          ) : sessions.length === 0 ? (
            <div className="empty-state">No student sessions found.</div>
          ) : (
            sessions.map(session => (
              <div 
                key={session.id} 
                className={`glass-panel session-card ${selectedSession?.id === session.id ? 'selected' : ''}`}
                onClick={() => setSelectedSession(session)}
              >
                <div className="card-header">
                  <h3>{session.student_name || 'Unknown Student'}</h3>
                  <span className={`status-badge ${session.status}`}>{session.status}</span>
                </div>
                <div className="card-body">
                  <div className="info-row">
                    <span>Roll No:</span>
                    <strong>{session.student_id}</strong>
                  </div>
                  <div className="info-row">
                    <span>Semester:</span>
                    <strong>{session.semester || 'N/A'}</strong>
                  </div>
                  <div className="info-row">
                    <span>Exam:</span>
                    <strong>{session.exam_id}</strong>
                  </div>
                  <div className="risk-indicator" style={{ borderLeftColor: getRiskColor(session.risk_label) }}>
                    <span>Risk Level</span>
                    <strong style={{ color: getRiskColor(session.risk_label) }}>{session.risk_label} ({session.risk_score}%)</strong>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="glass-panel detail-panel">
          {selectedSession ? (
            <>
              <div className="glass-header detail-header" style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <h2>Session Details</h2>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: '10px' }}>
                  {selectedSession.status === 'active' && (
                    <button 
                      className="danger" 
                      onClick={() => forceTerminateSession(selectedSession.student_id)}
                      style={{ padding: '6px 12px', background: '#dc2626', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold', fontSize: '12px' }}
                    >
                      🛑 Force Terminate
                    </button>
                  )}
                  <button 
                    onClick={() => deleteSession(selectedSession.student_id)}
                    style={{ padding: '6px 12px', background: '#4b5563', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold', fontSize: '12px' }}
                  >
                    🗑️ Delete
                  </button>
                </div>
              </div>
              <div className="detail-body">
                <h3>{selectedSession.student_name || selectedSession.student_id}</h3>
                <p className="subtitle">Exam: {selectedSession.exam_id} • Semester: {selectedSession.semester}</p>
                
                <h4 className="section-title">Telemetry Timeline ({selectedSession.violations?.length || 0} events)</h4>
                
                {selectedSession.violations && selectedSession.violations.length > 0 ? (
                  <div className="timeline">
                    {/* Reverse to show newest first */}
                    {[...selectedSession.violations].reverse().map((v, i) => (
                      <div key={i} className="timeline-event">
                        <div className="event-time">{v.time}</div>
                        <div className="event-content">
                          <p className="event-type">⚠️ {v.type}</p>
                          {v.cid && (
                            <div className="ipfs-evidence">
                              <span>IPFS Evidence Captured</span>
                              <img 
                                src={`http://127.0.0.1:8080/ipfs/${getCleanCid(v.cid)}`} 
                                onError={(e) => {
                                  const target = e.target as HTMLImageElement;
                                  if (target.src.startsWith('http://127.0.0.1:8080')) {
                                    target.src = `https://ipfs.io/ipfs/${getCleanCid(v.cid)}`;
                                  }
                                }}
                                alt="Violation Snapshot" 
                              />
                              <div className="cid-link-wrapper" style={{ display: 'flex', flexDirection: 'column', gap: '5px', marginTop: '8px' }}>
                                <span style={{ fontSize: '11px', color: 'var(--text-muted)', wordBreak: 'break-all' }}>CID: <code>{getCleanCid(v.cid)}</code></span>
                                <div style={{ display: 'flex', gap: '10px' }}>
                                  <a 
                                    href={`http://127.0.0.1:8080/ipfs/${getCleanCid(v.cid)}`} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="cid-link"
                                    style={{ fontSize: '12px' }}
                                  >
                                    🔗 Local Gateway
                                  </a>
                                  <a 
                                    href={`https://ipfs.io/ipfs/${getCleanCid(v.cid)}`} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="cid-link"
                                    style={{ fontSize: '12px' }}
                                  >
                                    🌐 Public Gateway
                                  </a>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">No anomalies detected during this session.</div>
                )}
              </div>
            </>
          ) : (
            <div className="empty-state" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              Select a student session to view live telemetry and snapshots.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
