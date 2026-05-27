import { useEffect, useRef, useState } from 'react';
import './App.css';
import { supabase, initStudentSession, pushViolation, markSessionTerminated, markSessionCompleted, fetchPublishedExams } from './supabase';

type AppState = 'LOGIN' | 'HOME' | 'SETUP' | 'PRE_TEST' | 'EXAM' | 'TERMINATED' | 'SUBMITTED';

type RiskLevel = 'Low' | 'Moderate' | 'High' | 'Very High';

/**
 * Smart risk label function.
 * Uses cumulative score as the base, but applies hard overrides
 * for serious violation types (spoofing, multiple persons).
 */
function getRiskInfo(score: number, violations: { type: string }[]): { label: RiskLevel; color: string; barColor: string } {
  const hasSeriousViolation = violations.some(v =>
    v.type.toLowerCase().includes('multiple') ||
    v.type.toLowerCase().includes('liveness') ||
    v.type.toLowerCase().includes('spoof')
  );

  // Hard override: any spoofing or multiple-persons triggers at least High
  const effectiveScore = hasSeriousViolation ? Math.max(score, 70) : score;

  if (effectiveScore <= 0)    return { label: 'Low',       color: '#2e7d32', barColor: '#4caf50' };
  if (effectiveScore <= 30)   return { label: 'Low',       color: '#2e7d32', barColor: '#4caf50' };
  if (effectiveScore <= 60)   return { label: 'Moderate',  color: '#e65100', barColor: '#ff9800' };
  if (effectiveScore <= 85)   return { label: 'High',      color: '#b71c1c', barColor: '#f44336' };
  return                             { label: 'Very High',  color: '#4a0000', barColor: '#7f0000' };
}

function App() {
  const [appState, setAppState] = useState<AppState>('LOGIN');
  const appStateRef = useRef<AppState>('LOGIN');
  const [studentPassword, setStudentPassword] = useState('');
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [referenceImage, setReferenceImage] = useState<string | null>(null);
  const [registeringFace, setRegisteringFace] = useState(false);
  const [browserStatus, setBrowserStatus] = useState<'idle' | 'opened'>('idle');
  const [urlInput, setUrlInput] = useState('');
  const [cumulativeRisk, setCumulativeRisk] = useState(0);
  const cumulativeRiskRef = useRef(0);
  const [violations, setViolations] = useState<{ type: string; cid: string | null; time: string }[]>([]);
  const violationsRef = useRef<{ type: string; cid: string | null; time: string }[]>([]);
  const [studentId, setStudentId] = useState('');
  const [studentName, setStudentName] = useState('');
  const [semester, setSemester] = useState('');
  const [examId, setExamId] = useState('');
  const [availableExams, setAvailableExams] = useState<any[]>([]);
  const [currentQuestionIdx, setCurrentQuestionIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [timeLeft, setTimeLeft] = useState(3600); // 1 hour mock timer

  
  const [preTestChecks, setPreTestChecks] = useState({
    calibrating: true,
    faceDetected: false,
    plainBackground: false,
    livenessPassed: false,
    gazeCentered: false,
    noPhoneDetected: true,  // Start true, flips false if phone is in frame
    identityVerified: false,
  });
  
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const analyzeFrameRef = useRef<() => Promise<void>>(async () => {});
  const phoneDetectionCountRef = useRef(0);
  const lastPhoneDetectionTimeRef = useRef(0);


  useEffect(() => {
    fetchPublishedExams().then(exams => {
      setAvailableExams(exams);
      if (exams.length > 0) {
        setExamId(exams[0].id);
        setTimeLeft(exams[0].duration * 60);
      }
    }).catch(e => console.error("Error fetching exams:", e));
  }, []);
  useEffect(() => {
    appStateRef.current = appState;
  }, [appState]);

  // Keep refs in sync so callbacks always have fresh values
  useEffect(() => { cumulativeRiskRef.current = cumulativeRisk; }, [cumulativeRisk]);
  useEffect(() => { violationsRef.current = violations; }, [violations]);

  // Bulletproof interval pattern to avoid ANY stale closures
  useEffect(() => {
    analyzeFrameRef.current = analyzeFrame;
  });

  useEffect(() => {
    if (appState === 'PRE_TEST' || appState === 'EXAM') {
      const interval = setInterval(() => {
        analyzeFrameRef.current();
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [appState]);

  // Timer logic
  useEffect(() => {
    if (appState === 'EXAM') {
      const timer = setInterval(() => {
        setTimeLeft(prev => {
          if (prev <= 1) {
            submitExam();
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
      return () => clearInterval(timer);
    }
  }, [appState]);

  // Realtime Session Force-Termination check from Admin
  useEffect(() => {
    if (appState !== 'EXAM' || !studentId) return;

    console.log("Subscribing to realtime session updates for force-terminate monitoring...");
    const channel = supabase
      .channel(`session-terminate-${studentId}`)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'sessions',
          filter: `student_id=eq.${studentId}`
        },
        (payload) => {
          console.log("Realtime session update payload:", payload);
          if (payload.new && payload.new.status === 'terminated') {
            const reason = payload.new.termination_reason || 'Terminated by Admin';
            setAppState('TERMINATED');
            stopExam();
            alert(`This exam has been FORCE TERMINATED by the Administrator.\nReason: ${reason}`);
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [appState, studentId]);

  // Window Focus (Switching tab/application) detection
  useEffect(() => {
    const handleBlur = () => {
      if (appStateRef.current === 'EXAM') {
        const now = new Date().toLocaleTimeString();
        const flag = "Window focus lost (switched application/screen)";
        
        // Add 30 risk points and log violation
        setCumulativeRisk(prev => {
          const newRisk = Math.min(100, prev + 30);
          
          setViolations(prevViolations => {
            const newViolation = { type: flag, cid: null, time: now };
            const newViolations = [newViolation, ...prevViolations].slice(0, 20);
            
            // Push violation to Firebase
            pushViolation(studentId, newRisk, getRiskInfo(newRisk, newViolations).label, flag, null)
              .catch(e => console.warn('Firebase push failed:', e));
              
            return newViolations;
          });
          
          return newRisk;
        });
      }
    };

    window.addEventListener('blur', handleBlur);
    return () => window.removeEventListener('blur', handleBlur);
  }, [studentId]);

  const startPreTest = async () => {
    setRegisteringFace(true);
    try {
      if (referenceImage && referenceImage.startsWith('data:image')) {
        const registerRes = await fetch('http://127.0.0.1:8000/api/v1/register_reference', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            student_id: studentId,
            image_base64: referenceImage,
          }),
        });
        if (!registerRes.ok) {
          const errorData = await registerRes.json();
          alert(`Face registration failed: ${errorData.detail || 'Unknown error'}`);
          setRegisteringFace(false);
          return;
        }
      }
      
      const mediaStream = await navigator.mediaDevices.getUserMedia({ video: true });
      setStream(mediaStream);
      setAppState('PRE_TEST');
    } catch (err: any) {
      console.error("Error accessing webcam or registering face:", err);
      alert("Error starting system check: " + err.message);
    } finally {
      setRegisteringFace(false);
    }
  };

  const startExam = async () => {
    setAppState('EXAM');
    setCumulativeRisk(0);
    setViolations([]);
    cumulativeRiskRef.current = 0;
    violationsRef.current = [];
    // Create the student's session document in Firebase
    try {
      await initStudentSession(studentId, studentName, semester, examId);
    } catch (e) {
      console.warn('Firebase session init failed:', e);
    }
  };

  const stopExam = () => {
    if (videoRef.current && videoRef.current.srcObject) {
      const stream = videoRef.current.srcObject as MediaStream;
      stream.getTracks().forEach(track => track.stop());
    }
  };

  const terminateExam = async (reason = 'Phone detected') => {
    setAppState('TERMINATED');
    stopExam();
    try {
      await markSessionTerminated(studentId, reason);
    } catch (e) {
      console.warn('Firebase termination update failed:', e);
    }
  };

  const submitExam = async () => {
    setAppState('SUBMITTED'); 
    stopExam();
    try {
      await markSessionCompleted(studentId); 
    } catch (e) {
      console.warn('Firebase completion update failed:', e);
    }
  };

  const resetSession = () => {
    setStudentId('');
    setStudentName('');
    setStudentPassword('');
    setSemester('');
    setReferenceImage(null);
    setCumulativeRisk(0);
    setViolations([]);
    violationsRef.current = [];
    setAnswers({});
    setCurrentQuestionIdx(0);
    phoneDetectionCountRef.current = 0;
    lastPhoneDetectionTimeRef.current = 0;
    setAppState('LOGIN');
  };

  const closeApplication = () => {
    fetch('http://127.0.0.1:8000/api/v1/system/close', { method: 'POST' }).catch(() => {});
  };

  const openWifiModal = () => {
    fetch('http://127.0.0.1:8000/api/v1/system/wifi-flyout', { method: 'POST' }).catch(() => {});
  };

  const analyzeFrame = async () => {
    if (!videoRef.current || !canvasRef.current) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    
    if (!ctx) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const base64Image = canvas.toDataURL('image/jpeg');

    const currentState = appStateRef.current;

    try {
      if (currentState === 'PRE_TEST') {
        // PRE-TEST: use lightweight vision endpoint — NO IPFS upload
        const response = await fetch('http://127.0.0.1:8000/api/v1/analyze_vision', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ frame_base64: base64Image, student_id: studentId }),
        });
        if (!response.ok) return;
        const data = await response.json();
        const vision = data.result || {};
        const phoneInFrame = (vision.objects_found || []).some((obj: string) =>
          obj.toLowerCase().includes('phone') || obj.toLowerCase().includes('cell')
        );
        setPreTestChecks({
          calibrating: !!vision.calibrating,
          faceDetected: !vision.no_face_detected,
          plainBackground: !vision.background_warning,
          livenessPassed: !vision.liveness_failed,
          gazeCentered: !vision.gaze_deviation,
          noPhoneDetected: !phoneInFrame,
          identityVerified: !!vision.identity_verified,
        });

      } else if (currentState === 'EXAM') {
        // EXAM: use full behavior endpoint — IPFS upload happens here
        const response = await fetch('http://127.0.0.1:8000/api/v1/analyze_behavior', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ frame_base64: base64Image, student_id: studentId }),
        });
        if (!response.ok) return;
        const data = await response.json();
        const flags: string[] = data.flags || [];

        if (flags.length > 0) {
          // Phone → increment counter with a 3-second cooldown, terminate on 3
          const phoneDetected = flags.some(f => f.toLowerCase().includes('phone'));
          if (phoneDetected) {
            const now = Date.now();
            if (now - lastPhoneDetectionTimeRef.current > 3000) {
              lastPhoneDetectionTimeRef.current = now;
              phoneDetectionCountRef.current += 1;
              
              if (phoneDetectionCountRef.current >= 3) {
                terminateExam('Phone detected 3 times');
                return;
              }
            }
          }

          // All other violations → cumulative risk bar + Firebase push
          const frameRisk: number = data.risk_score || 0;
          const ipfsCid: string | null = data.ipfs_cid || null;
          if (frameRisk > 0) {
            const newRisk = Math.min(100, cumulativeRiskRef.current + frameRisk);
            const now = new Date().toLocaleTimeString();
            const newViolation = { type: flags.join(', '), cid: ipfsCid, time: now };
            const newViolations = [newViolation, ...violationsRef.current].slice(0, 20);

            setCumulativeRisk(newRisk);
            setViolations(newViolations);

            const riskLabel = getRiskInfo(newRisk, newViolations).label;
            pushViolation(studentId, newRisk, riskLabel, flags.join(', '), ipfsCid)
              .catch(e => console.warn('Firebase push failed:', e));
          }
        }
      }
    } catch (err) {
      console.error('Backend connection error:', err);
    }
  };

  useEffect(() => {
    return () => stopExam();
  }, []);

  useEffect(() => {
    if ((appState === 'PRE_TEST' || appState === 'EXAM') && videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [appState, stream]);

  const CheckItem = ({ label, passed }: { label: string, passed: boolean }) => (
    <div style={{ marginBottom: '8px' }}>
      {passed ? '✅' : '❌'} {label}
    </div>
  );

  const isPreTestReady = 
    !preTestChecks.calibrating && 
    preTestChecks.faceDetected && 
    preTestChecks.plainBackground && 
    preTestChecks.livenessPassed && 
    preTestChecks.gazeCentered &&
    preTestChecks.noPhoneDetected &&
    preTestChecks.identityVerified;

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  if (appState === 'SUBMITTED' || (appState === 'TERMINATED' && timeLeft <= 0)) {
    return (
      <div style={{ backgroundColor: '#2e7d32', color: 'white', height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
        <h1>EXAM SUBMITTED</h1>
        <h2>Your exam was submitted successfully.</h2>
        <p style={{ marginBottom: '30px' }}>You may return to the portal or close the application.</p>
        <div style={{ display: 'flex', gap: '20px' }}>
          <button 
            onClick={resetSession}
            style={{ padding: '12px 30px', fontSize: '18px', fontWeight: 'bold', backgroundColor: 'white', color: '#2e7d32', border: 'none', borderRadius: '8px', cursor: 'pointer', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }}
          >
            Return to Portal
          </button>
          <button 
            onClick={closeApplication}
            style={{ padding: '12px 30px', fontSize: '18px', fontWeight: 'bold', backgroundColor: 'rgba(255,255,255,0.2)', color: 'white', border: '1px solid white', borderRadius: '8px', cursor: 'pointer' }}
          >
            Close Application
          </button>
        </div>
      </div>
    );
  }

  if (appState === 'TERMINATED') {
    return (
      <div style={{ backgroundColor: 'red', color: 'white', height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
        <h1>EXAM TERMINATED</h1>
        <h2>REASON: MALPRACTICE DETECTED</h2>
        <p style={{ marginBottom: '30px' }}>Please contact your instructor immediately.</p>
        <button 
          onClick={closeApplication}
          style={{ padding: '12px 30px', fontSize: '18px', fontWeight: 'bold', backgroundColor: 'white', color: 'red', border: 'none', borderRadius: '8px', cursor: 'pointer', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }}
        >
          Close Application
        </button>
      </div>
    );
  }

  if (appState === 'LOGIN') {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '100vw',
        height: '100vh',
        backgroundColor: '#090514',
        fontFamily: 'Segoe UI, Roboto, Helvetica, Arial, sans-serif',
        position: 'relative',
        overflow: 'hidden'
      }}>
        {/* Close Button in Top Right */}
        <button 
          onClick={closeApplication}
          style={{
            position: 'absolute',
            top: '20px',
            right: '20px',
            backgroundColor: '#d32f2f',
            border: 'none',
            color: 'white',
            padding: '8px 18px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 'bold',
            fontSize: '14px',
            zIndex: 100,
            boxShadow: '0 4px 10px rgba(211, 47, 47, 0.3)'
          }}
        >
          ✕ Close Application
        </button>
        {/* Glow Effects */}
        <div style={{
          position: 'absolute',
          width: '350px',
          height: '350px',
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(124, 58, 237, 0.2) 0%, transparent 70%)',
          top: '-50px',
          left: '-50px',
          filter: 'blur(40px)',
        }}></div>
        <div style={{
          position: 'absolute',
          width: '450px',
          height: '450px',
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(79, 70, 229, 0.15) 0%, transparent 70%)',
          bottom: '-100px',
          right: '-100px',
          filter: 'blur(50px)',
        }}></div>

        <div style={{
          width: '100%',
          maxWidth: '400px',
          padding: '40px',
          borderRadius: '16px',
          background: 'rgba(30, 20, 50, 0.45)',
          border: '1px solid rgba(167, 139, 250, 0.25)',
          boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
          backdropFilter: 'blur(12px)',
          display: 'flex',
          flexDirection: 'column',
          gap: '24px',
          zIndex: 10
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '32px', marginBottom: '10px' }}>🛡️</div>
            <h1 style={{ color: '#fff', fontSize: '24px', margin: '0 0 8px 0', fontWeight: 'bold' }}>Sentinel OS</h1>
            <p style={{ color: '#a78bfa', fontSize: '14px', margin: 0 }}>Student Authentication Portal</p>
          </div>

          <form onSubmit={async (e) => {
            e.preventDefault();
            if (!studentId || !studentPassword) return;
            setIsLoggingIn(true);
            setLoginError(null);

            try {
              const res = await fetch('http://127.0.0.1:8000/api/v1/student/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  student_id: studentId,
                  password: studentPassword
                })
              });
              const data = await res.json();
              if (res.ok) {
                setStudentName(data.student_name);
                setSemester(data.semester);
                if (data.photo_url) {
                  setReferenceImage(data.photo_url);
                } else {
                  setReferenceImage('mock_url');
                }
                setAppState('SETUP');
              } else {
                setLoginError(data.detail || 'Invalid login details.');
              }
            } catch (err) {
              setLoginError('Could not connect to authentication server.');
            } finally {
              setIsLoggingIn(false);
            }
          }} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ color: '#d8b4fe', fontSize: '13px', fontWeight: '500' }}>Roll Number</label>
              <input 
                type="text" 
                value={studentId}
                onChange={e => setStudentId(e.target.value.trim())}
                placeholder="Enter Roll Number"
                required
                style={{
                  padding: '12px 16px',
                  borderRadius: '8px',
                  background: 'rgba(15, 10, 25, 0.6)',
                  border: '1px solid rgba(139, 92, 246, 0.3)',
                  color: '#fff',
                  fontSize: '15px',
                  outline: 'none'
                }}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ color: '#d8b4fe', fontSize: '13px', fontWeight: '500' }}>Password</label>
              <input 
                type="password" 
                value={studentPassword}
                onChange={e => setStudentPassword(e.target.value)}
                placeholder="Enter password"
                required
                style={{
                  padding: '12px 16px',
                  borderRadius: '8px',
                  background: 'rgba(15, 10, 25, 0.6)',
                  border: '1px solid rgba(139, 92, 246, 0.3)',
                  color: '#fff',
                  fontSize: '15px',
                  outline: 'none'
                }}
              />
            </div>

            {loginError && (
              <div style={{
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#f87171',
                padding: '10px 12px',
                borderRadius: '6px',
                fontSize: '13px'
              }}>
                ⚠️ {loginError}
              </div>
            )}

            <button type="submit" disabled={isLoggingIn} style={{
              padding: '14px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #7c3aed, #4f46e5)',
              color: '#fff',
              border: 'none',
              fontWeight: 'bold',
              fontSize: '16px',
              cursor: 'pointer',
              marginTop: '8px'
            }}>
              {isLoggingIn ? 'Establishing connection...' : 'Establish Session'}
            </button>
          </form>

          <div style={{ textAlign: 'center', fontSize: '11px', color: '#64748b' }}>
            Ensure your webcam is clear and functional for the system checks.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ fontFamily: 'Segoe UI, Tahoma, Geneva, Verdana, sans-serif', backgroundColor: '#f4f6f8', minHeight: '100vh', display: 'flex', overflow: 'hidden' }}>
      
      {/* Sidebar Navigation (Visible only before test starts) */}
      {(appState === 'HOME' || appState === 'SETUP') && (
        <div style={{ width: '250px', backgroundColor: '#0d47a1', color: 'white', display: 'flex', flexDirection: 'column', boxShadow: '2px 0 10px rgba(0,0,0,0.2)', zIndex: 10 }}>
          <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
            <h2 style={{ margin: 0, fontSize: '22px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              🛡️ Sentinel OS
            </h2>
          </div>
          <div style={{ flex: 1, padding: '20px 0' }}>
            <div 
              onClick={() => setAppState('HOME')}
              style={{ padding: '15px 20px', cursor: 'pointer', backgroundColor: appState === 'HOME' ? 'rgba(255,255,255,0.15)' : 'transparent', borderLeft: appState === 'HOME' ? '4px solid #64b5f6' : '4px solid transparent', transition: 'all 0.2s', display: 'flex', alignItems: 'center', gap: '12px', fontSize: '16px' }}
            >
              <span>🌐</span> Web Browser
            </div>
            <div 
              onClick={() => setAppState('SETUP')}
              style={{ padding: '15px 20px', cursor: 'pointer', backgroundColor: appState === 'SETUP' ? 'rgba(255,255,255,0.15)' : 'transparent', borderLeft: appState === 'SETUP' ? '4px solid #64b5f6' : '4px solid transparent', transition: 'all 0.2s', display: 'flex', alignItems: 'center', gap: '12px', fontSize: '16px' }}
            >
              <span>📝</span> Take a Test
            </div>
          </div>
          <div style={{ padding: '20px', fontSize: '12px', color: 'rgba(255,255,255,0.5)', textAlign: 'center' }}>
            Sentinel Secure Environment v1.0
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative' }}>
        
        {/* Global Header */}
        <header style={{ backgroundColor: '#1a237e', color: 'white', padding: '15px 30px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 2px 4px rgba(0,0,0,0.1)', zIndex: 5 }}>
        <h2 style={{ margin: 0, fontSize: '20px' }}>Sentinel Secure Exam Browser</h2>
        <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
          {appState === 'EXAM' && (
            <>
              <span style={{ fontSize: '14px', backgroundColor: 'rgba(255,255,255,0.2)', padding: '4px 10px', borderRadius: '4px' }}>
                Student: <strong>{studentId}</strong>
              </span>
              <span style={{ fontSize: '18px', fontWeight: 'bold', color: timeLeft < 300 ? '#ff5252' : 'white' }}>
                ⏱ {formatTime(timeLeft)}
              </span>
            </>
          )}
          <button 
            onClick={openWifiModal}
            style={{ backgroundColor: 'transparent', border: '1px solid rgba(255,255,255,0.5)', color: 'white', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer' }}
          >
            📶 WiFi
          </button>
          <button 
            onClick={closeApplication}
            style={{ backgroundColor: '#d32f2f', border: 'none', color: 'white', padding: '6px 16px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}
          >
            ✕ Close
          </button>
        </div>
      </header>

        {/* Main Body */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'center', padding: appState === 'HOME' ? '0' : '20px', overflow: 'hidden' }}>

          {/* HOME SCREEN / BROWSER */}
          {appState === 'HOME' && (
            <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: 'white', position: 'relative' }}>
              {browserStatus === 'idle' ? (
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: '#fff' }}>
                  <div style={{ fontSize: '80px', fontWeight: 'bold', letterSpacing: '-3px', marginBottom: '30px' }}>
                    <span style={{ color: '#4285F4' }}>G</span>
                    <span style={{ color: '#EA4335' }}>o</span>
                    <span style={{ color: '#FBBC05' }}>o</span>
                    <span style={{ color: '#4285F4' }}>g</span>
                    <span style={{ color: '#34A853' }}>l</span>
                    <span style={{ color: '#EA4335' }}>e</span>
                  </div>
                  <form 
                    onSubmit={(e) => {
                      e.preventDefault();
                      let query = urlInput.trim();
                      if (!query) return;
                      
                      let targetUrl = '';
                      if (query.startsWith('http://') || query.startsWith('https://')) {
                        targetUrl = query;
                      } else if (query.includes('.') && !query.includes(' ')) {
                        targetUrl = 'https://' + query;
                      } else {
                        targetUrl = 'https://www.google.com/search?q=' + encodeURIComponent(query);
                      }
                      
                      setBrowserStatus('opened');
                      fetch('http://127.0.0.1:8000/api/v1/browser/open', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ url: targetUrl }),
                      }).catch(err => console.error('Error opening browser:', err));
                    }}
                    style={{ width: '100%', maxWidth: '600px', position: 'relative' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', border: '1px solid #dfe1e5', borderRadius: '24px', padding: '10px 20px', boxShadow: '0 1px 6px rgba(32,33,36,.28)', transition: 'box-shadow 0.2s', backgroundColor: 'white' }}>
                      <span style={{ color: '#9aa0a6', marginRight: '10px', fontSize: '18px' }}>🔍</span>
                      <input 
                        type="text" 
                        value={urlInput} 
                        onChange={e => setUrlInput(e.target.value)} 
                        placeholder="Search Google or type a URL"
                        style={{ flex: 1, border: 'none', outline: 'none', fontSize: '16px', backgroundColor: 'transparent' }} 
                      />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'center', gap: '15px', marginTop: '25px' }}>
                      <button type="submit" style={{ padding: '10px 20px', backgroundColor: '#f8f9fa', border: '1px solid #f8f9fa', borderRadius: '4px', color: '#3c4043', cursor: 'pointer', fontSize: '14px' }}>Google Search</button>
                      <button 
                        type="button" 
                        onClick={() => {
                          setBrowserStatus('opened');
                          setUrlInput('https://www.google.com');
                          fetch('http://127.0.0.1:8000/api/v1/browser/open', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ url: 'https://www.google.com' }),
                          }).catch(err => console.error('Error opening browser:', err));
                        }} 
                        style={{ padding: '10px 20px', backgroundColor: '#f8f9fa', border: '1px solid #f8f9fa', borderRadius: '4px', color: '#3c4043', cursor: 'pointer', fontSize: '14px' }}
                      >
                        I'm Feeling Lucky
                      </button>
                    </div>
                  </form>
                </div>
              ) : (
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', backgroundColor: '#fff', padding: '20px' }}>
                  <div style={{ fontSize: '60px', marginBottom: '20px' }}>🌐</div>
                  <h3 style={{ margin: '0 0 10px 0', color: '#333' }}>Secure Browser Opened</h3>
                  <p style={{ color: '#666', textAlign: 'center', maxWidth: '450px', margin: '0 0 20px 0', fontSize: '15px', lineHeight: '1.6' }}>
                    We have launched Microsoft Edge in secure application mode. This opens a separate fullscreen window to load any webpage securely without iframe restrictions.
                  </p>
                  <div style={{ fontSize: '14px', backgroundColor: '#f1f3f4', padding: '10px 20px', borderRadius: '20px', border: '1px solid #dfe1e5', marginBottom: '30px', color: '#3c4043', fontFamily: 'monospace' }}>
                    {urlInput.startsWith('http') ? urlInput : `https://www.google.com/search?q=${urlInput}`}
                  </div>
                  <button 
                    onClick={() => {
                      setBrowserStatus('idle');
                      setUrlInput('');
                    }}
                    style={{ padding: '12px 30px', backgroundColor: '#0d47a1', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold', fontSize: '15px', boxShadow: '0 2px 5px rgba(0,0,0,0.2)', transition: 'background-color 0.2s' }}
                  >
                    ← Close Browser and Go Back
                  </button>
                </div>
              )}
            </div>
          )}

          {/* SETUP SCREEN */}
          {appState === 'SETUP' && (
            <div style={{ backgroundColor: 'white', padding: '40px', borderRadius: '12px', boxShadow: '0 4px 20px rgba(0,0,0,0.15)', maxWidth: '480px', width: '100%', alignSelf: 'center', margin: 'auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ textAlign: 'center' }}>
                <h2 style={{ marginTop: 0, color: '#1e1b4b', marginBottom: '4px' }}>Confirm Identity & Select Exam</h2>
                <p style={{ color: '#64748b', fontSize: '14px', margin: 0 }}>Verify your profile details retrieved from registry.</p>
              </div>

              {/* Profile card summary */}
              <div style={{ display: 'flex', gap: '16px', padding: '16px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0', alignItems: 'center' }}>
                <div style={{ width: '80px', height: '80px', borderRadius: '50%', overflow: 'hidden', background: '#e2e8f0', border: '2px solid #818cf8', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {referenceImage && referenceImage !== 'mock_url' ? (
                    <img src={referenceImage} alt="Profile" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <div style={{ fontSize: '32px' }}>👤</div>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '18px', fontWeight: 'bold', color: '#1e1b4b' }}>{studentName}</span>
                  <span style={{ fontSize: '13px', color: '#64748b' }}>Roll No: <code style={{ fontWeight: 'bold' }}>{studentId}</code></span>
                  <span style={{ fontSize: '13px', color: '#64748b' }}>{semester}</span>
                </div>
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '6px', fontWeight: 'bold', fontSize: '14px', color: '#334155' }}>Select Exam</label>
                <select
                  value={examId}
                  onChange={e => {
                    setExamId(e.target.value);
                    const selected = availableExams.find(ex => ex.id === e.target.value);
                    if (selected) setTimeLeft(selected.duration * 60);
                  }}
                  style={{ padding: '12px', fontSize: '16px', width: '100%', boxSizing: 'border-box', border: '1px solid #cbd5e1', borderRadius: '6px', cursor: 'pointer', backgroundColor: 'white' }}
                >
                  {availableExams.length === 0 ? (
                    <option value="" disabled>Loading exams from server...</option>
                  ) : (
                    availableExams.map(ex => (
                      <option key={ex.id} value={ex.id}>{ex.title} ({ex.duration} mins)</option>
                    ))
                  )}
                </select>
              </div>

              <div style={{ backgroundColor: '#e0e7ff', padding: '12px', borderRadius: '6px', fontSize: '13px', color: '#3730a3', border: '1px solid #c7d2fe' }}>
                Secure Proctor Session ID: <strong>{examId || 'Initializing...'}</strong>
              </div>
              
              <button
                onClick={startPreTest}
                disabled={!examId || !referenceImage || registeringFace}
                style={{ 
                  width: '100%', padding: '14px', fontSize: '16px', fontWeight: 'bold', 
                  backgroundColor: (!examId || !referenceImage || registeringFace) ? '#cbd5e1' : '#4f46e5', color: 'white', 
                  border: 'none', borderRadius: '8px', cursor: (!examId || !referenceImage || registeringFace) ? 'not-allowed' : 'pointer',
                  transition: 'background-color 0.2s',
                  boxShadow: '0 4px 6px -1px rgba(79, 70, 229, 0.2)'
                }}
              >
                {registeringFace ? 'Configuring Session...' : 'Proceed to System Check →'}
              </button>
            </div>
          )}

        {/* PRE-TEST SCREEN */}
        {appState === 'PRE_TEST' && (
          <div style={{ display: 'flex', gap: '30px', maxWidth: '1000px', width: '100%' }}>
            
            {/* Camera Feed */}
            <div style={{ flex: 1, backgroundColor: 'white', padding: '20px', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
              <h3 style={{ marginTop: 0, color: '#333' }}>Camera Positioning</h3>
              <video 
                ref={videoRef} 
                autoPlay 
                playsInline 
                style={{ width: '100%', borderRadius: '4px', border: '1px solid #ddd', transform: 'scaleX(-1)' }} 
              />
              <canvas ref={canvasRef} style={{ display: 'none' }} />
            </div>

            {/* Checklist */}
            <div style={{ width: '350px', backgroundColor: 'white', padding: '20px', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', display: 'flex', flexDirection: 'column' }}>
              <h3 style={{ marginTop: 0, color: '#333' }}>System Check</h3>
              <p style={{ color: '#666', fontSize: '14px', marginBottom: '20px' }}>Adjust your environment until all checks pass.</p>
              
              <div style={{ flex: 1 }}>
                {preTestChecks.calibrating ? (
                  <div style={{ padding: '20px', backgroundColor: '#fff3e0', color: '#e65100', borderRadius: '4px', textAlign: 'center', fontWeight: 'bold' }}>
                    Calibrating Gaze...<br/><span style={{fontSize: '12px', fontWeight: 'normal'}}>Please look directly at the center of the screen.</span>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <CheckItem label="Face Detected & Clear" passed={preTestChecks.faceDetected} />
                    <CheckItem label="Identity Verified (Face Matches Registry)" passed={preTestChecks.identityVerified} />
                    <CheckItem label="Clear Environment" passed={preTestChecks.plainBackground} />
                    <CheckItem label="Real Person (Liveness Passed)" passed={preTestChecks.livenessPassed} />
                    <CheckItem label="Looking at Screen" passed={preTestChecks.gazeCentered} />
                    <CheckItem label="No Phone in Frame" passed={preTestChecks.noPhoneDetected} />
                  </div>
                )}
              </div>

              <button 
                onClick={startExam} 
                disabled={!isPreTestReady}
                style={{ 
                  marginTop: '20px', padding: '14px', fontSize: '16px', fontWeight: 'bold', 
                  backgroundColor: !isPreTestReady ? '#ccc' : '#4caf50', color: 'white', 
                  border: 'none', borderRadius: '4px', cursor: !isPreTestReady ? 'not-allowed' : 'pointer',
                }}
              >
                {isPreTestReady ? 'Start Official Exam' : 'Waiting for checks...'}
              </button>
            </div>
          </div>
        )}

        {/* EXAM SCREEN */}
        {appState === 'EXAM' && (
          <div style={{ display: 'flex', gap: '20px', width: '100%', maxWidth: '1200px' }}>
            
            {/* Left side: The Exam Content */}
            <div style={{ flex: 1, backgroundColor: 'white', padding: '30px', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', display: 'flex', flexDirection: 'column' }}>
              {(() => {
                const selectedExam = availableExams.find(ex => ex.id === examId);
                const questions = selectedExam?.questions || [];
                const currentQuestion = questions[currentQuestionIdx];

                return (
                  <>
                    <div style={{ borderBottom: '1px solid #eee', paddingBottom: '15px', marginBottom: '20px' }}>
                      <h1 style={{ margin: 0, color: '#333', fontSize: '24px' }}>{selectedExam?.title || 'Loading Exam...'}</h1>
                      <p style={{ margin: '5px 0 0 0', color: '#777' }}>Question {currentQuestionIdx + 1} of {questions.length}</p>
                    </div>

                    <div style={{ flex: 1 }}>
                      {currentQuestion ? (
                        <div style={{ marginBottom: '30px' }}>
                          <h3 style={{ color: '#444' }}>Question {currentQuestionIdx + 1}</h3>
                          <p style={{ fontSize: '16px', lineHeight: '1.5', color: '#222' }}>
                            {currentQuestion.text}
                          </p>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '15px' }}>
                            {currentQuestion.options.map((opt: string, i: number) => (
                              <label key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', border: '1px solid #ddd', borderRadius: '4px', cursor: 'pointer', backgroundColor: answers[currentQuestion.id] === opt ? '#e3f2fd' : 'white' }}>
                                <input 
                                  type="radio" 
                                  name={`q_${currentQuestion.id}`} 
                                  value={opt} 
                                  checked={answers[currentQuestion.id] === opt}
                                  onChange={() => setAnswers({...answers, [currentQuestion.id]: opt})}
                                />
                                <span>{opt}</span>
                              </label>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <p>No questions found for this exam.</p>
                      )}
                    </div>

                    {/* Exam Controls */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #eee', paddingTop: '20px' }}>
                      <button 
                        onClick={() => setCurrentQuestionIdx(Math.max(0, currentQuestionIdx - 1))}
                        disabled={currentQuestionIdx === 0}
                        style={{ padding: '10px 20px', backgroundColor: currentQuestionIdx === 0 ? '#f5f5f5' : '#e0e0e0', color: currentQuestionIdx === 0 ? '#aaa' : 'black', border: 'none', borderRadius: '4px', cursor: currentQuestionIdx === 0 ? 'not-allowed' : 'pointer' }}
                      >
                        ← Previous
                      </button>
                      
                      {currentQuestionIdx === questions.length - 1 ? (
                        <button onClick={submitExam} style={{ padding: '10px 30px', backgroundColor: '#4caf50', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}>Submit Exam</button>
                      ) : (
                        <button onClick={submitExam} style={{ padding: '10px 30px', backgroundColor: '#f44336', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}>Early Submit</button>
                      )}

                      <button 
                        onClick={() => setCurrentQuestionIdx(Math.min(questions.length - 1, currentQuestionIdx + 1))}
                        disabled={currentQuestionIdx === questions.length - 1}
                        style={{ padding: '10px 20px', backgroundColor: currentQuestionIdx === questions.length - 1 ? '#bbdefb' : '#2196f3', color: 'white', border: 'none', borderRadius: '4px', cursor: currentQuestionIdx === questions.length - 1 ? 'not-allowed' : 'pointer' }}
                      >
                        Next →
                      </button>
                    </div>
                  </>
                );
              })()}
            </div>

            {/* Right side: Proctoring Sidebar */}
            <div style={{ width: '320px', display: 'flex', flexDirection: 'column', gap: '15px' }}>
              
              {/* Camera Mini-view */}
              <div style={{ backgroundColor: 'white', padding: '10px', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
                <div style={{ fontSize: '12px', fontWeight: 'bold', color: '#666', marginBottom: '8px', textTransform: 'uppercase' }}>Live Monitoring</div>
                <video 
                  ref={videoRef} 
                  autoPlay 
                  playsInline 
                  style={{ width: '100%', borderRadius: '4px', backgroundColor: '#000', transform: 'scaleX(-1)' }} 
                />
                <canvas ref={canvasRef} style={{ display: 'none' }} />
              </div>

              {/* Risk Panel */}
              <div style={{ backgroundColor: 'white', padding: '15px', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
                {(() => {
                  const risk = getRiskInfo(cumulativeRisk, violations);
                  const barWidth = Math.min(100, cumulativeRisk);
                  return (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                        <span style={{ fontSize: '14px', fontWeight: 'bold', color: '#555' }}>RISK LEVEL</span>
                        <span style={{ color: risk.color, fontWeight: 'bold', fontSize: '16px', letterSpacing: '0.5px', padding: '2px 8px', backgroundColor: `${risk.barColor}20`, borderRadius: '4px' }}>
                          {risk.label}
                        </span>
                      </div>
                      <div style={{ width: '100%', background: '#e0e0e0', borderRadius: '6px', overflow: 'hidden', height: '8px' }}>
                        <div style={{ width: `${barWidth}%`, height: '100%', background: risk.barColor, transition: 'width 0.5s ease, background 0.5s ease' }} />
                      </div>
                    </>
                  );
                })()}
              </div>

              {/* Violation Log */}
              <div style={{ flex: 1, backgroundColor: 'white', padding: '15px', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', display: 'flex', flexDirection: 'column' }}>
                <div style={{ fontSize: '12px', fontWeight: 'bold', color: '#666', marginBottom: '10px', textTransform: 'uppercase' }}>Activity Log</div>
                <div style={{ flex: 1, overflowY: 'auto', maxHeight: '300px' }}>
                  {violations.length === 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100px', color: '#888' }}>
                      <span style={{ fontSize: '24px', marginBottom: '5px' }}>✓</span>
                      <span style={{ fontSize: '13px' }}>No violations recorded</span>
                    </div>
                  ) : (
                    violations.map((v, idx) => (
                      <div key={idx} style={{ borderLeft: '3px solid #f44336', paddingLeft: '10px', marginBottom: '12px', fontSize: '13px' }}>
                        <div style={{ color: '#999', fontSize: '11px', marginBottom: '2px' }}>{v.time}</div>
                        <div style={{ color: '#333', fontWeight: '500' }}>Something unusual detected</div>
                        {v.cid && (
                          <div style={{ color: '#2196f3', fontSize: '10px', marginTop: '4px', wordBreak: 'break-all' }}>
                            📸 Snapshot saved
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        </div>
      </div>
    </div>
  );
}

export default App;
