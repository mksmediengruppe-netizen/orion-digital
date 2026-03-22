"""
Landing Builder -- builds a landing page from blueprint.
High-level operator that orchestrates photo generation, HTML/CSS/JS creation, and deployment.
ULTIMATE PATCH Part H2.
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("build_landing")


class LandingBuilder:

    def __init__(self, ssh_executor=None, image_generator=None, llm_client=None):
        self._ssh = ssh_executor
        self._image_gen = image_generator
        self._llm = llm_client

    def build(self, blueprint: dict, server_config: dict) -> dict:
        """
        Full build cycle:
        1. Generate AI photos (from blueprint.photos_needed)
        2. Generate HTML by sections
        3. Generate CSS
        4. Generate JS (animations, accordion, forms)
        5. Generate PHP handler
        6. Generate privacy.html
        7. Assemble into folder
        8. Deploy to server
        9. Verify result
        """
        result = {
            "success": False,
            "photos_generated": 0,
            "html_size": 0,
            "deployed": False,
            "verified": False,
            "url": None,
            "errors": []
        }

        server = server_config
        deploy = blueprint.get("deploy", {})
        path = deploy.get("path", "/var/www/html/site/")

        try:
            # 1. Prepare server directory
            logger.info("Step 1: Preparing server directory")
            self._ssh.execute(f"mkdir -p {path}/images", server)
            self._ssh.execute(f"chown -R www-data:www-data {path}", server)

            # 2. Generate photos
            logger.info("Step 2: Generating photos")
            photos = blueprint.get("photos_needed", [])
            for i, photo in enumerate(photos):
                try:
                    img_result = self._image_gen.generate(
                        prompt=photo.get("prompt", "professional photo"),
                        style=photo.get("style", "professional")
                    )
                    if img_result and img_result.get("url"):
                        filename = f"{photo.get('section', f'photo_{i}')}.png"
                        self._ssh.execute(
                            f"wget -q '{img_result['url']}' -O {path}/images/{filename}",
                            server
                        )
                        result["photos_generated"] += 1
                except Exception as e:
                    logger.warning(f"Photo {i} failed: {e}")
                    result["errors"].append(f"Photo {photo.get('section')}: {e}")

            # 3. Generate HTML
            logger.info("Step 3: Generating HTML")
            html = self._generate_html(blueprint)
            result["html_size"] = len(html)

            # 4. Generate CSS (inline in HTML for simplicity)
            # 5. Generate JS (inline in HTML)

            # 6. Deploy HTML
            logger.info("Step 6: Deploying HTML")
            self._ssh.execute(
                f"cat > {path}/index.html << 'HTMLEOF'\n{html}\nHTMLEOF",
                server
            )

            # 7. Generate PHP handler
            if blueprint.get("technical", {}).get("php_handler"):
                logger.info("Step 7: Creating PHP handler")
                forms = blueprint.get("forms", [])
                email = forms[0].get("email", "admin@example.com") if forms else "admin@example.com"
                self._create_php_handler(path, email, server)

            # 8. Generate privacy.html
            logger.info("Step 8: Creating privacy page")
            self._create_privacy_page(path, blueprint, server)

            # 9. Setup nginx if needed
            if deploy.get("nginx"):
                logger.info("Step 9: Configuring nginx")
                self._setup_nginx(path, blueprint, server)

            # 10. Verify
            logger.info("Step 10: Verifying deployment")
            site_url = f"http://{server.get('host')}"
            site_name = path.rstrip('/').split('/')[-1]
            full_url = f"{site_url}/{site_name}/"

            check = self._ssh.execute(f"curl -sI {full_url} | head -1", server)
            if "200" in str(check.get("output", "")):
                result["deployed"] = True
                result["verified"] = True
                result["url"] = full_url

            result["success"] = result["deployed"]

        except Exception as e:
            logger.error(f"Build failed: {e}")
            result["errors"].append(str(e))

        return result

    def _generate_html(self, blueprint: dict) -> str:
        """Generate HTML from blueprint using LLM or template."""
        if self._llm:
            return self._generate_html_via_llm(blueprint)
        return self._generate_html_template(blueprint)

    def _generate_html_via_llm(self, blueprint: dict) -> str:
        """Use LLM to generate full HTML."""
        import json
        prompt = f"""Generate a complete, production-ready HTML landing page based on this blueprint:
{json.dumps(blueprint, indent=2, ensure_ascii=False)}

Requirements:
- Single HTML file with inline CSS and JS
- Use {blueprint.get('technical', {}).get('framework', 'tailwind')} CSS
- Responsive design (mobile-first)
- AOS animations
- Contact form with validation
- All sections from blueprint
- Professional design with colors from blueprint.design
- Russian language content
Return ONLY the HTML code, no markdown."""

        try:
            response = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model="gpt54"
            )
            return response
        except:
            return self._generate_html_template(blueprint)

    def _generate_html_template(self, blueprint: dict) -> str:
        """Fallback template-based HTML generation."""
        design = blueprint.get("design", {})
        sections_html = ""
        for section in blueprint.get("sections", []):
            sections_html += f"""
<section id="{section['id']}" class="py-16 px-4">
    <div class="max-w-6xl mx-auto">
        <h2 class="text-3xl font-bold text-center mb-8">{section.get('title', '')}</h2>
        <p class="text-center text-gray-600">{section.get('content', '')}</p>
    </div>
</section>"""

        return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{blueprint.get('site_name', 'Site')}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://unpkg.com/aos@2.3.1/dist/aos.css" rel="stylesheet">
</head>
<body class="bg-{design.get('background', 'white')}">
{sections_html}
<script src="https://unpkg.com/aos@2.3.1/dist/aos.js"></script>
<script>AOS.init();</script>
</body>
</html>"""

    def _create_php_handler(self, path, email, server):
        """Create send.php handler."""
        php = f"""<?php
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {{ http_response_code(405); exit; }}
if (!empty($_POST['website'])) exit;
$name = htmlspecialchars($_POST['name'] ?? '');
$phone = htmlspecialchars($_POST['phone'] ?? '');
$email_from = htmlspecialchars($_POST['email'] ?? '');
$message = htmlspecialchars($_POST['message'] ?? '');
if (empty($name) || empty($phone)) {{ http_response_code(400); exit('Required'); }}
$to = '{email}';
$subject = "Request from $name";
$body = "Name: $name\\nPhone: $phone\\nEmail: $email_from\\nMessage: $message";
mail($to, $subject, $body, "From: noreply@" . $_SERVER['HTTP_HOST']);
echo json_encode(['success' => true]);
?>"""
        self._ssh.execute(f"cat > {path}/send.php << 'PHPEOF'\n{php}\nPHPEOF", server)

    def _create_privacy_page(self, path, blueprint, server):
        """Create privacy policy page."""
        html = """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Privacy Policy</title></head><body>
<h1>Privacy Policy</h1><p>Standard privacy policy text.</p>
</body></html>"""
        self._ssh.execute(f"cat > {path}/privacy.html << 'PRIVEOF'\n{html}\nPRIVEOF", server)

    def _setup_nginx(self, path, blueprint, server):
        """Setup nginx config."""
        site_name = path.rstrip('/').split('/')[-1]
        conf = f"""location /{site_name}/ {{
    alias {path}/;
    index index.php index.html;
    location ~ \\.php$ {{
        fastcgi_pass unix:/run/php/php-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $request_filename;
        include fastcgi_params;
    }}
}}"""
        self._ssh.execute(
            f"cat > /etc/nginx/conf.d/{site_name}.conf << 'NEOF'\n{conf}\nNEOF",
            server
        )
        self._ssh.execute("nginx -t && systemctl reload nginx", server)
