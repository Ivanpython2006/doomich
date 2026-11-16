import { Navigate, type RouteObject } from 'react-router'

import { ProtectedLayout } from './components/AppLayout'
import { LoginPage } from './pages/LoginPage'

/** Страницы загружаются по требованию: первая загрузка панели быстрее. */
export const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <ProtectedLayout />,
    children: [
      { index: true, lazy: () => import('./pages/DashboardPage').then((m) => ({ Component: m.DashboardPage })) },
      { path: 'university', lazy: () => import('./pages/UniversityPage').then((m) => ({ Component: m.UniversityPage })) },
      { path: 'campuses', lazy: () => import('./pages/CampusesPage').then((m) => ({ Component: m.CampusesPage })) },
      { path: 'groups', lazy: () => import('./pages/GroupsPage').then((m) => ({ Component: m.GroupsPage })) },
      { path: 'invites', lazy: () => import('./pages/InvitesPage').then((m) => ({ Component: m.InvitesPage })) },
      { path: 'schedule', lazy: () => import('./pages/SchedulePage').then((m) => ({ Component: m.SchedulePage })) },
      { path: 'kb', lazy: () => import('./pages/KnowledgePage').then((m) => ({ Component: m.KnowledgePage })) },
      { path: 'models', lazy: () => import('./pages/ModelsPage').then((m) => ({ Component: m.ModelsPage })) },
      { path: 'admins', lazy: () => import('./pages/AdminsPage').then((m) => ({ Component: m.AdminsPage })) },
      { path: 'audit', lazy: () => import('./pages/AuditPage').then((m) => ({ Component: m.AuditPage })) },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]
