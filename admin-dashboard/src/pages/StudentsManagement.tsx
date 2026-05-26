import React, { useState, useEffect } from 'react';
import { UserPlus, UploadCloud, Eye, EyeOff, FileUser, Image as ImageIcon, Loader2 } from 'lucide-react';
import { supabase } from '../supabase';
import './StudentsManagement.css';

interface Student {
  student_id: string;
  student_name: string;
  semester: string;
  photo_url?: string;
  password?: string;
  created_at?: string;
}

export default function StudentsManagement() {
  const [studentId, setStudentId] = useState('');
  const [studentName, setStudentName] = useState('');
  const [semester, setSemester] = useState('Semester 1');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [imageBytesBase64, setImageBytesBase64] = useState<string | null>(null);
  
  const [isRegistering, setIsRegistering] = useState(false);
  const [studentsList, setStudentsList] = useState<Student[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error', text: string } | null>(null);
  const [editingStudentId, setEditingStudentId] = useState<string | null>(null);
  const [cacheBuster, setCacheBuster] = useState(Date.now());

  useEffect(() => {
    fetchStudents();
  }, []);

  const fetchStudents = async () => {
    setIsLoadingList(true);
    try {
      const { data, error } = await supabase
        .from('students')
        .select('student_id, student_name, semester, photo_url, password')
        .order('student_id');
      if (error) throw error;
      setStudentsList(data || []);
      setCacheBuster(Date.now()); // Update cache buster on successful fetch to refresh CDN caches
    } catch (err: any) {
      console.error('Error fetching students:', err);
    } finally {
      setIsLoadingList(false);
    }
  };

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = reader.result as string;
        setImagePreview(result);
        setImageBytesBase64(result);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleEdit = (student: Student) => {
    setEditingStudentId(student.student_id);
    setStudentId(student.student_id);
    setStudentName(student.student_name);
    setSemester(student.semester);
    setPassword(student.password || '');
    setImagePreview(student.photo_url || null);
    setImageBytesBase64(student.photo_url || null);
    setStatusMsg(null);
  };

  const handleCancelEdit = () => {
    setEditingStudentId(null);
    setStudentId('');
    setStudentName('');
    setSemester('Semester 1');
    setPassword('');
    setImagePreview(null);
    setImageBytesBase64(null);
    setStatusMsg(null);
  };

  const handleDeleteStudent = async (studentIdToDelete: string) => {
    if (window.confirm(`Are you sure you want to delete student ${studentIdToDelete}? This will delete their verified photo and all their exam session records.`)) {
      setIsLoadingList(true);
      try {
        // 1. Delete associated sessions to satisfy FK constraints
        const { error: sessionError } = await supabase
          .from('sessions')
          .delete()
          .eq('student_id', studentIdToDelete);
          
        if (sessionError) {
          console.warn("Could not delete associated sessions:", sessionError.message);
        }

        // 2. Delete reference photo from storage
        const { data: storageData, error: storageError } = await supabase.storage
          .from('student-photos')
          .remove([`${studentIdToDelete}.jpg`]);
          
        if (storageError) {
          console.warn("Storage deletion failed:", storageError.message);
          alert(`Warning: Failed to delete image from Supabase Storage (${storageError.message}).\n\nPlease ensure your bucket policy allows the "DELETE" operation for the public/anon role. Deleting database records will proceed.`);
        } else if (!storageData || storageData.length === 0) {
          console.warn("No files deleted from storage. RLS policies might be blocking it.");
          alert(`Warning: No files were deleted from Supabase Storage. This usually means the file was not found, or your Row-Level Security (RLS) policies are silently blocking the "DELETE" action for public/anon users.\n\nPlease check your Supabase Storage policies. Deleting database records will proceed.`);
        }

        // 3. Delete student row from database
        const { error: dbError } = await supabase
          .from('students')
          .delete()
          .eq('student_id', studentIdToDelete);

        if (dbError) throw dbError;

        setStatusMsg({ type: 'success', text: `Student ${studentIdToDelete} deleted successfully.` });
        
        if (editingStudentId === studentIdToDelete) {
          handleCancelEdit();
        }
        
        fetchStudents();
      } catch (err: any) {
        console.error(err);
        setStatusMsg({ type: 'error', text: `Failed to delete student: ${err.message}` });
      } finally {
        setIsLoadingList(false);
      }
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!studentId || !studentName || !semester) {
      setStatusMsg({ type: 'error', text: 'Roll number, Name, and Semester are required.' });
      return;
    }

    // For new registrations, password and photo are mandatory
    if (!editingStudentId && (!password || !imageBytesBase64)) {
      setStatusMsg({ type: 'error', text: 'All fields including the password and student photo are required for registration.' });
      return;
    }

    setIsRegistering(true);
    setStatusMsg(null);

    try {
      let photoUrl = '';

      // If a new image was selected (base64 data URL)
      if (imageBytesBase64 && imageBytesBase64.startsWith('data:image/')) {
        // 1. Convert base64 image string to binary Blob/File for Supabase Storage
        const resBlob = await fetch(imageBytesBase64);
        const blob = await resBlob.blob();
        const file = new File([blob], `${studentId}.jpg`, { type: 'image/jpeg' });

        // 2. Upload photo to Supabase storage 'student-photos' bucket with 0 cache control
        const { error: uploadError } = await supabase.storage
          .from('student-photos')
          .upload(`${studentId}.jpg`, file, {
            upsert: true,
            cacheControl: '0'
          });

        if (uploadError) throw uploadError;

        // 3. Get public URL of the uploaded photo
        const { data: urlData } = supabase.storage
          .from('student-photos')
          .getPublicUrl(`${studentId}.jpg`);

        photoUrl = urlData.publicUrl;
      } else {
        // Re-use current photo URL if editing
        if (editingStudentId) {
          const original = studentsList.find(s => s.student_id === editingStudentId);
          photoUrl = original?.photo_url || '';
        }
      }

      if (editingStudentId) {
        // 4. Update student details directly in Supabase 'students' table
        const updateData: any = {
          student_name: studentName,
          semester: semester,
          embedding: null // Force re-generation of embedding on local device upon next login
        };

        if (password) {
          updateData.password = password;
        }

        if (photoUrl) {
          updateData.photo_url = photoUrl;
        }

        const { error: dbError } = await supabase
          .from('students')
          .update(updateData)
          .eq('student_id', editingStudentId);

        if (dbError) throw dbError;

        setStatusMsg({ type: 'success', text: `Student ${studentName} successfully updated!` });
      } else {
        // 4. Insert new student details directly into Supabase 'students' table
        const { error: dbError } = await supabase
          .from('students')
          .insert({
            student_id: studentId,
            student_name: studentName,
            semester: semester,
            password: password,
            photo_url: photoUrl,
            embedding: null // Local device will compute face vector on-the-fly
          });

        if (dbError) throw dbError;

        setStatusMsg({ type: 'success', text: `Student ${studentName} successfully registered!` });
      }

      // Reset form fields
      setStudentId('');
      setStudentName('');
      setPassword('');
      setImagePreview(null);
      setImageBytesBase64(null);
      setEditingStudentId(null);
      // Refresh list
      fetchStudents();
    } catch (err: any) {
      console.error(err);
      setStatusMsg({ type: 'error', text: `Operation failed: ${err.message || 'Unknown error'}` });
    } finally {
      setIsRegistering(false);
    }
  };

  return (
    <div className="students-management">
      <header className="page-header">
        <div>
          <h1>Student Directory</h1>
          <p>Manage registered students, update passwords, reference photos, and configure biometric profiles.</p>
        </div>
      </header>

      <div className="students-grid">
        {/* Registration/Edit Form Card */}
        <div className="glass-panel form-panel">
          <div className="glass-header">
            <h2>
              <UserPlus size={20} className="header-icon" /> 
              {editingStudentId ? 'Edit Student Details' : 'New Student Registration'}
            </h2>
          </div>
          
          <form onSubmit={handleRegister} className="registration-form">
            <div className="form-group">
              <label>Roll Number / Student ID</label>
              <input 
                type="text" 
                value={studentId} 
                onChange={e => setStudentId(e.target.value)} 
                placeholder="e.g. 2026CS45" 
                required 
                disabled={!!editingStudentId}
                style={editingStudentId ? { opacity: 0.6, cursor: 'not-allowed' } : {}}
              />
            </div>

            <div className="form-group">
              <label>Full Name</label>
              <input 
                type="text" 
                value={studentName} 
                onChange={e => setStudentName(e.target.value)} 
                placeholder="e.g. Saksham Sharma" 
                required 
              />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>Semester</label>
                <select value={semester} onChange={e => setSemester(e.target.value)}>
                  {Array.from({ length: 8 }).map((_, i) => (
                    <option key={i} value={`Semester ${i + 1}`}>Semester {i + 1}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>{editingStudentId ? 'Password (Optional/To Change)' : 'Password'}</label>
                <div className="password-input-wrapper">
                  <input 
                    type={showPassword ? 'text' : 'password'} 
                    value={password} 
                    onChange={e => setPassword(e.target.value)} 
                    placeholder={editingStudentId ? "Enter new passcode" : "Create passcode"} 
                    required={!editingStudentId} 
                  />
                  <button 
                    type="button" 
                    className="toggle-password-btn" 
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>

            {/* Photo upload component */}
            <div className="form-group">
              <label>Verified Identification Photo {editingStudentId && '(Optional to replace)'}</label>
              <div className="image-upload-zone">
                <input 
                  type="file" 
                  id="student-image-input" 
                  accept="image/*" 
                  onChange={handleImageChange} 
                  style={{ display: 'none' }}
                />
                
                {imagePreview ? (
                  <div className="image-preview-container">
                    <img 
                      src={imagePreview.startsWith('data:image/') ? imagePreview : `${imagePreview}?t=${cacheBuster}`} 
                      alt="Reference Preview" 
                      className="uploaded-preview" 
                    />
                    <button 
                      type="button" 
                      className="change-image-btn" 
                      onClick={() => document.getElementById('student-image-input')?.click()}
                    >
                      Change Image
                    </button>
                  </div>
                ) : (
                  <label htmlFor="student-image-input" className="upload-placeholder">
                    <UploadCloud size={36} className="upload-icon" />
                    <span>Click or Drag photo here to upload</span>
                    <span className="file-desc">Clear passport size face photo (JPEG/PNG)</span>
                  </label>
                )}
              </div>
            </div>

            {statusMsg && (
              <div className={`status-banner ${statusMsg.type}`}>
                {statusMsg.text}
              </div>
            )}

            <div className="form-actions-row" style={{ display: 'flex', gap: '1rem', marginTop: '0.5rem' }}>
              <button type="submit" className="primary-btn" disabled={isRegistering} style={{ flex: 1, marginTop: 0 }}>
                {isRegistering ? (
                  <>
                    <Loader2 className="spinner" size={18} />
                    <span>Saving...</span>
                  </>
                ) : (
                  <span>{editingStudentId ? 'Update Profile' : 'Register Student'}</span>
                )}
              </button>
              
              {editingStudentId && (
                <button type="button" className="cancel-btn" onClick={handleCancelEdit} style={{ flex: 1, marginTop: 0 }}>
                  Cancel
                </button>
              )}
            </div>
          </form>
        </div>

        {/* Registered Students List */}
        <div className="glass-panel list-panel">
          <div className="glass-header list-header">
            <h2><FileUser size={20} className="header-icon" /> Registered Students</h2>
            <span className="badge">{studentsList.length} Students</span>
          </div>

          <div className="students-list-container">
            {isLoadingList ? (
              <div className="list-loading">
                <Loader2 className="spinner" size={24} />
                <span>Fetching directory...</span>
              </div>
            ) : studentsList.length === 0 ? (
              <div className="empty-students">
                <ImageIcon size={48} className="empty-icon" />
                <p>No registered students found.</p>
                <span>Register a student using the form to populate this list.</span>
              </div>
            ) : (
              <div className="students-table-wrapper">
                <table className="students-table">
                  <thead>
                    <tr>
                      <th>Avatar</th>
                      <th>Roll Number</th>
                      <th>Name</th>
                      <th>Semester</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {studentsList.map((student) => (
                      <tr key={student.student_id}>
                        <td>
                          <div className="student-avatar-frame">
                            {student.photo_url ? (
                              <img src={`${student.photo_url}?t=${cacheBuster}`} alt={student.student_name} className="avatar-img" />
                            ) : (
                              <div className="avatar-letter">{student.student_name[0]}</div>
                            )}
                          </div>
                        </td>
                        <td><code className="roll-badge">{student.student_id}</code></td>
                        <td><strong>{student.student_name}</strong></td>
                        <td><span className="semester-tag">{student.semester}</span></td>
                        <td>
                          <div className="action-buttons">
                            <button 
                              type="button" 
                              className="edit-btn" 
                              onClick={() => handleEdit(student)}
                            >
                              ✏️ Edit
                            </button>
                            <button 
                              type="button" 
                              className="delete-btn" 
                              onClick={() => handleDeleteStudent(student.student_id)}
                            >
                              🗑️ Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
