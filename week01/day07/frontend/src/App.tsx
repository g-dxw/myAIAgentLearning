import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { AuthProvider } from './contexts/AuthContext';
import RoleGuard from './components/RoleGuard';
import LoginPage from './pages/LoginPage';
import AdminLayout from './pages/admin/AdminLayout';
import AdminDashboard from './pages/admin/AdminDashboard';
import WorkerList from './pages/admin/WorkerList';
import WorkerDetail from './pages/admin/WorkerDetail';
import PatientList from './pages/admin/PatientList';
import PatientDetail from './pages/admin/PatientDetail';
import PatientApproval from './pages/admin/PatientApproval';
import ScheduleView from './pages/admin/ScheduleView';
import RecordList from './pages/admin/RecordList';
import AbsenteeismList from './pages/admin/AbsenteeismList';
import SettingsPage from './pages/admin/SettingsPage';
import WorkerLayout from './pages/worker/WorkerLayout';
import WorkerDashboard from './pages/worker/WorkerDashboard';
import MySchedule from './pages/worker/MySchedule';
import ScheduleDetail from './pages/worker/ScheduleDetail';
import MyPatientList from './pages/worker/MyPatientList';
import SessionChat from './pages/worker/SessionChat';
import CheckinForm from './pages/worker/CheckinForm';
import MakeupCheckin from './pages/worker/MakeupCheckin';
import MyRecordList from './pages/worker/MyRecordList';
import ReminderList from './pages/worker/ReminderList';

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      <AntdApp>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/" element={<RoleGuard />} />

              {/* 机构端 */}
              <Route path="/admin" element={<AdminLayout />}>
                <Route index element={<AdminDashboard />} />
                <Route path="workers" element={<WorkerList />} />
                <Route path="workers/new" element={<WorkerDetail />} />
                <Route path="workers/:id" element={<WorkerDetail />} />
                <Route path="patients" element={<PatientList />} />
                <Route path="patients/new" element={<PatientDetail />} />
                <Route path="patients/:id" element={<PatientDetail />} />
                <Route path="patients/approvals" element={<PatientApproval />} />
                <Route path="schedules" element={<ScheduleView />} />
                <Route path="records" element={<RecordList />} />
                <Route path="absenteeism" element={<AbsenteeismList />} />
                <Route path="settings" element={<SettingsPage />} />
              </Route>

              {/* 护工端 */}
              <Route path="/worker" element={<WorkerLayout />}>
                <Route index element={<WorkerDashboard />} />
                <Route path="schedules" element={<MySchedule />} />
                <Route path="schedules/:id" element={<ScheduleDetail />} />
                <Route path="patients" element={<MyPatientList />} />
                <Route path="patients/:id/chat" element={<SessionChat />} />
                <Route path="checkin/makeup" element={<MakeupCheckin />} />
                <Route path="checkin/:id" element={<CheckinForm />} />
                <Route path="records" element={<MyRecordList />} />
                <Route path="reminders" element={<ReminderList />} />
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}
