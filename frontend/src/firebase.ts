import { initializeApp } from 'firebase/app';
import { getFirestore, doc, setDoc, updateDoc, arrayUnion, serverTimestamp, collection, getDocs, query, where } from 'firebase/firestore';

// Your Firebase project configuration
const firebaseConfig = {
  apiKey: "AIzaSyCppoRL4iRlg79aSyfyuRPfBH0dxOyCWoY",
  authDomain: "ai-proctoring-system-3c306.firebaseapp.com",
  databaseURL: "https://ai-proctoring-system-3c306-default-rtdb.firebaseio.com",
  projectId: "ai-proctoring-system-3c306",
  storageBucket: "ai-proctoring-system-3c306.firebasestorage.app",
  messagingSenderId: "400723002652",
  appId: "1:400723002652:web:8eb44deb16a7aa277e66d9",
  measurementId: "G-EV4ZW78MY1"
};

const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);

/**
 * Creates or resets a student's session document at the start of the exam.
 */
export async function initStudentSession(studentId: string, studentName: string, semester: string, examId: string) {
  const sessionRef = doc(db, 'sessions', studentId);
  await setDoc(sessionRef, {
    student_id: studentId,
    student_name: studentName,
    semester: semester,
    exam_id: examId,
    status: 'active',
    risk_score: 0,
    risk_label: 'Low',
    started_at: serverTimestamp(),
    last_updated: serverTimestamp(),
    violations: [],
  });
}

/**
 * Pushes a new violation event to the student's Firestore document.
 * This triggers a real-time update on the Admin Dashboard instantly.
 */
export async function pushViolation(
  studentId: string,
  riskScore: number,
  riskLabel: string,
  violationType: string,
  ipfsCid: string | null
) {
  const sessionRef = doc(db, 'sessions', studentId);
  const violation = {
    type: violationType,
    time: new Date().toLocaleTimeString(),
    cid: ipfsCid || null,
  };

  await updateDoc(sessionRef, {
    risk_score: riskScore,
    risk_label: riskLabel,
    last_updated: serverTimestamp(),
    violations: arrayUnion(violation),  // appends, never overwrites the array
  });
}

/**
 * Marks the student's session as terminated (phone detected).
 */
export async function markSessionTerminated(studentId: string, reason: string) {
  const sessionRef = doc(db, 'sessions', studentId);
  await updateDoc(sessionRef, {
    status: 'terminated',
    termination_reason: reason,
    last_updated: serverTimestamp(),
  });
}

/**
 * Marks the student's session as completed (exam finished normally).
 */
export async function markSessionCompleted(studentId: string) {
  const sessionRef = doc(db, 'sessions', studentId);
  await updateDoc(sessionRef, {
    status: 'completed',
    last_updated: serverTimestamp(),
  });
}

/**
 * Fetches all published exams from Firestore.
 */
export async function fetchPublishedExams() {
  const examsRef = collection(db, 'exams');
  const q = query(examsRef, where('status', '==', 'published'));
  const querySnapshot = await getDocs(q);
  
  const exams: any[] = [];
  querySnapshot.forEach((doc) => {
    exams.push({ id: doc.id, ...doc.data() });
  });
  
  return exams;
}
