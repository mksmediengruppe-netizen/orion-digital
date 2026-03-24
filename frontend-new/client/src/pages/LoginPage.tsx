import { useState } from "react";
import { useCurrentUser } from "@/contexts/CurrentUserContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const { login } = useCurrentUser();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Ошибка входа";
      setError(msg.includes("401") || msg.includes("credentials") || msg.includes("Invalid")
        ? "Неверный email или пароль"
        : msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F7F5F0] dark:bg-[#0f1117]">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-[#6366f1] flex items-center justify-center">
              <span className="text-white font-bold text-sm">O</span>
            </div>
            <span className="text-xl font-semibold text-[#1a1d2e] dark:text-white">ORION</span>
          </div>
          <p className="text-sm text-[#6b7280] dark:text-[#9ca3af]">AI Workspace</p>
        </div>

        {/* Card */}
        <div className="bg-white dark:bg-[#1a1d2e] rounded-2xl border border-[#E8E6E1] dark:border-[#2a2d3a] p-8 shadow-sm">
          <h1 className="text-lg font-semibold text-[#1a1d2e] dark:text-white mb-6">
            Вход в систему
          </h1>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-sm text-[#374151] dark:text-[#d1d5db]">
                Email
              </Label>
              <Input
                id="email"
                type="email"
                placeholder="admin@orion.ai"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                className="bg-[#F7F5F0] dark:bg-[#0f1117] border-[#E8E6E1] dark:border-[#2a2d3a]"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-sm text-[#374151] dark:text-[#d1d5db]">
                Пароль
              </Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="bg-[#F7F5F0] dark:bg-[#0f1117] border-[#E8E6E1] dark:border-[#2a2d3a]"
              />
            </div>

            {error && (
              <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-[#6366f1] hover:bg-[#5558e3] text-white"
            >
              {loading ? "Вход..." : "Войти"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
