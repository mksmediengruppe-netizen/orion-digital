// ARCANE ModelsPanel — Real API Integration
// Displays available AI models from /api/models
import { useState, useEffect, useCallback } from "react";
import { Cpu, RefreshCw, X, CheckCircle, DollarSign, Hash } from "lucide-react";
import api, { type ModelInfo } from "@/lib/api";

interface ModelsPanelProps {
  onClose?: () => void;
  selectedModel?: string;
  onSelectModel?: (modelId: string) => void;
}

const PROVIDER_COLORS: Record<string, string> = {
  openai: "bg-green-50 dark:bg-green-950/30 text-green-600 dark:text-green-400",
  anthropic: "bg-orange-50 dark:bg-orange-950/30 text-orange-600 dark:text-orange-400",
  google: "bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400",
  mistral: "bg-purple-50 dark:bg-purple-950/30 text-purple-600 dark:text-purple-400",
  default: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400",
};

export function ModelsPanel({ onClose, selectedModel, onSelectModel }: ModelsPanelProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.models.list();
      setModels(res.models || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки моделей");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = models.filter(m =>
    !filter || m.name.toLowerCase().includes(filter.toLowerCase()) ||
    m.id.toLowerCase().includes(filter.toLowerCase()) ||
    (m.provider || "").toLowerCase().includes(filter.toLowerCase())
  );

  const byProvider = filtered.reduce((acc, m) => {
    const p = m.provider || "other";
    if (!acc[p]) acc[p] = [];
    acc[p].push(m);
    return acc;
  }, {} as Record<string, ModelInfo[]>);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#1C1C1E]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <Cpu size={16} className="text-blue-500" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-100">Модели</span>
          <span className="text-[10px] bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 px-1.5 py-0.5 rounded-full">
            {models.filter(m => m.available !== false).length} доступно
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

      {/* Filter */}
      <div className="px-3 py-2 border-b border-gray-100 dark:border-gray-800">
        <input
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Фильтр по названию или провайдеру..."
          className="w-full px-3 py-1.5 text-xs bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-300"
        />
      </div>

      {/* Error */}
      {error && (
        <div className="mx-3 mt-2 px-3 py-2 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg text-xs text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Models list */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-xs text-gray-400">
            <RefreshCw size={14} className="animate-spin mr-2" /> Загрузка моделей...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-xs text-gray-400 gap-2">
            <Cpu size={24} className="text-gray-300 dark:text-gray-600" />
            <span>{filter ? "Ничего не найдено" : "Нет доступных моделей"}</span>
          </div>
        ) : (
          Object.entries(byProvider).map(([provider, provModels]) => (
            <div key={provider} className="mb-4">
              <p className="text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1.5 px-1">
                {provider}
              </p>
              <div className="space-y-1.5">
                {provModels.map(model => {
                  const colorClass = PROVIDER_COLORS[provider.toLowerCase()] || PROVIDER_COLORS.default;
                  const isSelected = selectedModel === model.id;
                  const isAvailable = model.available !== false;
                  return (
                    <div
                      key={model.id}
                      onClick={() => isAvailable && onSelectModel?.(model.id)}
                      className={`flex items-center justify-between px-3 py-2.5 rounded-lg border transition-colors ${
                        isSelected
                          ? "bg-blue-50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-800"
                          : isAvailable
                          ? "bg-gray-50 dark:bg-gray-800/50 border-gray-100 dark:border-gray-700/50 hover:border-blue-200 dark:hover:border-blue-800 cursor-pointer"
                          : "bg-gray-50/50 dark:bg-gray-800/20 border-gray-100 dark:border-gray-700/30 opacity-50"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {isSelected && <CheckCircle size={12} className="text-blue-500 shrink-0" />}
                        <div>
                          <p className={`text-xs font-medium ${isSelected ? "text-blue-700 dark:text-blue-300" : "text-gray-800 dark:text-gray-200"}`}>
                            {model.name}
                          </p>
                          <p className="text-[10px] text-gray-400 dark:text-gray-500">{model.id}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {model.context_length && (
                          <span className="text-[10px] bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 px-1.5 py-0.5 rounded flex items-center gap-0.5">
                            <Hash size={8} /> {(model.context_length / 1000).toFixed(0)}K
                          </span>
                        )}
                        {model.cost_per_1k_input !== undefined && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ${colorClass}`}>
                            <DollarSign size={8} /> {model.cost_per_1k_input.toFixed(3)}
                          </span>
                        )}
                        {!isAvailable && (
                          <span className="text-[10px] bg-gray-100 dark:bg-gray-700 text-gray-400 px-1.5 py-0.5 rounded">
                            Недоступна
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
