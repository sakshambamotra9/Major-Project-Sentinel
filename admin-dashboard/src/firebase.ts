import { initializeApp } from 'firebase/app';
import { getFirestore } from 'firebase/firestore';

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

export const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);
