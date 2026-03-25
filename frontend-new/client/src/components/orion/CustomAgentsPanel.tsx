// ORION CustomAgentsPanel — Real API Integration
// Manages custom agents via /api/agents/custom
import { useState, useEffect, useCallback } from "react";
import { Bot, Plus, Trash2, RefreshCw, X, ChevronDown, ChevronUp, Cpu } from "lucide-react";
import api, { type CustomAgent, type ModelInfo } from "@/lib/api";

interface CustomAgentsPanelProps {
  onClose?: () => void;
}

const AVAILABLE_TOOLS = ["browser", "terminal", "ssh", "files", "images", "api"];

export function CustomAgentsPanel({ onClose }: CustomAgentsPanelProps) {
  const [agents, setAgents] = useState<CustomAgent[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createMode, setCreateMode] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    name: "",
    description: "",
    system_prompt: "",
    model: "",
    tools: [] as string[],
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [agRes, modRes] = await Promise.all([
        api.agents.list(),
        api.models.list().catch(() => ({ models: [] })),
      ]);
      setAgents(agRes.agents || []);
      setModels(modRes.models || []);
      if (modRes.models?.[0]) setForm(f => ({ ...f, model: modRes.models[0].id }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!form.name.trim() || !form.system_prompt.trim()) return;
    setSaving(true);
    try {
      const res = await api.agents.create({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        system_prompt: form.system_prompt.trim(),
        model: form.model || undefined,
        tools: form.tools.length > 0 ? form.tools : undefined,
      });
      setAgents(prev => [res.agent, ...prev]);
      setForm({ name: "", description: "", system_prompt: "", model: models[0]?.id || "", tools: [] });
      setCreateMode(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка создания");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Удалить агента?")) return;
    try {
      await api.agents.delete(id);
      setAgents(prev => prev.filter(a => a.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления");
    }
  };

  const toggleTool = (tool: string) => {
    setForm(f => ({
      ...f,
      tools: f.tools.includes(tool) ? f.tools.filter(t => t !== tool) : [...f.tools, tool],
    }));
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#1C1C1E]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <Bot size={16} className="text-violet-500" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-100">Кастомные агенты</span>
          <span className="text-[10px] bg-violet-50 dark:bg-violet-950/40 text-violet-600 dark:text-violet-400 px-1.5 py-0.5 rounded-full">
            {agents.length}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={load} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 transition-colors">
            <RefreshCw size={13} />
          </button>
          <button onClick={() => setCreateMode(v => !v)} className="p-1.5 rounded hover:bg-violet-50 dark:hover:bg-violet-950/40 text-violet-500 transition-colors">
            <Plus size={13} />
          </button>
          {onClose && (
            <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 transition-colors">
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Create form */}
      {createMode && (
        <div className="px-3 py-3 border-b border-violet-100 dark:border-violet-900/40 bg-violet-50/30 dark:bg-violet-950/10 space-y-2">
          <input
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            placeholder="Название агента *"
            className="w-full px-3 py-1.5 text-xs bg-white dark:bg-gray-800 border border-violet-200 dark:border-violet-800 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-300"
          />
          <input
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            placeholder="Описание (необязательно)"
            className="w-full px-3 py-1.5 text-xs bg-white dark:bg-gray-800 border border-violet-200 dark:border-violet-800 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-300"
          />
          <textarea
            value={form.system_prompt}
            onChange={e => setForm(f => ({ ...f, system_prompt: e.target.value }))}
            placeholder="Системный промпт *"
            rows={4}
            className="w-full px-3 py-2 text-xs bg-white dark:bg-gray-800 border border-violet-200 dark:border-violet-800 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-300 resize-none"
          />
          {models.length > 0 && (
            <select
              value={form.model}
              onChange={e => setForm(f => ({ ...f, model: e.target.value }))}
              className="w-full px-3 py-1.5 text-xs bg-white dark:bg-gray-800 border border-violet-200 dark:border-violet-800 rounded-lg text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-violet-300"
            >
              {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          )}
          <div>
            <p className="text-[10px] text-gray-500 dark:text-gray-400 mb-1">Инструменты:</p>
            <div className="flex flex-wrap gap-1">
              {AVAILABLE_TOOLS.map(tool => (
                <button
                  key={tool}
                  onClick={() => toggleTool(tool)}
                  className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
                    form.tools.includes(tool)
                      ? "bg-violet-500 text-white border-violet-500"
                      : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-violet-300"
                  }`}
                >
                  {tool}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={saving || !form.name.trim() || !form.system_prompt.trim()}
              className="flex-1 py-1.5 text-xs bg-violet-500 text-white rounded-lg hover:bg-violet-600 transition-colors disabled:opacity-50"
            >
              {saving ? "Создание..." : "Создать агента"}
            </button>
            <button onClick={() => setCreateMode(false)} className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
              Отмена
            </button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mx-3 mt-2 px-3 py-2 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg text-xs text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Agents list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-xs text-gray-400">
            <RefreshCw size={14} className="animate-spin mr-2" /> Загрузка агентов...
          </div>
        ) : agents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-xs text-gray-400 gap-2">
            <Bot size={24} className="text-gray-300 dark:text-gray-600" />
            <span>Нет кастомных агентов</span>
            <button onClick={() => setCreateMode(true)} className="text-violet-500 hover:text-violet-600 underline">
              Создать первого
            </button>
          </div>
        ) : (
          agents.map(agent => (
            <div key={agent.id} className="bg-gray-50 dark:bg-gray-800/50 border border-gray-100 dark:border-gray-700/50 rounded-lg overflow-hidden">
              <div
                className="flex items-center justify-between px-3 py-2.5 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                onClick={() => setExpandedId(expandedId === agent.id ? null : agent.id)}
              >
                <div className="flex items-center gap-2">
                  <div className="w-6 h-6 rounded-full bg-violet-100 dark:bg-violet-950/40 flex items-center justify-center">
                    <Bot size={12} className="text-violet-500" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-gray-800 dark:text-gray-200">{agent.name}</p>
                    {agent.description && (
                      <p className="text-[10px] text-gray-500 dark:text-gray-400">{agent.description}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {agent.model && (
                    <span className="text-[10px] bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 px-1.5 py-0.5 rounded flex items-center gap-0.5">
                      <Cpu size={8} /> {agent.model}
                    </span>
                  )}
                  <button
                    onClick={e => { e.stopPropagation(); handleDelete(agent.id); }}
                    className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-950/30 text-gray-400 hover:text-red-500 transition-colors"
                  >
                    <Trash2 size={11} />
                  </button>
                  {expandedId === agent.id ? <ChevronUp size={12} className="text-gray-400" /> : <ChevronDown size={12} className="text-gray-400" />}
                </div>
              </div>
              {expandedId === agent.id && (
                <div className="px-3 pb-3 border-t border-gray-100 dark:border-gray-700/50 pt-2">
                  <p className="text-[10px] text-gray-500 dark:text-gray-400 mb-1">Системный промпт:</p>
                  <p className="text-xs text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-900 rounded p-2 border border-gray-100 dark:border-gray-700 max-h-24 overflow-y-auto leading-relaxed">
                    {agent.system_prompt}
                  </p>
                  {agent.tools && agent.tools.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {agent.tools.map(t => (
                        <span key={t} className="text-[10px] bg-violet-50 dark:bg-violet-950/30 text-violet-500 px-1.5 py-0.5 rounded">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  <p className="text-[10px] text-gray-400 dark:text-gray-600 mt-2">
                    Создан: {new Date(agent.created_at).toLocaleDateString("ru-RU")}
                  </p>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
