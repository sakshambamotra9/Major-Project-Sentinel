import { createClient } from '@supabase/supabase-js';

// Supabase Credentials
const supabaseUrl = 'https://ssnedxdyhnczhvkdrkyg.supabase.co';
const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNzbmVkeGR5aG5jemh2a2Rya3lnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3MjA0NzAsImV4cCI6MjA5NTI5NjQ3MH0.vVXumzUQZrtGnjwf_NJl2Dtmf73U01uNb_Fxmq_uJSE';

export const supabase = createClient(supabaseUrl, supabaseKey);

/**
 * Creates or resets a student's session row at the start of the exam.
 */
export async function initStudentSession(studentId: string, studentName: string, semester: string, examId: string) {
  const { error } = await supabase.from('sessions').upsert({
    student_id: studentId,
    student_name: studentName,
    semester: semester,
    exam_id: examId,
    status: 'active',
    risk_score: 0,
    risk_label: 'Low',
    started_at: new Date().toISOString(),
    last_updated: new Date().toISOString(),
    violations: [],
  }, { onConflict: 'student_id' });

  if (error) {
    console.error('Error initializing student session in Supabase:', error);
    throw error;
  }
}

/**
 * Pushes a new violation event to the student's Supabase row.
 */
export async function pushViolation(
  studentId: string,
  riskScore: number,
  riskLabel: string,
  violationType: string,
  ipfsCid: string | null
) {
  const violation = {
    type: violationType,
    time: new Date().toLocaleTimeString(),
    cid: ipfsCid || null,
  };

  // Fetch existing violations first to append
  const { data, error: fetchError } = await supabase
    .from('sessions')
    .select('violations')
    .eq('student_id', studentId)
    .single();

  if (fetchError) {
    console.error('Error fetching session for violation push:', fetchError);
    throw fetchError;
  }

  const currentViolations = data?.violations || [];
  const updatedViolations = [...currentViolations, violation];

  const { error: updateError } = await supabase
    .from('sessions')
    .update({
      risk_score: riskScore,
      risk_label: riskLabel,
      last_updated: new Date().toISOString(),
      violations: updatedViolations,
    })
    .eq('student_id', studentId);

  if (updateError) {
    console.error('Error updating session violation in Supabase:', updateError);
    throw updateError;
  }
}

/**
 * Marks the student's session as terminated (phone detected).
 */
export async function markSessionTerminated(studentId: string, reason: string) {
  const { error } = await supabase
    .from('sessions')
    .update({
      status: 'terminated',
      termination_reason: reason,
      last_updated: new Date().toISOString(),
    })
    .eq('student_id', studentId);

  if (error) {
    console.error('Error marking session terminated in Supabase:', error);
    throw error;
  }
}

/**
 * Marks the student's session as completed (exam finished normally).
 */
export async function markSessionCompleted(studentId: string) {
  const { error } = await supabase
    .from('sessions')
    .update({
      status: 'completed',
      last_updated: new Date().toISOString(),
    })
    .eq('student_id', studentId);

  if (error) {
    console.error('Error marking session completed in Supabase:', error);
    throw error;
  }
}

/**
 * Fetches all published exams from Supabase.
 */
export async function fetchPublishedExams() {
  const { data, error } = await supabase
    .from('exams')
    .select('*')
    .eq('status', 'published');

  if (error) {
    console.error('Error fetching published exams from Supabase:', error);
    throw error;
  }

  return data || [];
}
