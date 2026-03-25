// ORION MemoryPanel — Real API Integration
// Displays and manages agent memory entries from /api/memory
import { useState, useEffect, useCallback } from "react";
import { Brain, Search, Trash2, Plus, RefreshCw, X, Tag, Clock } from "lucide-react";
import api, { type MemoryEntry } from "@/lib/api";

interface MemoryPanelProps {
  onClose?: () => void;
}

export function MemoryPanel({ onClose }: MemoryPanelProps) {
  const [memories, setMemories] = useState<MemoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [searching, setSearching] = useState(false);
  const [stats, setStats] = useState<{ total: number; sessions?: number; size_kb?: number; initialized?: boolean } | null>(null);
  const [addMode, setAddMode] = useState(false);
  const [newContent, setNewContent] = useState("");
  const [newTags, setNewTags] = useState("");
  const [saving, setSaving] = useState(false);

  const loadMemories = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [memRes, statsRes] = await Promise.all([
        api.memory.list(),
        api.memory.stats(),
      ]);
      setMemories(memRes.memories || []);
      setStats(statsRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки памяти");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadMemories(); }, [loadMemories]);

  const handleSearch = async () => {
    if (!search.trim()) { loadMemories(); return; }
    setSearching(true);
    try {
      const res = await api.memory.search(search.trim());
      setMemories(res.memories || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка поиска");
    } finally {
      setSearching(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.memory.delete(id);
      setMemories(prev => prev.filter(m => m.id !== id));
      if (stats) setStats(s => s ? { ...s, total: s.total - 1 } : s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления");
    }
  };

  const handleAdd = async () => {
    if (!newContent.trim()) return;
    setSaving(true);
    try {
      const tags = newTags.split(",").map(t => t.trim()).filter(Boolean);
      const res = await api.memory.store(newContent.trim(), "manual", tags);
      setMemories(prev => [res.memory, ...prev]);
      setNewContent("");
      setNewTags("");
      setAddMode(false);
      if (stats) setStats(s => s ? { ...s, total: s.total + 1 } : s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#1C1C1E]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-indigo-500" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-100">Память агента</span>
          {stats && (
            <span className="text-[10px] bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 px-1.5 py-0.5 rounded-full">
              {stats.total} записей{stats.size_kb !== undefined ? ` · ${stats.size_kb.toFixed(1)} KB` : ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={loadMemories} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 transition-colors" title="Обновить">
            <RefreshCw size={13} />
          </button>
          <button onClick={() => setAddMode(v => !v)} className="p-1.5 rounded hover:bg-indigo-50 dark:hover:bg-indigo-950/40 text-indigo-500 transition-colors" title="Добавить запись">
            <Plus size={13} />
          </button>
          {onClose && (
            <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 transition-colors">
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-gray-100 dark:border-gray-800">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleSearch()}
              placeholder="Семантический поиск по памяти..."
              className="w-full pl-7 pr-3 py-1.5 text-xs bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-300"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={searching}
            className="px-3 py-1.5 text-xs bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors disabled:opacity-50"
          >
            {searching ? "..." : "Найти"}
          </button>
          {search && (
            <button onClick={() => { setSearch(""); loadMemories(); }} className="px-2 py-1.5 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
              Сброс
            </button>
          )}
        </div>
      </div>

      {/* Add form */}
      {addMode && (
        <div className="px-3 py-2 border-b border-indigo-100 dark:border-indigo-900/40 bg-indigo-50/50 dark:bg-indigo-950/20">
          <textarea
            value={newContent}
            onChange={e => setNewContent(e.target.value)}
            placeholder="Содержимое записи..."
            rows={3}
            className="w-full px-3 py-2 text-xs bg-white dark:bg-gray-800 border border-indigo-200 dark:border-indigo-800 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-300 resize-none"
          />
          <div className="flex gap-2 mt-2">
            <input
              value={newTags}
              onChange={e => setNewTags(e.target.value)}
              placeholder="Теги через запятую..."
              className="flex-1 px-3 py-1.5 text-xs bg-white dark:bg-gray-800 border border-indigo-200 dark:border-indigo-800 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-300"
            />
            <button
              onClick={handleAdd}
              disabled={saving || !newContent.trim()}
              className="px-3 py-1.5 text-xs bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors disabled:opacity-50"
            >
              {saving ? "..." : "Сохранить"}
            </button>
            <button onClick={() => setAddMode(false)} className="px-2 py-1.5 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
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

      {/* Memory list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-xs text-gray-400">
            <RefreshCw size={14} className="animate-spin mr-2" /> Загрузка памяти...
          </div>
        ) : memories.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-xs text-gray-400 gap-2">
            <Brain size={24} className="text-gray-300 dark:text-gray-600" />
            <span>{search ? "Ничего не найдено" : "Память пуста"}</span>
          </div>
        ) : (
          memories.map(mem => (
            <div key={mem.id} className="group relative bg-gray-50 dark:bg-gray-800/50 border border-gray-100 dark:border-gray-700/50 rounded-lg p-3 hover:border-indigo-200 dark:hover:border-indigo-800 transition-colors">
              <p className="text-xs text-gray-700 dark:text-gray-300 leading-relaxed pr-6">{mem.content}</p>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                {mem.source && (
                  <span className="text-[10px] text-gray-400 dark:text-gray-500">
                    {mem.source}
                  </span>
                )}
                {mem.tags && mem.tags.length > 0 && mem.tags.map(tag => (
                  <span key={tag} className="inline-flex items-center gap-0.5 text-[10px] bg-indigo-50 dark:bg-indigo-950/40 text-indigo-500 dark:text-indigo-400 px-1.5 py-0.5 rounded">
                    <Tag size={8} /> {tag}
                  </span>
                ))}
                <span className="text-[10px] text-gray-400 dark:text-gray-600 flex items-center gap-0.5 ml-auto">
                  <Clock size={9} />
                  {new Date(mem.created_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "short" })}
                </span>
                {mem.relevance !== undefined && (
                  <span className="text-[10px] bg-green-50 dark:bg-green-950/30 text-green-600 dark:text-green-400 px-1.5 py-0.5 rounded">
                    {(mem.relevance * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              <button
                onClick={() => handleDelete(mem.id)}
                className="absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 dark:hover:bg-red-950/30 text-gray-400 hover:text-red-500 transition-all"
                title="Удалить"
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
