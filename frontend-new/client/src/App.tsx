import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Switch } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { CurrentUserProvider } from "./contexts/CurrentUserContext";
import Home from "./pages/Home";

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
      {/* switchable enables useTheme() hook for dark/light toggle */}
      <ThemeProvider defaultTheme="light" switchable>
        <CurrentUserProvider>
          <TooltipProvider>
            <Toaster position="top-right" />
            <Router />
          </TooltipProvider>
        </CurrentUserProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
