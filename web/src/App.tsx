import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./lib/auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Clients from "./pages/Clients";
import ClientPage from "./pages/ClientPage";
import Users from "./pages/Users";
import Workspace from "./pages/workspace/Workspace";
import { EmptyState, btnCls } from "./components/ui";
import { Link } from "react-router-dom";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="clients" element={<Clients />} />
        <Route path="clients/:cid" element={<ClientPage />} />
        <Route path="clients/:cid/:period" element={<Navigate to="overview" replace />} />
        <Route path="clients/:cid/:period/:tab" element={<Workspace />} />
        <Route
          path="users"
          element={
            <RequireAuth role="admin">
              <Users />
            </RequireAuth>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

function NotFound() {
  return (
    <EmptyState
      className="mt-20"
      title="This page doesn't exist"
      action={
        <Link to="/" className={btnCls("primary")}>
          Go to the dashboard
        </Link>
      }
    >
      The link may be old, or the client was deleted.
    </EmptyState>
  );
}
