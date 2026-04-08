import { useState, useEffect, useCallback, useRef, useMemo } from "react";

// ─── Data ────────────────────────────────────────────────────────────────────
const MODELS = [
  { id: "claude-opus-4.6", name: "Claude Opus 4.6", color: "#D4A574", costPerMTokIn: 5, costPerMTokOut: 25, icon: "◈" },
  { id: "claude-sonnet-4.6", name: "Claude Sonnet 4.6", color: "#7EB8DA", costPerMTokIn: 3, costPerMTokOut: 15, icon: "◇" },
  { id: "claude-haiku-4.5", name: "Claude Haiku 4.5", color: "#A8D5BA", costPerMTokIn: 1, costPerMTokOut: 5, icon: "△" },
  { id: "gpt-5.4", name: "GPT-5.4", color: "#C4A7E7", costPerMTokIn: 2.5, costPerMTokOut: 15, icon: "●" },
  { id: "gpt-5.4-mini", name: "GPT-5.4 Mini", color: "#B8A9C9", costPerMTokIn: 0.75, costPerMTokOut: 4.5, icon: "○" },
  { id: "gemini-3.1-pro", name: "Gemini 3.1 Pro", color: "#F2C078", costPerMTokIn: 2, costPerMTokOut: 12, icon: "✦" },
  { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", color: "#E8D5A3", costPerMTokIn: 0.3, costPerMTokOut: 2.5, icon: "⚡" },
  { id: "deepseek-v3.2", name: "DeepSeek V3.2", color: "#82C9A5", costPerMTokIn: 0.28, costPerMTokOut: 0.42, icon: "◆" },
  { id: "minimax-m2.5", name: "MiniMax M2.5", color: "#E09F7D", costPerMTokIn: 0.3, costPerMTokOut: 1.2, icon: "■" },
  { id: "kimi-k2.5", name: "Kimi K2.5", color: "#9BC1BC", costPerMTokIn: 0, costPerMTokOut: 0, icon: "★" },
];

const MODEL_MAP = Object.fromEntries(MODELS.map((m) => [m.id, m]));
const FALLBACK_MODEL = { name: "Unknown", color: "#555566", icon: "?", costPerMTokIn: 0, costPerMTokOut: 0 };
const getModel = (id) => MODEL_MAP[id] || { ...FALLBACK_MODEL, id };

const CATEGORIES = [
  { id: "design", label: "Дизайн / HTML", emoji: "🎨" },
  { id: "backend", label: "Backend / API", emoji: "⚙️" },
  { id: "review", label: "Code Review", emoji: "🔍" },
  { id: "text", label: "Тексты / Copy", emoji: "✍️" },
  { id: "devops", label: "DevOps", emoji: "🚀" },
];
const CATEGORY_MAP = Object.fromEntries(CATEGORIES.map((c) => [c.id, c]));

const SAMPLE_OUTPUTS_BY_CAT = {
  design: [
    "Реализован компонент с адаптивной сеткой CSS Grid, анимациями hover-эффектов и lazy-loading для изображений. Семантический HTML5, BEM-нейминг. Lighthouse: Performance 98, Accessibility 100.",
    "Hero-секция с параллакс-эффектом, gradient mesh фоном, анимированной типографикой. Container queries для адаптива. View Transitions API для навигации.",
  ],
  backend: [
    "REST API с JWT-авторизацией, rate limiting, валидацией через Zod, миграциями Prisma. Покрытие тестами 87%. OpenAPI-спека сгенерирована автоматически.",
    "GraphQL API с подписками через WebSocket, DataLoader для N+1, кеширование Redis, автогенерация TypeScript типов из схемы.",
  ],
  review: [
    "Найдено 3 критических уязвимости: SQL injection в search endpoint, отсутствие CSRF-токенов, утечка stack trace в production errors. Предложены патчи.",
    "Race condition в параллельных транзакциях — pessimistic locking. Memory leak в event listeners — паттерн cleanup. Неиспользуемые зависимости в bundle.",
  ],
  text: [
    "Landing copy с A/B вариантами заголовков, CTA-блоками, SEO-мета. Tone of voice: уверенный, дружелюбный. Readability score: 72. Alt-тексты для изображений.",
    "Документация API: 12 эндпоинтов, примеры запросов/ответов, коды ошибок, rate limits. Markdown + OpenAPI 3.1.",
  ],
  devops: [
    "CI/CD pipeline: GitHub Actions → Docker build → staging deploy → smoke tests → production с blue-green strategy. Rollback за 30 сек. Мониторинг Prometheus + Grafana.",
    "Terraform конфигурация для AWS: VPC, ECS Fargate, RDS PostgreSQL, CloudFront CDN. Автоскейлинг 2–10 инстансов. Ежедневные бэкапы с 30-дневной ретенцией.",
  ],
};

function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function simulateRace(modelId, category) {
  const model = getModel(modelId);
  const tokensIn = 800 + Math.floor(Math.random() * 1200);
  const tokensOut = 1500 + Math.floor(Math.random() * 3000);
  const costIn = (tokensIn / 1_000_000) * model.costPerMTokIn;
  const costOut = (tokensOut / 1_000_000) * model.costPerMTokOut;
  const time = +(1.2 + Math.random() * 8.5).toFixed(2);
  const pool = SAMPLE_OUTPUTS_BY_CAT[category] || Object.values(SAMPLE_OUTPUTS_BY_CAT).flat();
  const output = pool[Math.floor(Math.random() * pool.length)];
  return { modelId, tokensIn, tokensOut, cost: costIn + costOut, time, output };
}

function formatCost(cost) {
  if (cost === 0) return "$0";
  if (cost < 0.001) return `$${(cost * 1_000_000).toFixed(0)}µ`;
  if (cost < 1) return `$${(cost * 1000).toFixed(2)}m`;
  return `$${cost.toFixed(2)}`;
}

// ─── Persistence ─────────────────────────────────────────────────────────────
const STORAGE_KEY = "dog-racing-races";

async function loadRaces() {
  try {
    const result = await window.storage.get(STORAGE_KEY);
    if (result && result.value) return JSON.parse(result.value);
  } catch { /* not found */ }
  return [];
}

async function persistRaces(races) {
  try {
    await window.storage.set(STORAGE_KEY, JSON.stringify(races));
  } catch (e) {
    console.error("Storage save failed:", e);
  }
}

// ─── Styles ──────────────────────────────────────────────────────────────────
const font = `'JetBrains Mono', 'Fira Code', 'SF Mono', monospace`;
const fontDisplay = `'Unbounded', 'Space Grotesk', sans-serif`;

const S = {
  root: { fontFamily: font, fontSize: 13, background: "#0A0A0F", color: "#C8C8D0", minHeight: "100vh", padding: "0 0 60px 0" },
  header: { padding: "32px 32px 24px", borderBottom: "1px solid #1A1A25", background: "linear-gradient(180deg, #0F0F18 0%, #0A0A0F 100%)", position: "relative", overflow: "hidden" },
  headerGlow: { position: "absolute", top: -80, right: -80, width: 300, height: 300, borderRadius: "50%", background: "radial-gradient(circle, rgba(212,165,116,0.06) 0%, transparent 70%)", pointerEvents: "none" },
  title: { fontFamily: fontDisplay, fontSize: 28, fontWeight: 800, color: "#EDEDF0", letterSpacing: "-0.02em", margin: 0, position: "relative" },
  subtitle: { fontSize: 12, color: "#5A5A6A", marginTop: 6, letterSpacing: "0.08em", textTransform: "uppercase" },
  tabs: { display: "flex", gap: 0, borderBottom: "1px solid #1A1A25", background: "#0D0D15" },
  card: { background: "#0F0F18", border: "1px solid #1A1A25", borderRadius: 10, padding: 20, marginBottom: 16 },
  label: { fontSize: 10, fontWeight: 700, color: "#5A5A6A", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8, display: "block" },
  textarea: { width: "100%", background: "#12121C", border: "1px solid #1E1E30", borderRadius: 6, padding: "10px 14px", color: "#C8C8D0", fontFamily: font, fontSize: 13, outline: "none", boxSizing: "border-box", minHeight: 80, resize: "vertical" },
  raceTrack: { position: "relative", background: "#0D0D15", border: "1px solid #1A1A25", borderRadius: 10, overflow: "hidden", marginBottom: 16 },
  statBox: { display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", flex: 1 },
  statVal: { fontFamily: fontDisplay, fontSize: 22, fontWeight: 800, color: "#EDEDF0", lineHeight: 1 },
  statLabel: { fontSize: 9, fontWeight: 700, color: "#5A5A6A", letterSpacing: "0.1em", textTransform: "uppercase", marginTop: 6 },
};

const tabStyle = (active) => ({
  padding: "14px 28px", fontSize: 12, fontFamily: font, fontWeight: 600,
  color: active ? "#D4A574" : "#5A5A6A", background: "transparent", border: "none",
  borderBottom: active ? "2px solid #D4A574" : "2px solid transparent",
  cursor: "pointer", letterSpacing: "0.04em", textTransform: "uppercase", transition: "all 0.2s",
});
const chipStyle = (sel, color, dis = false) => ({
  display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px",
  borderRadius: 6, fontSize: 12, fontWeight: 600, fontFamily: font,
  cursor: dis ? "not-allowed" : "pointer",
  border: sel ? `1px solid ${color}` : "1px solid #1E1E30",
  background: sel ? `${color}11` : "#12121C",
  color: sel ? color : "#5A5A6A",
  opacity: dis ? 0.35 : 1, transition: "all 0.2s", userSelect: "none",
});
const badgeStyle = (color) => ({
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  width: 28, height: 28, borderRadius: 6, background: `${color}18`,
  color, fontSize: 14, fontWeight: 800, flexShrink: 0,
});
const btnPrimary = (dis) => ({
  padding: "12px 32px", borderRadius: 8, border: "none", fontFamily: font,
  fontSize: 13, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase",
  cursor: dis ? "not-allowed" : "pointer",
  background: dis ? "#1E1E30" : "linear-gradient(135deg, #D4A574, #C48B5C)",
  color: dis ? "#5A5A6A" : "#0A0A0F", transition: "all 0.3s",
  boxShadow: dis ? "none" : "0 4px 20px rgba(212,165,116,0.2)",
});
const scoreBtnStyle = (active, val) => {
  const c = active ? (val >= 7 ? "#A8D5BA" : val >= 4 ? "#F2C078" : "#E07070") : "#2A2A3A";
  return {
    width: 30, height: 30, borderRadius: 6,
    border: active ? `1px solid ${c}` : "1px solid #1E1E30",
    background: active ? `${c}22` : "#12121C",
    color: active ? c : "#4A4A5A",
    fontFamily: font, fontSize: 11, fontWeight: 700, cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center", transition: "all 0.15s",
  };
};
const rankStyle = (i) => ({
  fontFamily: fontDisplay, fontWeight: 800, fontSize: i === 0 ? 18 : 14,
  color: i === 0 ? "#D4A574" : i === 1 ? "#8A8A9A" : i === 2 ? "#A0785A" : "#3A3A4A",
});
const laneStyle = (i) => ({
  display: "flex", alignItems: "center", padding: "12px 16px",
  borderBottom: "1px solid #13131E", background: i % 2 === 0 ? "#0D0D15" : "#0F0F19",
  position: "relative", overflow: "hidden",
});
const progressBarStyle = (pct, color) => ({
  position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct}%`,
  background: `linear-gradient(90deg, ${color}08, ${color}18)`,
  transition: "width 0.6s cubic-bezier(0.22,1,0.36,1)",
});
const leaderRowStyle = (i) => ({
  display: "grid", gridTemplateColumns: "40px 1fr 80px 80px 80px 70px",
  alignItems: "center", padding: "12px 16px", borderBottom: "1px solid #13131E",
  background: i === 0 ? "#14140E" : i % 2 === 0 ? "#0D0D15" : "#0F0F19",
});

// ─── Sub-components ──────────────────────────────────────────────────────────
function ModelSelector({ selected, onChange, disabled: formOff }) {
  const atLimit = selected.length >= 5;
  const toggle = (id) => {
    if (formOff) return;
    if (selected.includes(id)) onChange(selected.filter((s) => s !== id));
    else if (!atLimit) onChange([...selected, id]);
  };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {MODELS.map((m) => {
        const isSel = selected.includes(m.id);
        const isDis = formOff || (!isSel && atLimit);
        return (
          <button key={m.id} type="button" aria-pressed={isSel} aria-disabled={isDis}
            style={chipStyle(isSel, m.color, isDis)} onClick={() => toggle(m.id)} tabIndex={0}>
            <span style={{ fontSize: 14 }}>{m.icon}</span>{m.name}
          </button>
        );
      })}
    </div>
  );
}

function CategoryPicker({ value, onChange, disabled }) {
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }} role="radiogroup" aria-label="Категория">
      {CATEGORIES.map((c) => (
        <button key={c.id} type="button" role="radio" aria-checked={value === c.id} aria-disabled={disabled}
          style={{ ...chipStyle(value === c.id, "#D4A574", disabled), gap: 5 }}
          onClick={() => !disabled && onChange(c.id)} tabIndex={0}>
          <span>{c.emoji}</span> {c.label}
        </button>
      ))}
    </div>
  );
}

function RaceAnimation({ runners, phase }) {
  return (
    <div style={S.raceTrack}>
      <div style={{ padding: "8px 16px", fontSize: 10, fontWeight: 700, color: "#5A5A6A", letterSpacing: "0.1em", textTransform: "uppercase", borderBottom: "1px solid #1A1A25", display: "flex", justifyContent: "space-between" }}>
        <span>Трек</span>
        <span style={{ color: phase === "running" ? "#D4A574" : phase === "done" ? "#A8D5BA" : "#5A5A6A" }}>
          {phase === "running" ? "● LIVE" : phase === "done" ? "✓ ФИНИШ" : "ОЖИДАНИЕ"}
        </span>
      </div>
      {runners.map((r, i) => {
        const model = getModel(r.modelId);
        const pct = phase === "done" ? 100 : phase === "running" ? r.progress || 0 : 0;
        return (
          <div key={r.modelId} style={laneStyle(i)}>
            <div style={progressBarStyle(pct, model.color)} />
            <div style={{ ...badgeStyle(model.color), zIndex: 1, marginRight: 12 }}>{model.icon}</div>
            <div style={{ flex: 1, zIndex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: model.color }}>{model.name}</div>
              {phase === "done" && r.result && (
                <div style={{ fontSize: 11, color: "#6A6A7A", marginTop: 2 }}>
                  {r.result.time}s · {formatCost(r.result.cost)}
                </div>
              )}
            </div>
            {phase === "done" && r.finished && (
              <div style={{ fontSize: 10, color: "#A8D5BA", fontWeight: 700, zIndex: 1 }}>✓</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ResultCard({ runner, score, onScore }) {
  if (!runner.result) return null;
  const model = getModel(runner.modelId);
  return (
    <div style={{ ...S.card, borderColor: model.color + "30", borderTop: `2px solid ${model.color}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={badgeStyle(model.color)}>{model.icon}</div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: model.color }}>{model.name}</div>
            <div style={{ fontSize: 10, color: "#5A5A6A", marginTop: 2 }}>
              {runner.result.time}s · {formatCost(runner.result.cost)} · {runner.result.tokensOut} tok
            </div>
          </div>
        </div>
        {score > 0 && (
          <div style={{ fontFamily: fontDisplay, fontSize: 20, fontWeight: 800, color: score >= 7 ? "#A8D5BA" : score >= 4 ? "#F2C078" : "#E07070" }}>
            {score}
          </div>
        )}
      </div>
      <div style={{ background: "#12121C", borderRadius: 6, padding: "12px 14px", fontSize: 12, lineHeight: 1.65, color: "#9898A8", marginBottom: 14, border: "1px solid #1A1A25" }}>
        {runner.result.output}
      </div>
      <div>
        <span style={{ ...S.label, marginBottom: 6, display: "inline-block" }}>Оценка</span>
        <div style={{ display: "flex", gap: 4 }} role="radiogroup" aria-label={`Оценка ${model.name}`}>
          {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((v) => (
            <button key={v} type="button" role="radio" aria-checked={score === v} aria-label={`${v} из 10`}
              style={scoreBtnStyle(score === v, v)} onClick={() => onScore(v)}>{v}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatsOverview({ races }) {
  const data = useMemo(() => {
    const sc = races.filter((r) => r.scores && Object.values(r.scores).some((s) => s > 0)).length;
    const all = races.flatMap((r) => r.runners.map((run) => (r.scores?.[run.modelId] || 0)).filter((s) => s > 0));
    const avg = all.length > 0 ? all.reduce((a, b) => a + b, 0) / all.length : 0;
    const cost = races.reduce((sum, r) => sum + r.runners.reduce((s2, run) => s2 + (run.result?.cost || 0), 0), 0);
    return { total: races.length, scored: sc, avg, cost };
  }, [races]);

  return (
    <div style={{ display: "flex", gap: 0, ...S.card, padding: 0, overflow: "hidden" }}>
      {[
        { val: data.total, label: "Гонок", color: "#D4A574" },
        { val: data.scored, label: "Оценено", color: "#7EB8DA" },
        { val: data.avg.toFixed(1), label: "Ср. Оценка", color: "#A8D5BA" },
        { val: formatCost(data.cost), label: "Расходы", color: "#C4A7E7" },
      ].map((s, i) => (
        <div key={i} style={{ ...S.statBox, borderRight: i < 3 ? "1px solid #1A1A25" : "none" }}>
          <div style={{ ...S.statVal, color: s.color }}>{s.val}</div>
          <div style={S.statLabel}>{s.label}</div>
        </div>
      ))}
    </div>
  );
}

function Leaderboard({ races }) {
  const [catFilter, setCatFilter] = useState("all");

  const rows = useMemo(() => {
    const stats = {};
    MODELS.forEach((m) => {
      stats[m.id] = { wins: 0, part: 0, totalScore: 0, scored: 0, totalCost: 0, byCategory: {} };
      CATEGORIES.forEach((c) => { stats[m.id].byCategory[c.id] = { wins: 0, part: 0, totalScore: 0, scored: 0 }; });
    });

    races.forEach((race) => {
      const sc = race.scores || {};
      const hasAny = Object.values(sc).some((s) => s > 0);
      if (!hasAny) return;

      // Tie-aware winners
      let best = 0;
      race.runners.forEach((r) => { const s = sc[r.modelId] || 0; if (s > best) best = s; });
      const winners = best > 0 ? race.runners.filter((r) => (sc[r.modelId] || 0) === best).map((r) => r.modelId) : [];
      const winShare = winners.length > 0 ? 1 / winners.length : 0;

      race.runners.forEach((r) => {
        if (!stats[r.modelId]) return;
        const g = stats[r.modelId];
        const cat = g.byCategory[race.category];
        const userScore = sc[r.modelId] || 0;

        // Always count participation in scored races
        g.part++;
        if (cat) cat.part++;

        if (r.result) g.totalCost += r.result.cost;
        if (userScore > 0) {
          g.totalScore += userScore;
          g.scored++;
          if (cat) { cat.totalScore += userScore; cat.scored++; }
        }
        if (winners.includes(r.modelId)) {
          g.wins += winShare;
          if (cat) cat.wins += winShare;
        }
      });
    });

    return MODELS.map((m) => {
      const g = stats[m.id];
      const c = catFilter === "all" ? g : g.byCategory[catFilter] || { wins: 0, part: 0, totalScore: 0, scored: 0 };
      const avgScore = c.scored > 0 ? c.totalScore / c.scored : 0;
      const winRate = c.part > 0 ? (c.wins / c.part) * 100 : 0;
      const eff = g.scored > 0 && g.totalCost > 0 ? (g.totalScore / g.scored) / g.totalCost : 0;
      return { model: m, avgScore, winRate, part: c.part, eff };
    }).filter((r) => r.part > 0).sort((a, b) => b.avgScore - a.avgScore || b.winRate - a.winRate);
  }, [races, catFilter]);

  return (
    <div>
      <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }} role="radiogroup" aria-label="Фильтр">
        <button type="button" role="radio" aria-checked={catFilter === "all"} style={chipStyle(catFilter === "all", "#D4A574")} onClick={() => setCatFilter("all")}>Все</button>
        {CATEGORIES.map((c) => (
          <button key={c.id} type="button" role="radio" aria-checked={catFilter === c.id} style={chipStyle(catFilter === c.id, "#D4A574")} onClick={() => setCatFilter(c.id)}>
            {c.emoji} {c.label}
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <div style={{ ...S.card, textAlign: "center", color: "#3A3A4A", padding: 40 }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>🏁</div>
          <div style={{ fontSize: 13 }}>Нет данных. Проведите гонки и поставьте оценки.</div>
        </div>
      ) : (
        <div style={S.raceTrack}>
          <div style={{ display: "grid", gridTemplateColumns: "40px 1fr 80px 80px 80px 70px", padding: "8px 16px", fontSize: 9, fontWeight: 700, color: "#4A4A5A", letterSpacing: "0.1em", textTransform: "uppercase", borderBottom: "1px solid #1A1A25" }}>
            <span>#</span><span>Модель</span>
            <span style={{ textAlign: "center" }}>Оценка</span>
            <span style={{ textAlign: "center" }}>Win Rate</span>
            <span style={{ textAlign: "center" }}>Балл/$</span>
            <span style={{ textAlign: "center" }}>Гонок</span>
          </div>
          {rows.map((r, idx) => (
            <div key={r.model.id} style={leaderRowStyle(idx)}>
              <span style={rankStyle(idx)}>{idx + 1}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={badgeStyle(r.model.color)}>{r.model.icon}</div>
                <span style={{ fontSize: 12, fontWeight: 600, color: r.model.color }}>{r.model.name}</span>
              </div>
              <div style={{ textAlign: "center", fontFamily: fontDisplay, fontWeight: 800, fontSize: 15, color: r.avgScore >= 7 ? "#A8D5BA" : r.avgScore >= 4 ? "#F2C078" : "#E07070" }}>
                {r.avgScore.toFixed(1)}
              </div>
              <div style={{ textAlign: "center", fontSize: 12, fontWeight: 700, color: "#8A8A9A" }}>{r.winRate.toFixed(0)}%</div>
              <div style={{ textAlign: "center", fontSize: 11, color: "#6A6A7A" }}>{r.eff > 0 ? r.eff.toFixed(0) : "—"}</div>
              <div style={{ textAlign: "center", fontSize: 12, color: "#5A5A6A" }}>{r.part}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main ────────────────────────────────────────────────────────────────────
export default function DogRacing() {
  const [tab, setTab] = useState("race");
  const [races, setRaces] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [task, setTask] = useState("");
  const [category, setCategory] = useState("design");
  const [selectedModels, setSelectedModels] = useState(["claude-sonnet-4.6", "gpt-5.4", "deepseek-v3.2"]);
  const [currentRace, setCurrentRace] = useState(null);
  const [phase, setPhase] = useState("idle");
  const [scores, setScores] = useState({});
  const intervalRef = useRef(null);
  const mountedRef = useRef(true);

  // Fonts via DOM (not inline <link>)
  useEffect(() => {
    const id = "dog-racing-fonts";
    if (!document.getElementById(id)) {
      const link = document.createElement("link");
      link.id = id; link.rel = "stylesheet";
      link.href = "https://fonts.googleapis.com/css2?family=Unbounded:wght@400;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap";
      document.head.appendChild(link);
    }
  }, []);

  // Load persisted races
  useEffect(() => {
    loadRaces().then((data) => {
      if (Array.isArray(data)) setRaces(data);
      setLoaded(true);
    });
  }, []);

  // Save on change
  useEffect(() => {
    if (loaded) persistRaces(races);
  }, [races, loaded]);

  // Cleanup
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const clearTimer = () => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
  };

  const startRace = useCallback(() => {
    if (selectedModels.length < 2 || !task.trim() || phase !== "idle") return;
    clearTimer();

    const runners = selectedModels.map((id) => ({ modelId: id, progress: 0, finished: false, result: null }));
    const race = { id: uid(), task: task.trim(), category, runners, scores: {}, timestamp: new Date().toISOString() };
    const raceCat = category;
    setCurrentRace(race);
    setPhase("running");
    setScores({});

    const finishTimes = runners.map(() => 1500 + Math.random() * 3000);
    const startTime = Date.now();

    intervalRef.current = setInterval(() => {
      if (!mountedRef.current) { clearTimer(); return; }
      const elapsed = Date.now() - startTime;
      let allFinished = true;

      setCurrentRace((prev) => {
        if (!prev) return prev;
        const upd = prev.runners.map((r, i) => {
          if (r.finished) return r;
          const pct = Math.min(100, (elapsed / finishTimes[i]) * 100);
          if (pct >= 100) return { ...r, progress: 100, finished: true, result: simulateRace(r.modelId, raceCat) };
          allFinished = false;
          return { ...r, progress: pct };
        });
        return { ...prev, runners: upd };
      });

      if (allFinished || elapsed > Math.max(...finishTimes) + 300) {
        clearTimer();
        if (mountedRef.current) setPhase("done");
      }
    }, 80);
  }, [selectedModels, task, category, phase]);

  const setScore = (mid, val) => setScores((p) => ({ ...p, [mid]: p[mid] === val ? 0 : val }));

  const saveRace = () => {
    if (!currentRace || phase !== "done") return;
    if (!currentRace.runners.every((r) => r.finished && r.result)) return;
    setRaces((prev) => [{ ...currentRace, scores: { ...scores } }, ...prev]);
    setCurrentRace(null); setPhase("idle"); setTask(""); setTab("leaderboard");
  };

  const deleteRace = (id) => setRaces((p) => p.filter((r) => r.id !== id));
  const clearAll = () => { setRaces([]); persistRaces([]); };

  const formOff = phase !== "idle";
  const canStart = selectedModels.length >= 2 && task.trim().length > 0 && !formOff;

  return (
    <div style={S.root}>
      <div style={S.header}>
        <div style={S.headerGlow} />
        <h1 style={S.title}><span style={{ color: "#D4A574" }}>🐕</span> Dog Racing</h1>
        <div style={S.subtitle}>Arcane 2 · Сравнение моделей · Гонки · Лидерборд</div>
      </div>

      <div style={S.tabs} role="tablist">
        {[{ id: "race", label: "Новая гонка" }, { id: "leaderboard", label: "Лидерборд" }, { id: "history", label: `История (${races.length})` }].map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} style={tabStyle(tab === t.id)} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>

      <div style={{ padding: "24px 32px", maxWidth: 1200, margin: "0 auto" }}>

        {/* ── RACE TAB ── */}
        {tab === "race" && (
          <>
            <StatsOverview races={races} />

            {phase === "idle" && (
              <>
                <div style={S.card}>
                  <label style={S.label} htmlFor="race-task">Задача</label>
                  <textarea id="race-task" style={S.textarea} maxLength={2000} disabled={formOff}
                    placeholder="Опиши задачу для моделей…"
                    value={task} onChange={(e) => setTask(e.target.value)} />
                  <div style={{ fontSize: 10, color: "#3A3A4A", marginTop: 4, textAlign: "right" }}>{task.length}/2000</div>
                </div>
                <div style={S.card}>
                  <span style={S.label}>Категория</span>
                  <CategoryPicker value={category} onChange={setCategory} disabled={formOff} />
                </div>
                <div style={S.card}>
                  <span style={S.label}>Участники (2–5 моделей)</span>
                  <ModelSelector selected={selectedModels} onChange={setSelectedModels} disabled={formOff} />
                  <div style={{ fontSize: 11, color: "#4A4A5A", marginTop: 8 }}>
                    Выбрано: {selectedModels.length}/5
                    {selectedModels.length >= 5 && <span style={{ color: "#D4A574", marginLeft: 8 }}>максимум</span>}
                  </div>
                </div>
                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                  <button style={btnPrimary(!canStart)} onClick={startRace} disabled={!canStart}>🏁 Запустить гонку</button>
                </div>
              </>
            )}

            {(phase === "running" || phase === "done") && currentRace && (
              <>
                <div style={{ ...S.card, background: "#0C0C14" }}>
                  <div style={{ fontSize: 11, color: "#5A5A6A", marginBottom: 4 }}>
                    {CATEGORY_MAP[currentRace.category]?.emoji} {CATEGORY_MAP[currentRace.category]?.label}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#EDEDF0" }}>{currentRace.task}</div>
                </div>
                <RaceAnimation runners={currentRace.runners} phase={phase} />
                {phase === "done" && (
                  <>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#5A5A6A", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12, marginTop: 20 }}>
                      Результаты · Оцените каждую модель
                    </div>
                    {currentRace.runners.map((r) => (
                      <ResultCard key={r.modelId} runner={r} score={scores[r.modelId] || 0} onScore={(v) => setScore(r.modelId, v)} />
                    ))}
                    <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", marginTop: 8 }}>
                      <button style={{ ...btnPrimary(false), background: "#1E1E30", color: "#8A8A9A", boxShadow: "none" }}
                        onClick={() => { setCurrentRace(null); setPhase("idle"); clearTimer(); }}>Отменить</button>
                      <button style={btnPrimary(false)} onClick={saveRace}>Сохранить →</button>
                    </div>
                  </>
                )}
              </>
            )}
          </>
        )}

        {/* ── LEADERBOARD TAB ── */}
        {tab === "leaderboard" && <Leaderboard races={races} />}

        {/* ── HISTORY TAB ── */}
        {tab === "history" && (
          <>
            {races.length > 0 && (
              <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
                <button style={{ ...btnPrimary(false), background: "#1E1E30", color: "#E07070", boxShadow: "none", fontSize: 11, padding: "8px 16px" }}
                  onClick={() => { if (confirm("Удалить всю историю гонок?")) clearAll(); }}>
                  Очистить историю
                </button>
              </div>
            )}
            {races.length === 0 ? (
              <div style={{ ...S.card, textAlign: "center", color: "#3A3A4A", padding: 40 }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>📭</div>
                <div style={{ fontSize: 13 }}>Пока нет завершённых гонок</div>
              </div>
            ) : races.map((race) => {
              const cat = CATEGORY_MAP[race.category];
              const sc = race.scores || {};
              const scoredE = Object.entries(sc).filter(([, s]) => s > 0);
              const best = scoredE.length > 0 ? Math.max(...scoredE.map(([, s]) => s)) : 0;
              const winners = best > 0 ? scoredE.filter(([, s]) => s === best).map(([id]) => getModel(id)) : [];
              return (
                <div key={race.id} style={S.card}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 10, color: "#5A5A6A", marginBottom: 4 }}>
                        {cat?.emoji} {cat?.label || race.category} · {new Date(race.timestamp).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                      </div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#EDEDF0" }}>{race.task}</div>
                    </div>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
                      {winners.map((w) => (
                        <div key={w.id || w.name} style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 10px", borderRadius: 6, background: `${w.color}15`, border: `1px solid ${w.color}30` }}>
                          <span style={{ fontSize: 12 }}>🏆</span>
                          <span style={{ fontSize: 11, fontWeight: 700, color: w.color }}>{w.name}</span>
                          <span style={{ fontSize: 11, color: "#5A5A6A" }}>{best}/10</span>
                        </div>
                      ))}
                      <button type="button" aria-label="Удалить гонку"
                        style={{ background: "transparent", border: "none", color: "#3A3A4A", cursor: "pointer", fontSize: 14, padding: "4px 6px", borderRadius: 4 }}
                        onClick={() => deleteRace(race.id)}>×</button>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
                    {race.runners.map((r) => {
                      const m = getModel(r.modelId);
                      const s = sc[r.modelId] || 0;
                      return (
                        <div key={r.modelId} style={{ fontSize: 11, padding: "3px 8px", borderRadius: 4, background: `${m.color}10`, color: m.color, fontWeight: 600 }}>
                          {m.icon} {s > 0 ? s + "/10" : "—"}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
