// ARCANE ConnectorsPanel — Real API Integration
// Manages external service connectors via /api/connectors
import { useState, useEffect, useCallback } from "react";
import { Plug, RefreshCw, X, CheckCircle, XCircle, Loader2 } from "lucide-react";
import api, { type Connector } from "@/lib/api";

interface ConnectorsPanelProps {
  onClose?: () => void;
}

const CONNECTOR_ICONS: Record<string, string> = {
  github: "🐙",
  gitlab: "🦊",
  jira: "📋",
  slack: "💬",
  telegram: "✈️",
  notion: "📝",
  google: "🔍",
  openai: "🤖",
  anthropic: "🧠",
  bitrix: "📊",
  default: "🔌",
};

export function ConnectorsPanel({ onClose }: ConnectorsPanelProps) {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.connectors.list();
      setConnectors(res.connectors || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки коннекторов");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleToggle = async (connector: Connector) => {
    setConnecting(connector.id);
    setError(null);
    try {
      if ((connector.connected || connector.status === 'connected')) {
        await api.connectors.disconnect(connector.id);
        setConnectors(prev => prev.map(c => c.id === connector.id ? { ...c, connected: false } : c));
      } else {
        await api.connectors.connect(connector.id);
        setConnectors(prev => prev.map(c => c.id === connector.id ? { ...c, connected: true } : c));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка подключения");
    } finally {
      setConnecting(null);
    }
  };

  const connectedCount = connectors.filter(c => (c.connected || c.status === 'connected')).length;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#1C1C1E]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <Plug size={16} className="text-emerald-500" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-100">Коннекторы</span>
          <span className="text-[10px] bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded-full">
            {connectedCount}/{connectors.length} подключено
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={load} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 transition-colors">
            <RefreshCw size={13} />
          </button>
          {onClose && (
            <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 transition-colors">
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-3 mt-2 px-3 py-2 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg text-xs text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Connectors list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-xs text-gray-400">
            <RefreshCw size={14} className="animate-spin mr-2" /> Загрузка коннекторов...
          </div>
        ) : connectors.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-xs text-gray-400 gap-2">
            <Plug size={24} className="text-gray-300 dark:text-gray-600" />
            <span>Нет доступных коннекторов</span>
          </div>
        ) : (
          <>
            {/* Connected */}
            {connectors.filter(c => (c.connected || c.status === 'connected')).length > 0 && (
              <div>
                <p className="text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1 px-1">Подключено</p>
                {connectors.filter(c => (c.connected || c.status === 'connected')).map(connector => (
                  <ConnectorCard key={connector.id} connector={connector} connecting={connecting} onToggle={handleToggle} />
                ))}
              </div>
            )}
            {/* Disconnected */}
            {connectors.filter(c => !(c.connected || c.status === 'connected')).length > 0 && (
              <div>
                <p className="text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1 px-1 mt-3">Доступны</p>
                {connectors.filter(c => !(c.connected || c.status === 'connected')).map(connector => (
                  <ConnectorCard key={connector.id} connector={connector} connecting={connecting} onToggle={handleToggle} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ConnectorCard({ connector, connecting, onToggle }: {
  connector: Connector;
  connecting: string | null;
  onToggle: (c: Connector) => void;
}) {
  const icon = CONNECTOR_ICONS[connector.type?.toLowerCase()] || CONNECTOR_ICONS.default;
  const isLoading = connecting === connector.id;

  return (
    <div className={`flex items-center justify-between px-3 py-2.5 rounded-lg border mb-1.5 transition-colors ${
      (connector.connected || connector.status === 'connected')
        ? "bg-emerald-50/50 dark:bg-emerald-950/10 border-emerald-100 dark:border-emerald-900/40"
        : "bg-gray-50 dark:bg-gray-800/50 border-gray-100 dark:border-gray-700/50"
    }`}>
      <div className="flex items-center gap-2.5">
        <span className="text-base">{icon}</span>
        <div>
          <p className="text-xs font-medium text-gray-800 dark:text-gray-200">{connector.name}</p>
          {connector.description && (
            <p className="text-[10px] text-gray-500 dark:text-gray-400">{connector.description}</p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {(connector.connected || connector.status === 'connected') ? (
          <CheckCircle size={13} className="text-emerald-500" />
        ) : (
          <XCircle size={13} className="text-gray-300 dark:text-gray-600" />
        )}
        <button
          onClick={() => onToggle(connector)}
          disabled={isLoading}
          className={`px-2.5 py-1 text-[10px] rounded-lg transition-colors disabled:opacity-50 ${
            (connector.connected || connector.status === 'connected')
              ? "bg-red-50 dark:bg-red-950/30 text-red-500 hover:bg-red-100 dark:hover:bg-red-950/50"
              : "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600 hover:bg-emerald-100 dark:hover:bg-emerald-950/50"
          }`}
        >
          {isLoading ? (
            <Loader2 size={10} className="animate-spin" />
          ) : (connector.connected || connector.status === 'connected') ? "Отключить" : "Подключить"}
        </button>
      </div>
    </div>
  );
}
