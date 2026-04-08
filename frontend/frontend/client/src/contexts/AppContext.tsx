import React, { createContext, useContext, useReducer } from 'react';

// ─── Types ────────────────────────────────────────────────────────────────────
interface Task {
  id: string;
  title: string;
  status: string;
  budget?: number;
}

interface Project {
  id: string;
  name: string;
  tasks: Task[];
}

interface AppState {
  sidebarOpen: boolean;
  theme: string;
  rightPanelOpen: boolean;
  rightPanelWidth: number;
  activeProjectId: string | null;
  activeTaskId: string | null;
  projects: Project[];
}

type AppAction =
  | { type: 'TOGGLE_RIGHT_PANEL' }
  | { type: 'SET_RIGHT_PANEL_WIDTH'; width: number }
  | { type: 'SET_ACTIVE_PROJECT'; projectId: string | null }
  | { type: 'SET_ACTIVE_TASK'; taskId: string | null }
  | { type: 'SET_SIDEBAR_OPEN'; value: boolean }
  | { type: 'SET_THEME'; theme: string }
  | { type: 'UPDATE_TASK_BUDGET'; taskId: string; budget: number };

interface AppContextType {
  state: AppState;
  dispatch: React.Dispatch<AppAction>;
  // Legacy compat
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
  theme: string;
  setTheme: (v: string) => void;
}

// ─── Initial State ────────────────────────────────────────────────────────────
const initialState: AppState = {
  sidebarOpen: true,
  theme: 'light',
  rightPanelOpen: false,
  rightPanelWidth: 400,
  activeProjectId: null,
  activeTaskId: null,
  projects: [],
};

// ─── Reducer ──────────────────────────────────────────────────────────────────
function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'TOGGLE_RIGHT_PANEL':
      return { ...state, rightPanelOpen: !state.rightPanelOpen };
    case 'SET_RIGHT_PANEL_WIDTH':
      return { ...state, rightPanelWidth: action.width };
    case 'SET_ACTIVE_PROJECT':
      return { ...state, activeProjectId: action.projectId };
    case 'SET_ACTIVE_TASK':
      return { ...state, activeTaskId: action.taskId };
    case 'SET_SIDEBAR_OPEN':
      return { ...state, sidebarOpen: action.value };
    case 'SET_THEME':
      return { ...state, theme: action.theme };
    case 'UPDATE_TASK_BUDGET':
      return {
        ...state,
        projects: state.projects.map(p => ({
          ...p,
          tasks: p.tasks.map(t =>
            t.id === action.taskId ? { ...t, budget: action.budget } : t
          ),
        })),
      };
    default:
      return state;
  }
}

// ─── Context ──────────────────────────────────────────────────────────────────
const AppContext = createContext<AppContextType>({
  state: initialState,
  dispatch: () => {},
  sidebarOpen: true,
  setSidebarOpen: () => {},
  theme: 'light',
  setTheme: () => {},
});

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, dispatch] = useReducer(appReducer, initialState);

  return (
    <AppContext.Provider value={{
      state,
      dispatch,
      // Legacy compat
      sidebarOpen: state.sidebarOpen,
      setSidebarOpen: (v: boolean) => dispatch({ type: 'SET_SIDEBAR_OPEN', value: v }),
      theme: state.theme,
      setTheme: (v: string) => dispatch({ type: 'SET_THEME', theme: v }),
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => useContext(AppContext);
export default AppContext;
