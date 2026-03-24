import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import LoginPage from "@/pages/LoginPage";
import { Route, Switch } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { CurrentUserProvider, useCurrentUser } from "./contexts/CurrentUserContext";
import Home from "./pages/Home";

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useCurrentUser();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F7F5F0] dark:bg-[#0f1117]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#6366f1] flex items-center justify-center animate-pulse">
            <span className="text-white font-bold text-sm">O</span>
          </div>
          <span className="text-sm text-[#6b7280] dark:text-[#9ca3af]">Загрузка...</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return <>{children}</>;
}

function Router() {
  return (
    <Switch>
      <Route path={"/"} component={Home} />
      <Route path={"/404"} component={NotFound} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider defaultTheme="light" switchable>
        <CurrentUserProvider>
          <TooltipProvider>
            <Toaster position="top-right" />
            <AuthGuard>
              <Router />
            </AuthGuard>
          </TooltipProvider>
        </CurrentUserProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
