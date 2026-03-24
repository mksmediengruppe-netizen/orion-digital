// ORION Execution Simulation Engine
// Drives sequential step animation with realistic timing

import { useState, useCallback, useRef } from "react";
import type { Step, Message, AgentStatus, ViewerArtifact } from "@/lib/mockData";

// ─── Artifact payloads emitted during simulation ──────────────────────────────

const NGINX_CONF_ARTIFACT: ViewerArtifact = {
  id: "sim_nginx",
  title: "nginx.conf",
  type: "code",
  language: "nginx",
  createdAt: "14:29",
  size: "1.4 KB",
  content: `server {
    listen 80;
    listen [::]:80;
    server_name 185.22.xx.xx;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name 185.22.xx.xx;

    ssl_certificate /etc/letsencrypt/live/185.22.xx.xx/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/185.22.xx.xx/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    root /var/www/html/bitrix;
    index index.php index.html;

    location ~ \\.php$ {
        fastcgi_pass unix:/var/run/php/php8.2-fpm.sock;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    gzip on;
    gzip_types text/plain text/css application/json application/javascript;
}`,
  originalContent: `server {
    listen 80;
    server_name 185.22.xx.xx;

    root /var/www/html;
    index index.php index.html;

    location ~ \\.php$ {
        fastcgi_pass 127.0.0.1:9000;
        fastcgi_index index.php;
        include fastcgi_params;
    }
}`,
};

const README_ARTIFACT: ViewerArtifact = {
  id: "sim_readme",
  title: "README.md",
  type: "markdown",
  createdAt: "14:32",
  size: "1.8 KB",
  content: `# Bitrix CMS — Установка и настройка\n\n## Обзор\n\nПолная конфигурация для установки 1С-Битрикс на Ubuntu 22.04 с nginx, PHP 8.2 и MySQL 8.0.\n\n## Статус установки\n\n| Компонент | Версия | Статус |\n|-----------|--------|--------|\n| PHP | 8.2.10 | ✅ Установлен |\n| MySQL | 8.0.35 | ✅ Настроен |\n| Nginx | 1.24.0 | ✅ Настроен |\n| SSL | Let's Encrypt | ✅ Активен |\n\n## Доступ\n\n- **Сайт:** http://185.22.xx.xx/\n- **Админка:** http://185.22.xx.xx/bitrix/admin/\n- **Логин:** admin`,
};

const LANDING_HTML_ARTIFACT: ViewerArtifact = {
  id: "sim_landing",
  title: "landing.html",
  type: "html",
  createdAt: "14:33",
  size: "2.1 KB",
  content: `<!DOCTYPE html>\n<html lang="ru">\n<head>\n  <meta charset="UTF-8">\n  <title>Dream Avto — Автосалон</title>\n  <style>\n    body { font-family: system-ui, sans-serif; margin: 0; background: #f8f9fa; }\n    .hero { background: linear-gradient(135deg, #1a1a2e, #0f3460); color: white; padding: 60px 40px; text-align: center; }\n    .hero h1 { font-size: 42px; font-weight: 800; margin-bottom: 12px; }\n    .btn { display: inline-block; background: #e94560; color: white; padding: 14px 32px; border-radius: 8px; font-weight: 700; text-decoration: none; }\n    .cars { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; padding: 40px; }\n    .card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }\n    .price { font-size: 20px; font-weight: 800; color: #e94560; }\n  </style>\n</head>\n<body>\n  <div class="hero">\n    <h1>Dream Avto</h1>\n    <p>Лучшие автомобили по лучшим ценам</p>\n    <a href="#" class="btn">Смотреть каталог</a>\n  </div>\n  <div class="cars">\n    <div class="card"><h3>Toyota Camry 2024</h3><div class="price">2 890 000 ₽</div></div>\n    <div class="card"><h3>BMW X5 2023</h3><div class="price">7 450 000 ₽</div></div>\n    <div class="card"><h3>Mercedes C-Class</h3><div class="price">5 120 000 ₽</div></div>\n  </div>\n</body>\n</html>`,
};

export type SimulationState = "idle" | "running" | "done";

interface SimulationConfig {
  onMessagesChange: (msgs: Message[]) => void;
  onStatusChange: (status: AgentStatus) => void;
  onActiveStepChange: (stepId: string | undefined) => void;
  onRightPanelTabChange: (tab: string) => void;
}

// Full simulation scenario for chat c1
const SIMULATION_SCENARIO: {
  delay: number;
  action: (cfg: SimulationConfig, state: SimulationRef) => void;
}[] = [
  // 0 — user message appears
  {
    delay: 0,
    action: ({ onMessagesChange }, state) => {
      state.messages = [
        {
          id: "sim_user",
          role: "user",
          content: "Установи Bitrix CMS на сервер 185.22.xx.xx. Доступ по SSH есть. Нужно полностью рабочее окружение с настроенной базой данных и SSL.",
          timestamp: "14:27",
        },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 1 — agent starts thinking
  {
    delay: 800,
    action: ({ onStatusChange }) => {
      onStatusChange("thinking");
    },
  },
  // 2 — agent responds with plan
  {
    delay: 2200,
    action: ({ onMessagesChange, onStatusChange, onRightPanelTabChange }, state) => {
      onStatusChange("executing");
      onRightPanelTabChange("live");
      state.messages = [
        ...state.messages,
        {
          id: "sim_agent_plan",
          role: "agent",
          content: "Понял задачу. Начинаю установку Bitrix CMS на сервер. Сначала проверю текущее состояние сервера, затем установлю все необходимые компоненты.",
          timestamp: "14:27",
          plan: [
            "Проверить состояние сервера и версию PHP",
            "Загрузить и запустить установщик Bitrix",
            "Настроить базу данных MySQL",
            "Завершить установку через веб-интерфейс",
            "Настроить SSL сертификат",
            "Проверить работу через verifier",
          ],
          steps: [],
        },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 3 — step 1 starts (running)
  {
    delay: 1000,
    action: ({ onMessagesChange, onActiveStepChange, onRightPanelTabChange }, state) => {
      onRightPanelTabChange("steps");
      onActiveStepChange("sim_s1");
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps = [
        { id: "sim_s1", title: "Проверяю сервер", status: "running", tool: "SSH", startTime: "14:28:03", duration: "...", summary: "Подключаюсь по SSH, проверяю версию PHP и модули." },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 4 — step 1 done
  {
    delay: 2100,
    action: ({ onMessagesChange }, state) => {
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps![0] = {
        id: "sim_s1", title: "Проверил сервер", status: "success", tool: "SSH",
        startTime: "14:28:03", duration: "2.1s",
        summary: "Подключился по SSH, проверил версию PHP и доступные модули.",
        args: { host: "185.22.xx.xx", command: "php -v && php -m" },
        result: "PHP 8.2.10, модули: curl, gd, mbstring, mysqli ✓",
        goldenPath: true,
      };
      onMessagesChange([...state.messages]);
    },
  },
  // 5 — step 2 starts
  {
    delay: 600,
    action: ({ onMessagesChange, onActiveStepChange }, state) => {
      onActiveStepChange("sim_s2");
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps = [
        ...agentMsg.steps!,
        { id: "sim_s2", title: "Ищу документацию", status: "running", tool: "Browser", startTime: "14:28:06", duration: "...", summary: "Поиск актуальной версии Bitrix и требований." },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 6 — step 2 done
  {
    delay: 1400,
    action: ({ onMessagesChange }, state) => {
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps![1] = {
        id: "sim_s2", title: "Сделал web search", status: "success", tool: "Browser",
        startTime: "14:28:06", duration: "1.4s",
        summary: "Поиск актуальной версии Bitrix и требований к серверу.",
        args: { query: "Bitrix CMS 2024 server requirements PHP 8.2" },
        result: "Найдено: Bitrix 23.x поддерживает PHP 8.2, требует MySQL 8+",
      };
      onMessagesChange([...state.messages]);
    },
  },
  // 7 — step 3 starts
  {
    delay: 500,
    action: ({ onMessagesChange, onActiveStepChange }, state) => {
      onActiveStepChange("sim_s3");
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps = [
        ...agentMsg.steps!,
        { id: "sim_s3", title: "Открываю установщик", status: "running", tool: "Browser", startTime: "14:28:09", duration: "...", summary: "Загружаю установочный скрипт Bitrix." },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 8 — step 3 done
  {
    delay: 3200,
    action: ({ onMessagesChange }, state) => {
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps![2] = {
        id: "sim_s3", title: "Открыл bitrixsetup.php", status: "success", tool: "Browser",
        startTime: "14:28:09", duration: "3.2s",
        summary: "Загрузил установочный скрипт и открыл в браузере.",
        args: { url: "http://185.22.xx.xx/bitrixsetup.php" },
        result: "Страница установки загружена, все проверки пройдены",
      };
      onMessagesChange([...state.messages]);
    },
  },
  // 9 — step 4 starts (long)
  {
    delay: 700,
    action: ({ onMessagesChange, onActiveStepChange }, state) => {
      onActiveStepChange("sim_s4");
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps = [
        ...agentMsg.steps!,
        { id: "sim_s4", title: "Устанавливаю зависимости", status: "running", tool: "Terminal", startTime: "14:29:15", duration: "...", summary: "apt-get install php8.2-gd php8.2-curl php8.2-mbstring..." },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 10 — step 4 done + emit nginx.conf artifact
  {
    delay: 4500,
    action: ({ onMessagesChange }, state) => {
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps![3] = {
        id: "sim_s4", title: "Установил зависимости", status: "success", tool: "Terminal",
        startTime: "14:29:15", duration: "45.3s",
        summary: "Установил необходимые PHP-расширения и настроил php.ini.",
        args: { command: "apt-get install php8.2-gd php8.2-curl php8.2-mbstring" },
        result: "Все зависимости установлены успешно",
        goldenPath: true,
      };
      // Inject nginx.conf artifact into the agent plan message
      agentMsg.viewerArtifacts = [
        ...(agentMsg.viewerArtifacts ?? []),
        NGINX_CONF_ARTIFACT,
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 11 — system message: progress + emit README artifact
  {
    delay: 600,
    action: ({ onMessagesChange }, state) => {
      state.messages = [
        ...state.messages,
        {
          id: "sim_sys1",
          role: "system",
          content: "Агент выполняет задачу. Шаг 5 из 6: Проверка административной панели.",
          timestamp: "14:32",
          viewerArtifacts: [README_ARTIFACT],
        },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 12 — step 5 starts (running — stays running to show live state)
  {
    delay: 800,
    action: ({ onMessagesChange, onActiveStepChange, onRightPanelTabChange }, state) => {
      onActiveStepChange("sim_s5");
      onRightPanelTabChange("live");
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps = [
        ...agentMsg.steps!,
        { id: "sim_s5", title: "Проверяю админку", status: "running", tool: "Browser", startTime: "14:32:41", duration: "...", summary: "Открываю административную панель Bitrix для финальной проверки.", args: { url: "http://185.22.xx.xx/bitrix/admin/" } },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 13 — step 5 done
  {
    delay: 3000,
    action: ({ onMessagesChange, onActiveStepChange }, state) => {
      onActiveStepChange("sim_s5");
      const agentMsg = state.messages.find(m => m.id === "sim_agent_plan")!;
      agentMsg.steps![4] = {
        id: "sim_s5", title: "Проверил админку", status: "success", tool: "Browser",
        startTime: "14:32:41", duration: "3.8s",
        summary: "Административная панель Bitrix доступна и работает.",
        args: { url: "http://185.22.xx.xx/bitrix/admin/" },
        result: "HTTP 200 OK, панель загружена, авторизация работает ✓",
      };
      onMessagesChange([...state.messages]);
    },
  },
  // 14 — verifier runs
  {
    delay: 1000,
    action: ({ onMessagesChange, onRightPanelTabChange }, state) => {
      onRightPanelTabChange("verify");
      state.messages = [
        ...state.messages,
        {
          id: "sim_sys2",
          role: "system",
          content: "Verifier проверяет результат...",
          timestamp: "14:33",
        },
      ];
      onMessagesChange([...state.messages]);
    },
  },
  // 14b — needs_review transition (manual verification required)
  {
    delay: 1200,
    action: ({ onStatusChange }) => {
      onStatusChange("needs_review");
    },
  },
  // 15 — final agent message
  {
    delay: 1800,
    action: ({ onMessagesChange, onStatusChange, onActiveStepChange, onRightPanelTabChange }, state) => {
      onStatusChange("completed");
      onActiveStepChange(undefined);
      onRightPanelTabChange("result");
      // Remove verifier message, add final
      state.messages = state.messages.filter(m => m.id !== "sim_sys2");
      state.messages = [
        ...state.messages,
        {
          id: "sim_final",
          role: "agent",
          content: `## Bitrix CMS успешно установлен

:::success Задача выполнена — все 5 шагов завершены без ошибок:::

Сервер настроен и готов к работе. Ниже — итоговая сводка по установке.

### Что сделано

| Компонент | Версия | Статус |
|---|---|---|
| PHP | 8.2.10 | ✓ Установлен |
| MySQL | 8.0.35 | ✓ Настроен |
| Bitrix CMS | 23.850 | ✓ Установлен |
| nginx | 1.24.0 | ✓ Запущен |
| Composer | 2.6.5 | ✓ Установлен |

### Доступ к сайту

- **Сайт:** [http://185.22.xx.xx/](http://185.22.xx.xx/)
- **Админка:** [http://185.22.xx.xx/bitrix/admin/](http://185.22.xx.xx/bitrix/admin/)
- **Логин:** admin / *сохранён в отчёте*

### Конфигурация nginx

\`\`\`nginx
server {
    listen 80;
    server_name 185.22.xx.xx;
    root /var/www/bitrix;
    index index.php;

    location ~ \.php$ {
        fastcgi_pass unix:/run/php/php8.2-fpm.sock;
        include fastcgi_params;
    }
}
\`\`\`

### Следующие шаги

1. Настроить SSL сертификат через Let's Encrypt
2. Изменить пароль администратора
3. Настроить резервное копирование базы данных

> **Рекомендация:** запустите задачу «Настройка SSL» — это займёт около 2 минут и сделает сайт доступным по HTTPS.`,
          timestamp: "14:33",
          artifact: {
            id: "art_report",
            name: "installation_report.txt",
            type: "document",
            size: "14 KB",
            createdAt: "14:33",
            preview: "Bitrix CMS installation completed successfully...",
          },
          viewerArtifacts: [LANDING_HTML_ARTIFACT],
        },
      ];
      onMessagesChange([...state.messages]);
    },
  },
];

interface SimulationRef {
  messages: Message[];
}

export function useExecutionSimulation(config: SimulationConfig) {
  const [simState, setSimState] = useState<SimulationState>("idle");
  const timeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const stateRef = useRef<SimulationRef>({ messages: [] });

  const clearTimeouts = useCallback(() => {
    timeoutsRef.current.forEach(clearTimeout);
    timeoutsRef.current = [];
  }, []);

  const start = useCallback(() => {
    clearTimeouts();
    stateRef.current = { messages: [] };
    setSimState("running");

    let cumulativeDelay = 0;
    SIMULATION_SCENARIO.forEach((step, _i) => {
      cumulativeDelay += step.delay;
      const t = setTimeout(() => {
        step.action(config, stateRef.current);
      }, cumulativeDelay);
      timeoutsRef.current.push(t);
    });

    // Mark done after all steps
    const totalDelay = SIMULATION_SCENARIO.reduce((acc, s) => acc + s.delay, 0) + 500;
    const doneT = setTimeout(() => setSimState("done"), totalDelay);
    timeoutsRef.current.push(doneT);
  }, [config, clearTimeouts]);

  const reset = useCallback(() => {
    clearTimeouts();
    setSimState("idle");
  }, [clearTimeouts]);

  return { simState, start, reset };
}
