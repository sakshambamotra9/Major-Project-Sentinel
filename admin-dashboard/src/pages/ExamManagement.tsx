import { useState, useEffect } from 'react';
import { supabase } from '../supabase';
import { Loader2, BookOpen, Trash2, HelpCircle } from 'lucide-react';
import './ExamManagement.css';

interface Question {
  id: string;
  text: string;
  options: string[];
  correctAnswer: string;
}

export default function ExamManagement() {
  const [examTitle, setExamTitle] = useState('');
  const [duration, setDuration] = useState('60');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<'draft' | 'published'>('draft');

  // Published exams state
  const [publishedExams, setPublishedExams] = useState<any[]>([]);
  const [isLoadingExams, setIsLoadingExams] = useState(false);

  // Draft question state
  const [qText, setQText] = useState('');
  const [opt1, setOpt1] = useState('');
  const [opt2, setOpt2] = useState('');
  const [opt3, setOpt3] = useState('');
  const [opt4, setOpt4] = useState('');
  const [correct, setCorrect] = useState('0');

  useEffect(() => {
    fetchExams();
  }, []);

  const fetchExams = async () => {
    setIsLoadingExams(true);
    try {
      const { data, error } = await supabase
        .from('exams')
        .select('*')
        .order('title');
      
      if (error) throw error;
      setPublishedExams(data || []);
    } catch (err: any) {
      console.error('Error fetching exams:', err);
    } finally {
      setIsLoadingExams(false);
    }
  };

  const addQuestion = () => {
    if (!qText || !opt1 || !opt2 || !opt3 || !opt4) {
      alert("Please fill all options.");
      return;
    }
    const optionsArray = [opt1.trim(), opt2.trim(), opt3.trim(), opt4.trim()];
    const newQ: Question = {
      id: `q_${Date.now()}`,
      text: qText.trim(),
      options: optionsArray,
      correctAnswer: optionsArray[parseInt(correct)]
    };
    setQuestions([...questions, newQ]);
    
    // reset
    setQText(''); setOpt1(''); setOpt2(''); setOpt3(''); setOpt4(''); setCorrect('0');
  };

  const removeQuestion = (id: string) => {
    setQuestions(questions.filter(q => q.id !== id));
  };

  const deleteExam = async (examId: string) => {
    if (window.confirm(`Are you sure you want to delete the exam "${examId}"? This will permanently remove it from the database along with all associated student exam sessions.`)) {
      try {
        // 1. Cascade delete student sessions for this exam
        const { error: sessionError } = await supabase
          .from('sessions')
          .delete()
          .eq('exam_id', examId);
        
        if (sessionError) {
          console.warn("Could not delete associated sessions:", sessionError.message);
        }

        // 2. Delete the exam
        const { error } = await supabase
          .from('exams')
          .delete()
          .eq('id', examId);

        if (error) throw error;

        alert('Exam deleted successfully.');
        fetchExams();
      } catch (err: any) {
        console.error('Error deleting exam:', err);
        alert(`Failed to delete exam: ${err.message}`);
      }
    }
  };

  const publishExam = async () => {
    const trimmedTitle = examTitle.trim();
    if (!trimmedTitle) {
      alert("Exam title is required.");
      return;
    }

    const parsedDuration = parseInt(duration);
    if (isNaN(parsedDuration) || parsedDuration <= 0) {
      alert("Please enter a valid duration in minutes.");
      return;
    }

    if (questions.length === 0) {
      alert("At least one question is required to publish the exam.");
      return;
    }
    
    setIsSaving(true);
    try {
      // Replace whitespace cleanly with underscores
      const examId = `EXAM_${trimmedTitle.replace(/\s+/g, '_').toUpperCase()}`;
      
      const { error } = await supabase.from('exams').upsert({
        id: examId,
        title: trimmedTitle,
        duration: parsedDuration,
        status: 'published',
        questions: questions
      }, { onConflict: 'id' });

      if (error) throw error;

      alert('Exam successfully published!');
      setExamTitle('');
      setQuestions([]);
      fetchExams(); // Refresh published exams list
      setActiveTab('published'); // Switch to published tab to see it
    } catch (e: any) {
      console.error(e);
      alert(`Failed to publish exam: ${e.message || 'Unknown error'}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="exam-management">
      <header className="page-header">
        <div>
          <h1>Exam Management</h1>
          <p>Create, publish, and manage exams for the student portal.</p>
        </div>
        <button className="primary" onClick={publishExam} disabled={isSaving}>
          {isSaving ? 'Publishing...' : 'Publish Exam'}
        </button>
      </header>

      <div className="exam-builder">
        {/* Left Side: Meta & Question Builder */}
        <div className="builder-forms">
          <div className="glass-panel form-panel">
            <h2>Exam Settings</h2>
            <div className="form-group">
              <label>Exam Title</label>
              <input 
                type="text" 
                value={examTitle} 
                onChange={e => setExamTitle(e.target.value)} 
                placeholder="e.g. Midterm Physics" 
              />
            </div>
            <div className="form-group">
              <label>Duration (Minutes)</label>
              <input 
                type="number" 
                value={duration} 
                onChange={e => setDuration(e.target.value)} 
                min="1" 
              />
            </div>
          </div>

          <div className="glass-panel form-panel">
            <h2>Add Question</h2>
            <div className="form-group">
              <label>Question Text</label>
              <textarea 
                value={qText} 
                onChange={e => setQText(e.target.value)} 
                placeholder="Type your question here..." 
                rows={3}
              ></textarea>
            </div>
            
            <div className="options-grid">
              <div className="form-group">
                <label>Option 1</label>
                <input type="text" value={opt1} onChange={e => setOpt1(e.target.value)} placeholder="First choice" />
              </div>
              <div className="form-group">
                <label>Option 2</label>
                <input type="text" value={opt2} onChange={e => setOpt2(e.target.value)} placeholder="Second choice" />
              </div>
              <div className="form-group">
                <label>Option 3</label>
                <input type="text" value={opt3} onChange={e => setOpt3(e.target.value)} placeholder="Third choice" />
              </div>
              <div className="form-group">
                <label>Option 4</label>
                <input type="text" value={opt4} onChange={e => setOpt4(e.target.value)} placeholder="Fourth choice" />
              </div>
            </div>

            <div className="form-group">
              <label>Correct Answer</label>
              <select value={correct} onChange={e => setCorrect(e.target.value)}>
                <option value="0">Option 1: {opt1 || '(Empty)'}</option>
                <option value="1">Option 2: {opt2 || '(Empty)'}</option>
                <option value="2">Option 3: {opt3 || '(Empty)'}</option>
                <option value="3">Option 4: {opt4 || '(Empty)'}</option>
              </select>
            </div>

            <button className="secondary-btn" onClick={addQuestion}>+ Add Question to Exam</button>
          </div>
        </div>

        {/* Right Side: Preview & List Panel */}
        <div className="glass-panel preview-panel">
          <div className="preview-header-tabs">
            <button 
              type="button" 
              onClick={() => setActiveTab('draft')} 
              className={`tab-btn ${activeTab === 'draft' ? 'active' : ''}`}
            >
              📝 Draft Questions ({questions.length})
            </button>
            <button 
              type="button" 
              onClick={() => setActiveTab('published')} 
              className={`tab-btn ${activeTab === 'published' ? 'active' : ''}`}
            >
              📚 Published Exams ({publishedExams.length})
            </button>
          </div>
          
          <div className="preview-body">
            {activeTab === 'draft' ? (
              questions.length === 0 ? (
                <div className="empty-state">
                  <HelpCircle size={48} style={{ color: '#4b5563', marginBottom: '10px' }} />
                  <p>No questions added to the current draft.</p>
                  <span style={{ fontSize: '13px', color: '#64748b' }}>Use the form on the left to start adding questions.</span>
                </div>
              ) : (
                questions.map((q, idx) => (
                  <div key={q.id} className="preview-question">
                    <div className="q-header">
                      <strong>Q{idx + 1}. {q.text}</strong>
                      <button className="danger icon-btn" onClick={() => removeQuestion(q.id)}>✕</button>
                    </div>
                    <ul className="q-options">
                      {q.options.map((opt, i) => (
                        <li key={i} className={q.correctAnswer === opt ? 'correct' : ''}>
                          {opt} {q.correctAnswer === opt && '✓'}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))
              )
            ) : (
              isLoadingExams ? (
                <div className="list-loading" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '200px', color: '#a78bfa' }}>
                  <Loader2 className="spinner" size={24} />
                  <span style={{ marginTop: '10px' }}>Loading exams...</span>
                </div>
              ) : publishedExams.length === 0 ? (
                <div className="empty-state">
                  <BookOpen size={48} style={{ color: '#4b5563', marginBottom: '10px' }} />
                  <p>No published exams found in database.</p>
                  <span style={{ fontSize: '13px', color: '#64748b' }}>Create and publish an exam to populate this list.</span>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {publishedExams.map((exam) => (
                    <div key={exam.id} className="preview-question" style={{ border: '1px solid rgba(139, 92, 246, 0.15)' }}>
                      <div className="q-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: 0 }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          <strong style={{ fontSize: '15px', color: '#f3e8ff' }}>{exam.title}</strong>
                          <code className="roll-badge" style={{ alignSelf: 'flex-start', fontSize: '10px' }}>{exam.id}</code>
                        </div>
                        <button 
                          onClick={() => deleteExam(exam.id)}
                          className="danger-btn"
                        >
                          <Trash2 size={13} style={{ marginRight: '4px' }} />
                          Delete
                        </button>
                      </div>
                      <div style={{ display: 'flex', gap: '15px', fontSize: '12px', color: '#94a3b8', marginTop: '12px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '10px' }}>
                        <span>🕒 Duration: <strong>{exam.duration} mins</strong></span>
                        <span>❓ Questions: <strong>{exam.questions?.length || 0}</strong></span>
                      </div>
                    </div>
                  ))}
                </div>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
