import { NavLink } from 'react-router-dom';
import { LayoutDashboard, FileText, Settings, ShieldAlert, UserCheck, LogOut } from 'lucide-react';
import './Sidebar.css';

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <ShieldAlert className="logo-icon" size={32} />
        <h2>Sentinel Admin</h2>
      </div>
      
      <nav className="sidebar-nav">
        <NavLink 
          to="/control-room" 
          className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}
        >
          <LayoutDashboard size={20} />
          <span>Control Room</span>
        </NavLink>
        
        <NavLink 
          to="/exams" 
          className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}
        >
          <FileText size={20} />
          <span>Exam Management</span>
        </NavLink>

        <NavLink 
          to="/students" 
          className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}
        >
          <UserCheck size={20} />
          <span>Students Directory</span>
        </NavLink>

        <div className="nav-divider"></div>

        <a href="#" className="nav-item disabled">
          <Settings size={20} />
          <span>Settings (WIP)</span>
        </a>
      </nav>
      
      <div className="sidebar-footer">
        <div className="admin-profile">
          <div className="avatar">A</div>
          <div className="admin-info">
            <strong>System Admin</strong>
            <button 
              className="logout-button"
              onClick={() => {
                localStorage.removeItem('sentinel_admin_authenticated');
                localStorage.removeItem('sentinel_admin_username');
                window.location.href = '/login';
              }}
            >
              <LogOut size={14} />
              <span>Log Out</span>
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
}
