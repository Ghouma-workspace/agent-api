import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { ChatPage } from "./pages/ChatPage";
import { AdminPage } from "./pages/AdminPage";
import { LoginPage } from "./pages/LoginPage";
import { RequireAuth } from "./components/layout/RequireAuth";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <ChatPage />
            </RequireAuth>
          }
        />
        <Route
          path="/admin"
          element={
            <RequireAuth>
              <div>
                <nav className="border-b border-white/10 px-6 py-2 text-xs">
                  <Link to="/" className="text-gray-400 hover:text-white">← back to chat</Link>
                </nav>
                <AdminPage />
              </div>
            </RequireAuth>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
