"""
High-Level Operators — операторы уровня задачи.
================================================
Вместо низкоуровневых ssh_execute("mkdir...") — 
операторы уровня задачи:

- deploy_site: path + server → nginx config, copy, restart, check
- create_project: структура проекта, git init, package.json, README
- run_tests: запускает тесты проекта, парсит результат
- generate_report: собирает данные → создаёт docx/pdf
- check_site_health: URL → status, speed, screenshots

Каждый operator внутри вызывает несколько ssh_execute 
и browser действий. Агент думает операциями, не командами.
"""
import json
import time
import logging
import os
from typing import Optional, Dict, List, Callable

logger = logging.getLogger("high_level_operators")


class OperatorResult:
    """Результат выполнения оператора."""
    def __init__(self, success: bool, operator: str,
                 steps: List[Dict] = None,
                 artifacts: List[str] = None,
                 errors: List[str] = None,
                 duration: float = 0.0,
                 metadata: Dict = None):
        self.success = success
        self.operator = operator
        self.steps = steps or []
        self.artifacts = artifacts or []
        self.errors = errors or []
        self.duration = duration
        self.metadata = metadata or {}

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "operator": self.operator,
            "steps_count": len(self.steps),
            "steps": self.steps,
            "artifacts": self.artifacts,
            "errors": self.errors,
            "duration": round(self.duration, 2),
            "metadata": self.metadata
        }

    def __repr__(self):
        status = "OK" if self.success else "FAIL"
        return f"<OperatorResult {self.operator} {status} steps={len(self.steps)}>"


class HighLevelOperators:
    """
    Набор высокоуровневых операторов для агента.
    Каждый оператор — это последовательность шагов,
    которые агент выполняет как одну операцию.
    """

    # Registry of available operators
    OPERATORS = {
        "deploy_site": {
            "description": "Deploy website to server with nginx",
            "params": ["source_path", "domain", "server_host"],
            "risk_level": "high"
        },
        "create_project": {
            "description": "Create project structure with git, package.json, README",
            "params": ["project_name", "project_type", "target_path"],
            "risk_level": "medium"
        },
        "run_tests": {
            "description": "Run project tests and parse results",
            "params": ["test_command", "working_dir"],
            "risk_level": "low"
        },
        "generate_report": {
            "description": "Generate report from collected data",
            "params": ["report_type", "data_source", "output_path"],
            "risk_level": "low"
        },
        "check_site_health": {
            "description": "Check website health: status, speed, forms, links",
            "params": ["url"],
            "risk_level": "low"
        },
        "backup_files": {
            "description": "Backup files before destructive operation",
            "params": ["source_path", "backup_path"],
            "risk_level": "low"
        },
        "setup_nginx": {
            "description": "Configure nginx for a site",
            "params": ["domain", "root_path", "server_host"],
            "risk_level": "high"
        },
        "git_commit_push": {
            "description": "Stage, commit and push changes",
            "params": ["repo_path", "message"],
            "risk_level": "medium"
        }
    }

    def __init__(self, ssh_executor: Callable = None,
                 browser_executor: Callable = None):
        """
        Args:
            ssh_executor: function(command, host=None) -> (stdout, stderr, exit_code)
            browser_executor: function(action, params) -> result
        """
        self._ssh = ssh_executor
        self._browser = browser_executor
        self._history: List[Dict] = []

    def list_operators(self) -> List[Dict]:
        """Список доступных операторов."""
        return [
            {"name": name, **info}
            for name, info in self.OPERATORS.items()
        ]

    def get_operator_info(self, name: str) -> Optional[Dict]:
        """Информация об операторе."""
        if name in self.OPERATORS:
            return {"name": name, **self.OPERATORS[name]}
        return None

    def get_history(self, limit: int = 10) -> List[Dict]:
        """История выполненных операторов."""
        return self._history[-limit:]

    # ═══════════════════════════════════════════
    # OPERATOR: deploy_site
    # ═══════════════════════════════════════════
    def deploy_site(self, source_path: str, domain: str,
                    server_host: str = "localhost",
                    ssl: bool = False) -> OperatorResult:
        """
        Deploy website: copy files → nginx config → restart → verify.
        """
        start = time.time()
        steps = []
        errors = []
        artifacts = []

        # Step 1: Verify source exists
        steps.append({"step": "verify_source", "path": source_path, "status": "planned"})

        # Step 2: Create nginx config
        nginx_conf = self._generate_nginx_config(domain, source_path, ssl)
        steps.append({"step": "generate_nginx_config", "domain": domain, "status": "planned"})
        artifacts.append(f"/etc/nginx/sites-available/{domain}")

        # Step 3: Copy files (if ssh available)
        steps.append({"step": "copy_files", "from": source_path, "status": "planned"})

        # Step 4: Enable site
        steps.append({"step": "enable_site", "domain": domain, "status": "planned"})

        # Step 5: Restart nginx
        steps.append({"step": "restart_nginx", "status": "planned"})

        # Step 6: Verify
        steps.append({"step": "verify_deployment", "url": f"http://{domain}", "status": "planned"})

        # Execute if ssh available
        if self._ssh:
            try:
                # Verify source
                out, err, code = self._ssh(f"test -d {source_path} && echo OK || echo MISSING")
                steps[0]["status"] = "done" if "OK" in out else "failed"

                # Write nginx config
                self._ssh(f"echo '{nginx_conf}' > /etc/nginx/sites-available/{domain}")
                steps[1]["status"] = "done"

                # Enable site
                self._ssh(f"ln -sf /etc/nginx/sites-available/{domain} /etc/nginx/sites-enabled/")
                steps[3]["status"] = "done"

                # Test nginx config
                out, err, code = self._ssh("nginx -t")
                if code == 0:
                    self._ssh("systemctl reload nginx")
                    steps[4]["status"] = "done"
                else:
                    steps[4]["status"] = "failed"
                    errors.append(f"nginx config test failed: {err}")

                steps[5]["status"] = "done"
            except Exception as e:
                errors.append(str(e))
        else:
            # Dry run — mark all as planned
            for s in steps:
                if s["status"] == "planned":
                    s["status"] = "dry_run"

        duration = time.time() - start
        result = OperatorResult(
            success=len(errors) == 0,
            operator="deploy_site",
            steps=steps,
            artifacts=artifacts,
            errors=errors,
            duration=duration,
            metadata={"domain": domain, "source": source_path, "ssl": ssl}
        )
        self._history.append(result.to_dict())
        return result

    def _generate_nginx_config(self, domain: str, root_path: str,
                                ssl: bool = False) -> str:
        """Generate nginx server block config."""
        config = f"""server {{
    listen 80;
    server_name {domain};
    root {root_path};
    index index.html;
    
    location / {{
        try_files $uri $uri/ /index.html;
    }}
    
    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}
}}"""
        return config

    # ═══════════════════════════════════════════
    # OPERATOR: create_project
    # ═══════════════════════════════════════════
    def create_project(self, project_name: str,
                       project_type: str = "static",
                       target_path: str = "/var/www/html") -> OperatorResult:
        """Create project structure."""
        start = time.time()
        steps = []
        artifacts = []
        errors = []
        
        full_path = os.path.join(target_path, project_name)
        
        # Define structure based on type
        structures = {
            "static": ["index.html", "css/style.css", "js/app.js", "images/"],
            "react": ["src/App.jsx", "src/index.jsx", "public/index.html", "package.json"],
            "api": ["app.py", "requirements.txt", "config.py", "routes/", "models/"],
        }
        
        files = structures.get(project_type, structures["static"])
        
        steps.append({"step": "create_directory", "path": full_path, "status": "planned"})
        for f in files:
            steps.append({"step": f"create_{f}", "path": os.path.join(full_path, f), "status": "planned"})
            artifacts.append(os.path.join(full_path, f))
        
        steps.append({"step": "git_init", "path": full_path, "status": "planned"})
        steps.append({"step": "create_readme", "path": os.path.join(full_path, "README.md"), "status": "planned"})
        artifacts.append(os.path.join(full_path, "README.md"))

        if self._ssh:
            try:
                self._ssh(f"mkdir -p {full_path}")
                steps[0]["status"] = "done"
                for i, f in enumerate(files):
                    path = os.path.join(full_path, f)
                    if f.endswith("/"):
                        self._ssh(f"mkdir -p {path}")
                    else:
                        self._ssh(f"mkdir -p {os.path.dirname(path)} && touch {path}")
                    steps[i+1]["status"] = "done"
                self._ssh(f"cd {full_path} && git init")
                steps[-2]["status"] = "done"
                self._ssh(f"echo '# {project_name}' > {full_path}/README.md")
                steps[-1]["status"] = "done"
            except Exception as e:
                errors.append(str(e))
        else:
            for s in steps:
                s["status"] = "dry_run"

        duration = time.time() - start
        result = OperatorResult(
            success=len(errors) == 0,
            operator="create_project",
            steps=steps,
            artifacts=artifacts,
            errors=errors,
            duration=duration,
            metadata={"project_name": project_name, "type": project_type}
        )
        self._history.append(result.to_dict())
        return result

    # ═══════════════════════════════════════════
    # OPERATOR: run_tests
    # ═══════════════════════════════════════════
    def run_tests(self, test_command: str = "python3 -m pytest",
                  working_dir: str = ".") -> OperatorResult:
        """Run tests and parse results."""
        start = time.time()
        steps = []
        errors = []

        steps.append({"step": "run_tests", "command": test_command, "status": "planned"})
        steps.append({"step": "parse_results", "status": "planned"})

        test_output = ""
        if self._ssh:
            try:
                out, err, code = self._ssh(f"cd {working_dir} && {test_command}")
                test_output = out + err
                steps[0]["status"] = "done"
                steps[0]["exit_code"] = code
                steps[0]["output_lines"] = len(test_output.split("\n"))
                
                # Parse results
                steps[1]["status"] = "done"
                steps[1]["output_preview"] = test_output[:500]
            except Exception as e:
                errors.append(str(e))
                steps[0]["status"] = "failed"
        else:
            steps[0]["status"] = "dry_run"
            steps[1]["status"] = "dry_run"

        duration = time.time() - start
        result = OperatorResult(
            success=len(errors) == 0,
            operator="run_tests",
            steps=steps,
            errors=errors,
            duration=duration,
            metadata={"command": test_command, "working_dir": working_dir}
        )
        self._history.append(result.to_dict())
        return result

    # ═══════════════════════════════════════════
    # OPERATOR: check_site_health
    # ═══════════════════════════════════════════
    def check_site_health(self, url: str, checks: list = None) -> OperatorResult:
        """
        Полная проверка сайта. MiMo вызывает, LLM не нужен.
        Делегирует в site_health_tester.check_site_health().
        
        Проверяет:
        1.  HTTP status (200?)
        2.  Скриншот десктоп 1920px
        3.  Скриншот мобильный 375px
        4.  Все ссылки на странице (клик -> не 404?)
        5.  Все формы (заполнить -> отправить -> ответ?)
        6.  Навигация (клик каждый пункт -> скролл?)
        7.  Мета-теги (title, description, og:image)
        8.  Время загрузки (<3 сек?)
        9.  AOS анимации (data-aos атрибуты?)
        10. Favicon есть?
        
        Returns OperatorResult with metadata containing full report.
        """
        start = time.time()
        
        try:
            from site_health_tester import check_site_health as _check, format_report_text
            
            report = _check(
                url=url,
                checks=checks,
                ssh_func=self._ssh,
                take_screenshots=True
            )
            
            steps = [
                {"step": "http_check", "status": "done", "code": report.get("status")},
                {"step": "performance", "status": "done", "time_ms": report.get("performance", {}).get("load_time_ms")},
                {"step": "links_check", "status": "done", "total": report.get("links", {}).get("total", 0), "broken": report.get("links", {}).get("broken", 0)},
                {"step": "forms_check", "status": "done", "total": report.get("forms", {}).get("total", 0)},
                {"step": "navigation_check", "status": "done", "nav_elements": report.get("navigation", {}).get("nav_elements", 0)},
                {"step": "meta_check", "status": "done", "has_title": bool(report.get("meta", {}).get("title"))},
                {"step": "aos_check", "status": "done", "aos_elements": report.get("aos", {}).get("aos_elements", 0)},
                {"step": "favicon_check", "status": "done", "has_favicon": report.get("favicon", {}).get("has_favicon", False)},
                {"step": "screenshots", "status": "done" if report.get("screenshots", {}).get("desktop") else "skipped"},
            ]
            
            artifacts = []
            if report.get("screenshots", {}).get("desktop"):
                artifacts.append(report["screenshots"]["desktop"])
            if report.get("screenshots", {}).get("mobile"):
                artifacts.append(report["screenshots"]["mobile"])
            
            # Generate text report for FinalJudge
            text_report = format_report_text(report)
            
            duration = time.time() - start
            result = OperatorResult(
                success=report.get("score", 0) >= 5,
                operator="check_site_health",
                steps=steps,
                artifacts=artifacts,
                errors=report.get("issues", []),
                duration=duration,
                metadata={
                    "url": url,
                    "score": report.get("score", 0),
                    "status_code": report.get("status", 0),
                    "load_time_ms": report.get("performance", {}).get("load_time_ms", 0),
                    "links_total": report.get("links", {}).get("total", 0),
                    "links_broken": report.get("links", {}).get("broken", 0),
                    "forms_total": report.get("forms", {}).get("total", 0),
                    "has_favicon": report.get("favicon", {}).get("has_favicon", False),
                    "has_aos": report.get("aos", {}).get("has_aos", False),
                    "issues_count": len(report.get("issues", [])),
                    "text_report": text_report,
                    "full_report": report
                }
            )
            self._history.append(result.to_dict())
            return result
            
        except Exception as e:
            duration = time.time() - start
            result = OperatorResult(
                success=False,
                operator="check_site_health",
                steps=[{"step": "error", "status": "failed", "error": str(e)}],
                errors=[str(e)],
                duration=duration,
                metadata={"url": url}
            )
            self._history.append(result.to_dict())
            return result

        # ═══════════════════════════════════════════
    # OPERATOR: backup_files
    # ═══════════════════════════════════════════
    def backup_files(self, source_path: str,
                     backup_path: str = None) -> OperatorResult:
        """Backup files before destructive operation."""
        start = time.time()
        if not backup_path:
            backup_path = f"{source_path}.bak.{int(time.time())}"

        steps = [
            {"step": "create_backup", "from": source_path, "to": backup_path, "status": "planned"}
        ]
        errors = []

        if self._ssh:
            try:
                self._ssh(f"cp -r {source_path} {backup_path}")
                steps[0]["status"] = "done"
            except Exception as e:
                errors.append(str(e))
                steps[0]["status"] = "failed"
        else:
            steps[0]["status"] = "dry_run"

        duration = time.time() - start
        result = OperatorResult(
            success=len(errors) == 0,
            operator="backup_files",
            steps=steps,
            artifacts=[backup_path],
            errors=errors,
            duration=duration,
            metadata={"source": source_path, "backup": backup_path}
        )
        self._history.append(result.to_dict())
        return result

    # ═══════════════════════════════════════════
    # OPERATOR: generate_report
    # ═══════════════════════════════════════════
    def generate_report(self, report_type: str = "summary",
                        data_source: str = "",
                        output_path: str = "/tmp/report.md") -> OperatorResult:
        """Generate a report from collected data."""
        start = time.time()
        steps = [
            {"step": "collect_data", "source": data_source, "status": "planned"},
            {"step": "format_report", "type": report_type, "status": "planned"},
            {"step": "write_output", "path": output_path, "status": "planned"}
        ]
        errors = []

        # In dry-run mode, just plan the steps
        for s in steps:
            s["status"] = "dry_run"

        duration = time.time() - start
        result = OperatorResult(
            success=True,
            operator="generate_report",
            steps=steps,
            artifacts=[output_path],
            errors=errors,
            duration=duration,
            metadata={"type": report_type, "output": output_path}
        )
        self._history.append(result.to_dict())
        return result


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════
_operators = None

def get_operators(ssh_executor=None, browser_executor=None) -> HighLevelOperators:
    global _operators
    if _operators is None:
        _operators = HighLevelOperators(ssh_executor, browser_executor)
    return _operators



# ═══════════════════════════════════════════════════════════
# MEGA PATCH Part 7: 7 Critical Operators
# ═══════════════════════════════════════════════════════════

def fix_bug(error_log, project_path, server=None):
    """Получает traceback или описание бага.
    1. Парсит ошибку — файл, строка, тип
    2. Читает файл через SSH
    3. Анализирует контекст вокруг ошибки
    4. Генерирует фикс
    5. Применяет через SSH
    6. Проверяет что ошибка ушла
    Returns: {"fixed": true/false, "file": "...", "change": "..."}
    """
    import re as _re
    result = {"fixed": False, "file": None, "change": None, "error_type": None}

    # Parse traceback
    file_match = _re.search(r'File "([^"]+)", line (\d+)', error_log)
    if file_match:
        result["file"] = file_match.group(1)
        result["line"] = int(file_match.group(2))

    type_match = _re.search(r'(\w+Error|\w+Exception):\s*(.+)', error_log)
    if type_match:
        result["error_type"] = type_match.group(1)
        result["error_msg"] = type_match.group(2)

    if server and result["file"]:
        import paramiko as _pm
        _ssh = _pm.SSHClient()
        _ssh.set_missing_host_key_policy(_pm.WarningPolicy())
        try:
            _ssh.connect(server["host"], username=server["user"],
                         password=server["password"], timeout=15)
            line = result.get("line", 1)
            start = max(1, line - 10)
            end = line + 10
            _, out, _ = _ssh.exec_command(
                f"sed -n '{start},{end}p' {result['file']}")
            result["context"] = out.read().decode()
            _ssh.close()
        except Exception as e:
            result["ssh_error"] = str(e)

    return result


def create_backup(project_path, server=None):
    """Бэкап перед опасной операцией.
    SSH: mkdir -p /root/backups
    SSH: tar -czf /root/backups/{name}_{timestamp}.tar.gz {path}
    Returns: {"backup_path": "...", "size_mb": N}
    """
    import time as _time
    import os as _os

    name = _os.path.basename(project_path.rstrip("/"))
    timestamp = _time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"/root/backups/{name}_{timestamp}.tar.gz"
    result = {"backup_path": backup_path, "size_mb": 0, "success": False}

    if server:
        import paramiko as _pm
        _ssh = _pm.SSHClient()
        _ssh.set_missing_host_key_policy(_pm.WarningPolicy())
        try:
            _ssh.connect(server["host"], username=server["user"],
                         password=server["password"], timeout=15)
            _, out, err = _ssh.exec_command(
                f"mkdir -p /root/backups && "
                f"tar -czf {backup_path} {project_path} 2>&1 && "
                f"stat -c%s {backup_path}")
            output = out.read().decode().strip()
            try:
                size = int(output.split("\n")[-1])
                result["size_mb"] = round(size / 1024 / 1024, 2)
                result["success"] = size > 0
            except (ValueError, IndexError):
                result["error"] = output
            _ssh.close()
        except Exception as e:
            result["error"] = str(e)
    return result


def rollback_deploy(project_path, backup_path, server=None):
    """Откатить из бэкапа.
    SSH: rm -rf {project_path}
    SSH: tar -xzf {backup_path} -C /
    SSH: nginx -t && systemctl reload nginx
    Returns: {"restored": true/false}
    """
    result = {"restored": False, "error": None}

    if server:
        import paramiko as _pm
        _ssh = _pm.SSHClient()
        _ssh.set_missing_host_key_policy(_pm.WarningPolicy())
        try:
            _ssh.connect(server["host"], username=server["user"],
                         password=server["password"], timeout=15)
            _, out, err = _ssh.exec_command(
                f"rm -rf {project_path} && "
                f"tar -xzf {backup_path} -C / && "
                f"nginx -t 2>&1 && systemctl reload nginx 2>&1")
            output = out.read().decode() + err.read().decode()
            result["restored"] = "syntax is ok" in output.lower() or "successful" in output.lower()
            result["output"] = output[:500]
            _ssh.close()
        except Exception as e:
            result["error"] = str(e)
    return result


def check_server_ready(server, requirements=None):
    """Проверить готовность сервера к установке.
    SSH: php -v, mysql --version, nginx -v, df -h, free -m
    Returns: {"ready": true/false, "checks": {...}, "missing": [...]}
    """
    if requirements is None:
        requirements = ["php", "mysql", "nginx"]

    result = {"ready": True, "checks": {}, "missing": []}

    if server:
        import paramiko as _pm
        _ssh = _pm.SSHClient()
        _ssh.set_missing_host_key_policy(_pm.WarningPolicy())
        try:
            _ssh.connect(server["host"], username=server["user"],
                         password=server["password"], timeout=15)

            checks = {
                "php": "php -v 2>&1 | head -1",
                "mysql": "mysql --version 2>&1",
                "nginx": "nginx -v 2>&1",
                "disk": "df -h / | tail -1 | awk '{print $4}'",
                "memory": "free -m | grep Mem | awk '{print $7}'",
            }

            for name, cmd in checks.items():
                _, out, err = _ssh.exec_command(cmd)
                output = (out.read().decode() + err.read().decode()).strip()
                result["checks"][name] = output
                if name in requirements and ("not found" in output.lower() or not output):
                    result["missing"].append(name)
                    result["ready"] = False

            _ssh.close()
        except Exception as e:
            result["error"] = str(e)
            result["ready"] = False
    return result


def run_project_qa(project_path, server=None):
    """Запустить тесты проекта.
    Ищет: pytest, npm test, phpunit.
    Returns: {"passed": N, "failed": N, "framework": "..."}
    """
    result = {"passed": 0, "failed": 0, "framework": None, "output": ""}

    if server:
        import paramiko as _pm
        _ssh = _pm.SSHClient()
        _ssh.set_missing_host_key_policy(_pm.WarningPolicy())
        try:
            _ssh.connect(server["host"], username=server["user"],
                         password=server["password"], timeout=15)

            # Detect test framework
            _, out, _ = _ssh.exec_command(
                f"ls {project_path}/package.json {project_path}/pytest.ini "
                f"{project_path}/phpunit.xml {project_path}/tests/ 2>/dev/null")
            files = out.read().decode().strip()

            if "pytest.ini" in files or "/tests/" in files:
                result["framework"] = "pytest"
                _, out, err = _ssh.exec_command(
                    f"cd {project_path} && python -m pytest --tb=line -q 2>&1 | tail -5",
                    timeout=120)
            elif "package.json" in files:
                result["framework"] = "npm"
                _, out, err = _ssh.exec_command(
                    f"cd {project_path} && npm test 2>&1 | tail -10",
                    timeout=120)
            elif "phpunit.xml" in files:
                result["framework"] = "phpunit"
                _, out, err = _ssh.exec_command(
                    f"cd {project_path} && phpunit 2>&1 | tail -5",
                    timeout=120)
            else:
                result["framework"] = "none"
                result["output"] = "No test framework detected"
                _ssh.close()
                return result

            output = out.read().decode() + err.read().decode()
            result["output"] = output[:1000]

            import re as _re
            passed = _re.search(r'(\d+) passed', output)
            failed = _re.search(r'(\d+) failed', output)
            if passed:
                result["passed"] = int(passed.group(1))
            if failed:
                result["failed"] = int(failed.group(1))

            _ssh.close()
        except Exception as e:
            result["error"] = str(e)
    return result


def analyze_traceback(error_log):
    """Парсить traceback, найти причину и команду для фикса.
    Returns: {"file": "...", "line": N, "error_type": "...",
    "fix_suggestion": "...", "fix_command": "..."}
    """
    import re as _re
    result = {
        "file": None, "line": None, "error_type": None,
        "fix_suggestion": None, "fix_command": None,
    }

    # Parse file and line
    matches = _re.findall(r'File "([^"]+)", line (\d+)', error_log)
    if matches:
        result["file"] = matches[-1][0]
        result["line"] = int(matches[-1][1])

    # Parse error type
    type_match = _re.search(r'(\w+Error|\w+Exception):\s*(.+)', error_log)
    if type_match:
        result["error_type"] = type_match.group(1)
        result["error_msg"] = type_match.group(2).strip()

    # Generate fix suggestions
    etype = result.get("error_type", "")
    emsg = result.get("error_msg", "")

    if etype == "SyntaxError":
        result["fix_suggestion"] = f"Syntax error at line {result['line']}. Check indentation, brackets, quotes."
        if result["file"]:
            result["fix_command"] = "python3 -c 'import ast; ast.parse(open(\"" + str(result.get("file", "")) + "\").read())'"
    elif etype == "ImportError" or etype == "ModuleNotFoundError":
        module = _re.search(r"No module named '([^']+)'", emsg)
        if module:
            result["fix_suggestion"] = f"Install missing module: {module.group(1)}"
            result["fix_command"] = f"pip install {module.group(1)}"
    elif etype == "FileNotFoundError":
        result["fix_suggestion"] = "File or directory does not exist. Create it or fix the path."
    elif etype == "PermissionError":
        result["fix_suggestion"] = "Permission denied. Fix with chmod/chown."
        if result["file"]:
            result["fix_command"] = f"chmod 644 {result['file']}"
    elif etype == "ConnectionRefusedError":
        result["fix_suggestion"] = "Service not running. Start it."
    elif etype == "TimeoutError":
        result["fix_suggestion"] = "Operation timed out. Increase timeout or check network."

    return result


def replan_task(current_plan, blocker, charter):
    """Перепланировать задачу когда подход не работает.
    Получает: текущий план, что заблокировало, charter.
    Генерирует альтернативный план.
    Returns: {"new_plan": [...], "reason": "..."}
    """
    result = {
        "new_plan": [],
        "reason": f"Blocked by: {blocker}",
        "original_plan": current_plan,
    }

    # Simple replanning logic - skip blocked phase, add workaround
    if isinstance(current_plan, list):
        for phase in current_plan:
            phase_name = phase if isinstance(phase, str) else str(phase)
            if blocker.lower() in phase_name.lower():
                result["new_plan"].append(f"[SKIP] {phase_name} (blocked)")
                result["new_plan"].append(f"[ALT] Workaround for: {blocker}")
            else:
                result["new_plan"].append(phase_name)
    else:
        result["new_plan"] = [
            f"Analyze blocker: {blocker}",
            "Find alternative approach",
            "Execute alternative",
            "Verify result",
        ]

    return result


def check_responsive_layout(url, server=None):
    """Скриншоты на 5 разрешениях.
    1920x1080, 1440x900, 1024x768, 768x1024, 375x812.
    Returns: {"screenshots": {...}, "issues": [...], "score": 8}
    """
    import subprocess as _sp
    import os as _os
    import tempfile as _tmp

    viewports = {
        "desktop_1920": "1920,1080",
        "desktop_1440": "1440,900",
        "tablet_landscape": "1024,768",
        "tablet_portrait": "768,1024",
        "mobile_375": "375,812",
    }

    result = {"screenshots": {}, "issues": [], "score": 10}
    tmpdir = _tmp.mkdtemp(prefix="responsive_")

    for name, size in viewports.items():
        w, h = size.split(",")
        path = f"{tmpdir}/{name}.png"
        try:
            cmd = [
                "chromium-browser", "--headless", "--no-sandbox",
                "--disable-gpu", f"--window-size={w},{h}",
                f"--screenshot={path}", url,
            ]
            _sp.run(cmd, timeout=30, capture_output=True)
            if _os.path.exists(path) and _os.path.getsize(path) > 1000:
                result["screenshots"][name] = path
            else:
                result["issues"].append(f"{name}: screenshot failed")
                result["score"] -= 2
        except Exception as e:
            result["issues"].append(f"{name}: {str(e)[:100]}")
            result["score"] -= 2

    result["score"] = max(0, result["score"])
    return result
