import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const navigate = useNavigate();

  const doLogin = async () => {
    const { access_token, refresh_token } = await api.login(email, password);
    localStorage.setItem("access_token", access_token);
    localStorage.setItem("refresh_token", refresh_token);
    navigate("/");
  };

  const submit = async () => {
    setError(null);
    setInfo(null);
    try {
      if (mode === "register") {
        await api.register(email, password);
        setInfo("Account created — signing you in…");
      }
      await doLogin();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${mode === "register" ? "Registration" : "Login"} failed`);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center">
      <div className="w-80 space-y-3 rounded-xl border border-white/10 bg-panel p-6">
        <h1 className="text-lg font-semibold mb-2">
          {mode === "login" ? "Sign in" : "Create account"}
        </h1>
        <input
          className="w-full rounded-md bg-black/30 border border-white/10 px-3 py-2 text-sm"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          type="password"
          className="w-full rounded-md bg-black/30 border border-white/10 px-3 py-2 text-sm"
          placeholder="Password (min 8 characters)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-xs text-red-400">{error}</p>}
        {info && <p className="text-xs text-emerald-400">{info}</p>}
        <button onClick={submit} className="w-full rounded-md bg-accent py-2 text-sm font-medium">
          {mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
            setInfo(null);
          }}
          className="w-full text-xs text-gray-400 hover:text-gray-200"
        >
          {mode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}
