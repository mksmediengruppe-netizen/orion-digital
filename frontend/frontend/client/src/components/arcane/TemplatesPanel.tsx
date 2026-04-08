// ARCANE TemplatesPanel — Real API Integration
// Displays task templates from /api/templates
import { useState, useEffect, useCallback } from "react";
import { FileText, RefreshCw, X, Search, Play, Tag } from "lucide-react";
import api, { type TaskTemplate } from "@/lib/api";

interface TemplatesPanelProps {
  onClose?: () => void;
  onUseTemplate?: (prompt: string) => void;
}

export function TemplatesPanel({ onClose, onUseTemplate }: TemplatesPanelProps) {
  const [templates, setTemplates] = useState<TaskTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.templates.list();
      setTemplates(res.templates || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки шаблонов");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const categories = Array.from(new Set(templates.map(t => t.category).filter(Boolean))) as string[];

  const filtered = templates.filter(t => {
    const matchSearch = !search ||
      ((t.title || t.name || '').toLowerCase()).includes(search.toLowerCase()) ||
      (t.description || "").toLowerCase().includes(search.toLowerCase()) ||
      (t.tags || []).some(tag => tag.toLowerCase().includes(search.toLowerCase()));
    const matchCategory = !selectedCategory || t.category === selectedCategory;
    return matchSearch && matchCategory;
  });

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#1C1C1E]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <FileText size={16} className="text-amber-500" />
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-100">Шаблоны задач</span>
          <span className="text-[10px] bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 px-1.5 py-0.5 rounded-full">
            {templates.length}
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

      {/* Search */}
      <div className="px-3 py-2 border-b border-gray-100 dark:border-gray-800">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск шаблонов..."
            className="w-full pl-7 pr-3 py-1.5 text-xs bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-700 dark:text-gray-300 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-amber-300"
          />
        </div>
        {categories.length > 0 && (
          <div className="flex gap-1 mt-2 flex-wrap">
            <button
              onClick={() => setSelectedCategory(null)}
              className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
                !selectedCategory
                  ? "bg-amber-500 text-white border-amber-500"
                  : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-amber-300"
              }`}
            >
              Все
            </button>
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
                className={`px-2 py-0.5 text-[10px] rounded-full border transition-colors ${
                  selectedCategory === cat
                    ? "bg-amber-500 text-white border-amber-500"
                    : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-amber-300"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mx-3 mt-2 px-3 py-2 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg text-xs text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Templates list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-xs text-gray-400">
            <RefreshCw size={14} className="animate-spin mr-2" /> Загрузка шаблонов...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-xs text-gray-400 gap-2">
            <FileText size={24} className="text-gray-300 dark:text-gray-600" />
            <span>{search || selectedCategory ? "Ничего не найдено" : "Нет шаблонов"}</span>
          </div>
        ) : (
          filtered.map(template => (
            <div key={template.id} className="group bg-gray-50 dark:bg-gray-800/50 border border-gray-100 dark:border-gray-700/50 rounded-lg p-3 hover:border-amber-200 dark:hover:border-amber-800 transition-colors">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate">{template.title || template.name}</p>
                  {template.description && (
                    <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">{template.description}</p>
                  )}
                </div>
                {onUseTemplate && (
                  <button
                    onClick={() => onUseTemplate(template.prompt)}
                    className="shrink-0 flex items-center gap-1 px-2 py-1 text-[10px] bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400 rounded-lg hover:bg-amber-100 dark:hover:bg-amber-950/50 transition-colors opacity-0 group-hover:opacity-100"
                  >
                    <Play size={9} /> Запустить
                  </button>
                )}
              </div>
              <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                {template.category && (
                  <span className="text-[10px] bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400 px-1.5 py-0.5 rounded">
                    {template.category}
                  </span>
                )}
                {template.tags?.map(tag => (
                  <span key={tag} className="inline-flex items-center gap-0.5 text-[10px] bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 px-1.5 py-0.5 rounded">
                    <Tag size={8} /> {tag}
                  </span>
                ))}
              </div>
              <p className="text-[10px] text-gray-400 dark:text-gray-600 mt-2 line-clamp-2 italic">
                {template.prompt.slice(0, 120)}{template.prompt.length > 120 ? "..." : ""}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
