"""
ORION Digital — Tools Schema Definition.
Extracted from agent_loop.py (TASK 7).
"""
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "generate_site_content",
            "description": "Generate all text content for a website from blueprint. Returns sections text, meta tags, FAQ, reviews, privacy policy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "blueprint": {
                        "type": "string",
                        "description": "Blueprint JSON or ID"
                    }
                },
                "required": [
                    "blueprint"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "final_site_judge",
            "description": "Specialized judge for websites. Checks sections, photos, forms, mobile, speed, meta tags, design compliance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site_url": {
                        "type": "string",
                        "description": "URL of the deployed site"
                    },
                    "blueprint": {
                        "type": "string",
                        "description": "Blueprint JSON for comparison"
                    }
                },
                "required": [
                    "site_url"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bitrix_reverse_engineer",
            "description": "Analyze existing Bitrix site. Determines version, template, components, modules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "site_url": {
                        "type": "string"
                    },
                    "install_path": {
                        "type": "string"
                    },
                    "server_host": {
                        "type": "string"
                    }
                },
                "required": [
                    "install_path",
                    "server_host"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bitrix_build_template",
            "description": "Build Bitrix template from HTML. Splits into header.php, footer.php, template_styles.css, registers template.",
            "parameters": {
                "type": "object",
                "properties": {
                    "html_path": {
                        "type": "string",
                        "description": "Path to source HTML on server"
                    },
                    "install_path": {
                        "type": "string",
                        "description": "Bitrix installation path"
                    },
                    "server_host": {
                        "type": "string"
                    }
                },
                "required": [
                    "html_path",
                    "install_path",
                    "server_host"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bitrix_map_components",
            "description": "Map HTML sections to Bitrix components. Forms, sliders, FAQ, maps, galleries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "blueprint": {
                        "type": "string"
                    },
                    "install_path": {
                        "type": "string"
                    },
                    "server_host": {
                        "type": "string"
                    }
                },
                "required": [
                    "blueprint",
                    "install_path",
                    "server_host"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bitrix_publish",
            "description": "Publish and finalize Bitrix site. Clears cache, removes setup files, sets permissions, verifies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "install_path": {
                        "type": "string"
                    },
                    "server_host": {
                        "type": "string"
                    }
                },
                "required": [
                    "install_path",
                    "server_host"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_site_blueprint",
            "description": "Create a site structure from brief. Call BEFORE writing code. Returns JSON blueprint with sections, photos, forms, design.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brief": {
                        "type": "string",
                        "description": "Full text of the brief/TZ"
                    },
                    "site_type": {
                        "type": "string",
                        "enum": [
                            "landing",
                            "corporate",
                            "shop"
                        ],
                        "description": "Type of site to create"
                    }
                },
                "required": [
                    "brief"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_landing",
            "description": "Build a landing page from blueprint. Generates photos, HTML, CSS, JS, PHP handler, deploys to server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "blueprint_id": {
                        "type": "string",
                        "description": "Blueprint ID or JSON"
                    },
                    "server_host": {
                        "type": "string",
                        "description": "Server IP or domain"
                    },
                    "deploy_path": {
                        "type": "string",
                        "description": "Server path for deployment"
                    }
                },
                "required": [
                    "blueprint_id",
                    "server_host",
                    "deploy_path"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "install_bitrix",
            "description": "Install 1C-Bitrix CMS on a server. Prepares the server, runs the installation wizard, and verifies the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_host": {
                        "type": "string",
                        "description": "Server IP or domain"
                    },
                    "install_path": {
                        "type": "string",
                        "description": "Installation path, e.g. /var/www/html/site"
                    },
                    "db_name": {
                        "type": "string",
                        "description": "Database name"
                    },
                    "db_user": {
                        "type": "string",
                        "description": "Database user"
                    },
                    "db_password": {
                        "type": "string",
                        "description": "Database password"
                    },
                    "admin_login": {
                        "type": "string",
                        "description": "Bitrix admin login"
                    },
                    "admin_email": {
                        "type": "string",
                        "description": "Admin email"
                    },
                    "admin_password": {
                        "type": "string",
                        "description": "Admin password"
                    },
                    "use_demo": {
                        "type": "boolean",
                        "description": "Install demo data"
                    }
                },
                "required": [
                    "server_host",
                    "install_path",
                    "db_name",
                    "db_user",
                    "db_password"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_execute",
            "description": "Execute a shell command on a remote server via SSH. Use for: installing packages, running scripts, checking services, deploying code, managing processes, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Server IP or hostname to connect to"
                    },
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute on the server"
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH username (default: root)",
                        "default": "root"
                    },
                    "password": {
                        "type": "string",
                        "description": "SSH password for authentication"
                    }
                },
                "required": [
                    "host",
                    "command"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Create or overwrite a file on a remote server via SFTP. Use for: creating config files, writing code, deploying applications, creating scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Server IP or hostname"
                    },
                    "path": {
                        "type": "string",
                        "description": "Absolute path where to create/write the file"
                    },
                    "content": {
                        "type": "string",
                        "description": "Full content of the file to write"
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH username (default: root)",
                        "default": "root"
                    },
                    "password": {
                        "type": "string",
                        "description": "SSH password"
                    }
                },
                "required": [
                    "host",
                    "path",
                    "content"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read content of a file from a remote server. Use for: checking configs, reading logs, verifying deployed code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Server IP or hostname"
                    },
                    "path": {
                        "type": "string",
                        "description": "Absolute path of the file to read"
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH username (default: root)",
                        "default": "root"
                    },
                    "password": {
                        "type": "string",
                        "description": "SSH password"
                    }
                },
                "required": [
                    "host",
                    "path"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Open a URL in browser and get page content. Use for: checking websites, verifying deployments, reading documentation, testing APIs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to navigate to"
                    }
                },
                "required": [
                    "url"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_check_site",
            "description": "Check if a website is accessible and get status info (response time, title, status code).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to check"
                    }
                },
                "required": [
                    "url"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_text",
            "description": "Get clean text content from a webpage (without HTML tags).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to get text from"
                    }
                },
                "required": [
                    "url"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_check_api",
            "description": "Send HTTP request to an API endpoint and get response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "API endpoint URL"
                    },
                    "method": {
                        "type": "string",
                        "description": "HTTP method (GET, POST, PUT, DELETE)",
                        "default": "GET"
                    },
                    "data": {
                        "type": "object",
                        "description": "JSON data to send (for POST/PUT)"
                    }
                },
                "required": [
                    "url"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_file",
            "description": "Generate a downloadable file for the user. Supports: .docx (Word), .pdf, .md (Markdown), .txt, .html, .xlsx (Excel), .csv, .json, .py, .js, .css, .sql and other code files. ALWAYS use this when user asks to create/generate a document, report, spreadsheet, or any file. The file will be available for download via a link.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Full content of the file. For docx/pdf use markdown-like formatting (# headers, **bold**, - lists). For xlsx use CSV format (comma-separated). For html use full HTML."
                    },
                    "filename": {
                        "type": "string",
                        "description": "Filename with extension, e.g. 'report.docx', 'data.xlsx', 'page.html'"
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title for docx/pdf documents"
                    }
                },
                "required": [
                    "content",
                    "filename"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image using AI (diagram, chart, illustration). Returns a download link. Use for: creating diagrams, charts, logos, illustrations, mockups.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed description of the image to generate"
                    },
                    "style": {
                        "type": "string",
                        "description": "Style: 'diagram', 'chart', 'illustration', 'photo', 'logo', 'mockup'",
                        "default": "illustration"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Output filename, e.g. 'diagram.png'",
                        "default": "image.png"
                    }
                },
                "required": [
                    "prompt"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_any_file",
            "description": "Read and analyze any uploaded file. Supports: PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, images (with OCR), archives (ZIP/TAR), code files, TXT, MD. Returns extracted text, metadata, tables, and summary. Use when user uploads a file or asks to analyze a document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the uploaded file on server"
                    },
                    "extract_tables": {
                        "type": "boolean",
                        "description": "Whether to extract tables as structured data",
                        "default": True
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum text length to return",
                        "default": 50000
                    }
                },
                "required": [
                    "file_path"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": "Analyze an image using AI vision. Understands screenshots, charts, diagrams, photos, handwritten notes. Returns description, detected text (OCR), and insights. Use when user uploads an image or asks to analyze a screenshot/photo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the image file"
                    },
                    "question": {
                        "type": "string",
                        "description": "Specific question about the image (optional)",
                        "default": "Describe this image in detail"
                    }
                },
                "required": [
                    "file_path"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for current information. Returns ranked results with titles, URLs, and snippets. Use when user asks about current events, needs fact-checking, or requests research on any topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (1-10)",
                        "default": 5
                    }
                },
                "required": [
                    "query"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and parse a web page content. Returns clean text extracted from the URL. Use for reading articles, documentation, or any web content in detail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the web page to fetch"
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum text length to return",
                        "default": 20000
                    }
                },
                "required": [
                    "url"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "code_interpreter",
            "description": "Execute Python code in a secure sandbox. Use for: data analysis, calculations, generating charts/visualizations, processing files, statistical analysis, machine learning. The sandbox has numpy, pandas, matplotlib, plotly, scipy, sklearn pre-installed. Returns stdout, stderr, and any generated files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute"
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what the code does"
                    }
                },
                "required": [
                    "code"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": "Generate an interactive chart/visualization. Supports: bar, line, pie, scatter, heatmap, histogram, area, radar charts. Returns an HTML artifact with interactive Plotly chart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "description": "Type: bar, line, pie, scatter, heatmap, histogram, area, radar"
                    },
                    "data": {
                        "type": "object",
                        "description": "Chart data: {labels: [...], datasets: [{label: '...', values: [...]}]}"
                    },
                    "title": {
                        "type": "string",
                        "description": "Chart title"
                    },
                    "options": {
                        "type": "object",
                        "description": "Additional options: {colors: [...], width: 800, height: 500}"
                    }
                },
                "required": [
                    "chart_type",
                    "data",
                    "title"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_artifact",
            "description": "Create an interactive artifact (live HTML, SVG, Mermaid diagram, React component). The artifact renders in a sandboxed iframe in the chat. Use for: UI mockups, landing pages, interactive demos, diagrams, dashboards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Full HTML/SVG/Mermaid content"
                    },
                    "type": {
                        "type": "string",
                        "description": "Type: html, svg, mermaid, react",
                        "default": "html"
                    },
                    "title": {
                        "type": "string",
                        "description": "Artifact title for display"
                    }
                },
                "required": [
                    "content",
                    "title"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": "Generate a comprehensive multi-page report with embedded charts and tables. Output as DOCX, PDF, or XLSX. Use when user needs a professional report with data analysis, visualizations, and conclusions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Report title"
                    },
                    "sections": {
                        "type": "array",
                        "description": "Array of sections: [{heading: '...', content: '...', chart_data: {...}}]",
                        "items": {
                            "type": "object"
                        }
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format: docx, pdf, xlsx",
                        "default": "docx"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Output filename"
                    }
                },
                "required": [
                    "title",
                    "sections"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_image",
            "description": "Edit an existing image: resize, crop, add text/watermark, adjust colors, apply filters, convert format. Use when user wants to modify an uploaded or generated image.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the image file to edit"
                    },
                    "operations": {
                        "type": "array",
                        "description": "List of operations: [{type: 'resize', width: 800, height: 600}, {type: 'crop', x: 0, y: 0, w: 400, h: 300}, {type: 'text', text: 'Hello', x: 50, y: 50, color: '#fff', size: 24}, {type: 'filter', name: 'blur|sharpen|grayscale|sepia|brightness|contrast'}, {type: 'watermark', text: '...'}, {type: 'rotate', angle: 90}, {type: 'convert', format: 'png|jpg|webp'}]",
                        "items": {
                            "type": "object"
                        }
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "Output filename",
                        "default": "edited_image.png"
                    }
                },
                "required": [
                    "file_path",
                    "operations"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_design",
            "description": "Generate a professional design: banner, social media post, presentation slide, infographic, business card, logo concept. Returns HTML artifact or image.",
            "parameters": {
                "type": "object",
                "properties": {
                    "design_type": {
                        "type": "string",
                        "description": "Type: banner, social_post, slide, infographic, business_card, logo, poster, flyer"
                    },
                    "content": {
                        "type": "object",
                        "description": "Design content: {title: '...', subtitle: '...', body: '...', cta: '...', colors: [...], images: [...]}"
                    },
                    "style": {
                        "type": "string",
                        "description": "Style: modern, minimal, corporate, creative, elegant, bold",
                        "default": "modern"
                    },
                    "dimensions": {
                        "type": "object",
                        "description": "Size: {width: 1200, height: 630}",
                        "default": {}
                    }
                },
                "required": [
                    "design_type",
                    "content"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "store_memory",
            "description": "Store important information in persistent memory for future conversations. Use to remember user preferences, project details, key facts, decisions made.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Memory key/topic (e.g. 'user_preferences', 'project_stack', 'server_config')"
                    },
                    "value": {
                        "type": "string",
                        "description": "Information to remember"
                    },
                    "category": {
                        "type": "string",
                        "description": "Category: preference, fact, project, decision, context",
                        "default": "fact"
                    }
                },
                "required": [
                    "key",
                    "value"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Recall stored information from persistent memory. Search by key or category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query or key to recall"
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category (optional)"
                    }
                },
                "required": [
                    "query"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "canvas_create",
            "description": "Create or update a collaborative canvas document. Canvas is a persistent editable document (like Google Docs) that can be iteratively refined. Use for long documents, code projects, plans that need multiple revisions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Canvas document title"
                    },
                    "content": {
                        "type": "string",
                        "description": "Full content (Markdown, code, or HTML)"
                    },
                    "canvas_type": {
                        "type": "string",
                        "description": "Type: document, code, plan, design",
                        "default": "document"
                    },
                    "canvas_id": {
                        "type": "string",
                        "description": "Existing canvas ID to update (omit for new)"
                    }
                },
                "required": [
                    "title",
                    "content"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Mark the task as complete. Call this when all steps are done and verified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of what was accomplished"
                    }
                },
                "required": [
                    "summary"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click on an element on the current browser page. Supports CSS selectors (button.submit, #login-btn), text selectors (text=Войти), Beget st-attributes ([st=\"button-dns-edit-node\"]), and xpath (xpath=//button). Waits for SPA navigation (Vue.js/React) after click. Returns screenshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector or text=... selector of the element to click"
                    }
                },
                "required": [
                    "selector"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_scratchpad",
            "description": "Update your internal scratchpad with thoughts, plans, and progress notes. Use this to organize your thinking and track progress on complex tasks."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_charter",
            "description": "Update the structured Task Charter with project goals, pages, style, tech stack, and status. Use this at the start of complex tasks to define the project plan. All agents can see this charter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The thought, plan, or progress note to add to scratchpad"
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "plan",
                            "thought",
                            "progress",
                            "error",
                            "decision"
                        ],
                        "description": "Category of the scratchpad entry"
                    }
                },
                "required": [
                    "content"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "Fill a form field with Vue.js/React event triggers. Tries 3 strategies: Playwright fill, click+type, JavaScript setValue. Works with Vuetify, Material UI, and any SPA framework. Returns screenshot after fill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the input field"
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to type into the field"
                    }
                },
                "required": [
                    "selector",
                    "value"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_submit",
            "description": "Submit a form on the current browser page. Optionally specify submit button selector. If no selector — presses Enter. Returns screenshot and URL after submit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of submit button or form (optional). If omitted — presses Enter."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_select",
            "description": "Select an option from a <select> dropdown on the current browser page. Returns screenshot after selection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the <select> element"
                    },
                    "value": {
                        "type": "string",
                        "description": "Option value or label text to select"
                    }
                },
                "required": [
                    "selector",
                    "value"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_ask_auth",
            "description": "Detect login form on current page and request credentials from user via ORION chat UI. Shows screenshot + form fields to user. User enters credentials → agent fills and submits the form. USE THIS when encountering login/auth pages instead of hardcoding passwords.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the login page (optional, uses current page if omitted)"
                    },
                    "hint": {
                        "type": "string",
                        "description": "Hint for user about what system requires login (e.g. 'Bitrix admin panel', 'FTP server')"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text character by character into a field (for SPA where browser_fill doesn't work). Clicks the field first, then types. Use when browser_fill fails with Vuetify/Material UI inputs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the input field"
                    },
                    "value": {
                        "type": "string",
                        "description": "Text to type"
                    },
                    "clear": {
                        "type": "boolean",
                        "description": "Clear field before typing (default: True)",
                        "default": True
                    }
                },
                "required": [
                    "selector",
                    "value"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_js",
            "description": "Execute arbitrary JavaScript on the current page. Returns result + screenshot. Use for complex DOM manipulation, reading page state, triggering Vue/React events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "JavaScript code to execute. Can return a value."
                    }
                },
                "required": [
                    "code"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_press_key",
            "description": "Press a keyboard key on the current page. Use Enter to submit forms, Tab to move focus, Escape to close dialogs, ArrowDown for dropdowns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key name: Enter, Tab, Escape, ArrowDown, ArrowUp, Control+a, etc."
                    }
                },
                "required": [
                    "key"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the current page in a direction. Use to see content below the fold, load lazy content, or navigate long pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": [
                            "up",
                            "down",
                            "left",
                            "right"
                        ],
                        "description": "Scroll direction"
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Scroll amount in pixels (default: 500)",
                        "default": 500
                    }
                },
                "required": [
                    "direction"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_hover",
            "description": "Hover mouse over an element to reveal hidden menus, tooltips, or action buttons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element to hover over"
                    }
                },
                "required": [
                    "selector"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": "Wait for an element to appear or URL to change. Use after actions that trigger async loading (AJAX, SPA routing).",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to wait for (optional)"
                    },
                    "url_contains": {
                        "type": "string",
                        "description": "Wait until URL contains this substring (optional)"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max wait time in ms (default: 15000)",
                        "default": 15000
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_elements",
            "description": "Get a list of elements matching a selector with their text, attributes, and positions. Use to understand page structure before clicking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to match elements (e.g. 'button', '.menu-item', '[st]')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max elements to return (default: 50)",
                        "default": 50
                    }
                },
                "required": [
                    "selector"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Take a screenshot of the current page. Returns base64 image + current URL and title.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_page_info",
            "description": "Get detailed info about current page: URL, title, forms, buttons, links, captcha detection, 2FA detection. Use to understand what's on the page before taking action.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "smart_login",
            "description": "Automatically log into any website. Tries multiple strategies: find login/password fields, fill them, submit via Enter/button/JS. If login fails or CAPTCHA detected — returns need_user_takeover=true. Use this as the FIRST approach for any login task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Login page URL"
                    },
                    "login": {
                        "type": "string",
                        "description": "Username/email/login"
                    },
                    "password": {
                        "type": "string",
                        "description": "Password"
                    }
                },
                "required": [
                    "url",
                    "login",
                    "password"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_ask_user",
            "description": "Request user to take over browser control. Use when: CAPTCHA detected, 2FA required, unusual login form, or any situation where automated input fails. Shows screenshot to user with instructions. User can: enter credentials in chat, manually control browser, or skip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": [
                            "captcha",
                            "2fa",
                            "login_failed",
                            "unusual_form",
                            "confirmation",
                            "custom"
                        ],
                        "description": "Why user takeover is needed"
                    },
                    "instruction": {
                        "type": "string",
                        "description": "What the user should do (shown in chat)"
                    }
                },
                "required": [
                    "reason"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_takeover_done",
            "description": "Call after user has finished manual browser interaction. Takes screenshot and returns current page state so agent can continue.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ftp_upload",
            "description": "Upload a file to FTP server using ftplib (works even when SSH is disabled). Supports passwords with special characters (#, @, ! etc). Use for deploying files to shared hosting, Bitrix sites, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "FTP server hostname or IP"
                    },
                    "username": {
                        "type": "string",
                        "description": "FTP username"
                    },
                    "password": {
                        "type": "string",
                        "description": "FTP password (special chars supported)"
                    },
                    "remote_path": {
                        "type": "string",
                        "description": "Full remote path including filename, e.g. /www/site.ru/index.php"
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to upload"
                    },
                    "port": {
                        "type": "integer",
                        "description": "FTP port (default: 21)",
                        "default": 21
                    }
                },
                "required": [
                    "host",
                    "username",
                    "password",
                    "remote_path",
                    "content"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ftp_download",
            "description": "Download a file from FTP server. Returns file content as text. Use to read existing files before modifying them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "FTP server hostname or IP"
                    },
                    "username": {
                        "type": "string",
                        "description": "FTP username"
                    },
                    "password": {
                        "type": "string",
                        "description": "FTP password"
                    },
                    "remote_path": {
                        "type": "string",
                        "description": "Full remote path of the file to download"
                    },
                    "port": {
                        "type": "integer",
                        "description": "FTP port (default: 21)",
                        "default": 21
                    }
                },
                "required": [
                    "host",
                    "username",
                    "password",
                    "remote_path"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ftp_list",
            "description": "List files and directories on FTP server. Use to explore site structure before uploading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "FTP server hostname or IP"
                    },
                    "username": {
                        "type": "string",
                        "description": "FTP username"
                    },
                    "password": {
                        "type": "string",
                        "description": "FTP password"
                    },
                    "remote_path": {
                        "type": "string",
                        "description": "Remote directory path to list",
                        "default": "/"
                    },
                    "port": {
                        "type": "integer",
                        "description": "FTP port (default: 21)",
                        "default": 21
                    }
                },
                "required": [
                    "host",
                    "username",
                    "password"
                ]
            }
        }
    },
    # ══ WEBSITE FACTORY TOOLS ══════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "parse_site_brief",
            "description": "Parse a site brief/TZ into structured JSON. Extracts: goal, audience, sections, style, features, contacts, SEO keywords. Use as the FIRST step in website creation pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brief_text": {"type": "string", "description": "Raw brief/TZ text from user"},
                    "site_type": {"type": "string", "description": "Type: landing, corporate, ecommerce, portfolio", "default": "landing"}
                },
                "required": ["brief_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_site_blueprint",
            "description": "Create a site blueprint (JSON structure) from parsed brief. Defines sections, order, content blocks, forms, navigation. MUST be called before building HTML.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brief": {"type": "object", "description": "Parsed brief JSON from parse_site_brief"},
                    "site_type": {"type": "string", "description": "Type: landing, corporate, ecommerce", "default": "landing"}
                },
                "required": ["brief"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "plan_site_design",
            "description": "Plan visual design: colors, fonts, layout, spacing, component styles. Returns design_plan.json.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brief": {"type": "object", "description": "Parsed brief JSON"},
                    "blueprint": {"type": "object", "description": "Site blueprint JSON"},
                    "style_preference": {"type": "string", "description": "Style: modern, minimal, corporate, creative", "default": "modern"}
                },
                "required": ["brief", "blueprint"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_site_content",
            "description": "Generate text content for all site sections: headings, descriptions, CTAs, FAQ, reviews. Returns site_content.json.",
            "parameters": {
                "type": "object",
                "properties": {
                    "blueprint": {"type": "object", "description": "Site blueprint JSON"},
                    "brief": {"type": "object", "description": "Parsed brief JSON"},
                    "tone": {"type": "string", "description": "Tone: professional, friendly, formal, creative", "default": "professional"}
                },
                "required": ["blueprint", "brief"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_landing",
            "description": "Build a complete landing page (HTML+CSS+JS) from blueprint, design, and content. Includes responsive layout, forms, photos, animations. NEVER call without blueprint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "blueprint": {"type": "object", "description": "Site blueprint JSON"},
                    "design": {"type": "object", "description": "Design plan JSON"},
                    "content": {"type": "object", "description": "Site content JSON"},
                    "output_path": {"type": "string", "description": "Path to save HTML file", "default": "index.html"}
                },
                "required": ["blueprint", "design", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "publish_site",
            "description": "Deploy site to server: upload files, configure nginx, setup HTTPS, verify. Returns deploy_report.json.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP or hostname"},
                    "html_content": {"type": "string", "description": "HTML content to deploy"},
                    "domain": {"type": "string", "description": "Domain name"},
                    "deploy_path": {"type": "string", "description": "Server path", "default": "/var/www/html"},
                    "enable_ssl": {"type": "boolean", "description": "Setup Let's Encrypt SSL", "default": True}
                },
                "required": ["host", "html_content", "domain"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_site",
            "description": "Comprehensive site verification: HTTP status, mobile, meta tags, forms, links, speed, security headers. Returns verification_report.json.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL of the deployed site"},
                    "checks": {"type": "array", "items": {"type": "string"}, "description": "Specific checks to run (default: all)"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "judge_site_release",
            "description": "Final judge for website release. Checks 9 criteria: sections, photos, forms, mobile, meta, speed, links, HTTPS, content. Returns verdict: RELEASE/CONDITIONAL/REWORK/FAIL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL of the site"},
                    "blueprint": {"type": "object", "description": "Site blueprint JSON"},
                    "brief": {"type": "object", "description": "Original brief JSON"}
                },
                "required": ["url", "blueprint"]
            }
        }
    },
    # ══ BITRIX FACTORY TOOLS ═══════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "provision_bitrix_server",
            "description": "Prepare server for Bitrix: install Apache/Nginx, PHP, MySQL, create DB, download bitrixsetup.php.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP"},
                    "db_name": {"type": "string", "description": "Database name", "default": "bitrix_db"},
                    "db_user": {"type": "string", "description": "DB username", "default": "bitrix_user"},
                    "db_password": {"type": "string", "description": "DB password (auto-generated if empty)"},
                    "php_version": {"type": "string", "description": "PHP version", "default": "8.1"},
                    "web_server": {"type": "string", "description": "apache or nginx", "default": "apache"}
                },
                "required": ["host"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_bitrix_wizard",
            "description": "Run Bitrix web installer wizard: accept license, configure DB, set site name, install modules, create admin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Server URL"},
                    "db_name": {"type": "string", "description": "Database name"},
                    "db_user": {"type": "string", "description": "DB username"},
                    "db_password": {"type": "string", "description": "DB password"},
                    "admin_login": {"type": "string", "description": "Admin login", "default": "admin"},
                    "admin_password": {"type": "string", "description": "Admin password"},
                    "site_name": {"type": "string", "description": "Site name"},
                    "edition": {"type": "string", "description": "Edition: start, standard, business", "default": "start"}
                },
                "required": ["url", "db_name", "db_user", "db_password"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_bitrix",
            "description": "Verify Bitrix installation health: core files, DB, PHP, modules, permissions, cron, settings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP"},
                    "install_path": {"type": "string", "description": "Bitrix install path", "default": "/var/www/html"},
                    "url": {"type": "string", "description": "Site URL (optional)"}
                },
                "required": ["host"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "build_bitrix_template",
            "description": "Create Bitrix template from HTML/CSS: header.php, footer.php, template_styles.css, description.php.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP"},
                    "template_name": {"type": "string", "description": "Template slug name"},
                    "html_content": {"type": "string", "description": "Full HTML of the site"},
                    "css_content": {"type": "string", "description": "CSS styles"},
                    "js_content": {"type": "string", "description": "JavaScript code"},
                    "install_path": {"type": "string", "description": "Bitrix install path", "default": "/var/www/html"}
                },
                "required": ["host", "template_name", "html_content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "map_bitrix_components",
            "description": "Map site sections to Bitrix components: news.list, form.result.new, main.include, etc. Returns component_map.json.",
            "parameters": {
                "type": "object",
                "properties": {
                    "blueprint": {"type": "object", "description": "Site blueprint JSON"}
                },
                "required": ["blueprint"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_bitrix_site",
            "description": "Reverse-engineer existing Bitrix site: version, edition, template, modules, iblocks, components, forms, custom code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP"},
                    "install_path": {"type": "string", "description": "Bitrix install path", "default": "/var/www/html"},
                    "url": {"type": "string", "description": "Site URL"}
                },
                "required": ["host"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "publish_bitrix",
            "description": "Deploy Bitrix site: upload template, configure domain, SSL, clear cache, set permissions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP"},
                    "domain": {"type": "string", "description": "Domain name"},
                    "template_name": {"type": "string", "description": "Template name"},
                    "html_content": {"type": "string", "description": "HTML content"},
                    "css_content": {"type": "string", "description": "CSS styles"},
                    "install_path": {"type": "string", "description": "Install path", "default": "/var/www/html"},
                    "enable_ssl": {"type": "boolean", "description": "Setup SSL", "default": True}
                },
                "required": ["host", "domain"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "judge_bitrix_release",
            "description": "Final judge for Bitrix site release. Checks: installation, admin panel, template, forms, public access, assets, cache, PHP errors, .htaccess. Returns verdict with grade.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Site URL"},
                    "admin_url": {"type": "string", "description": "Admin panel URL"},
                    "admin_login": {"type": "string", "description": "Admin login"},
                    "admin_password": {"type": "string", "description": "Admin password"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "backup_bitrix",
            "description": "Create backup of Bitrix site: database dump + files archive. Returns backup metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP"},
                    "install_path": {"type": "string", "description": "Bitrix install path", "default": "/var/www/html"},
                    "label": {"type": "string", "description": "Backup label"}
                },
                "required": ["host"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "restore_bitrix",
            "description": "Restore Bitrix site from backup: database + files. Stops services, restores, clears cache, restarts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP"},
                    "label": {"type": "string", "description": "Backup label to restore"}
                },
                "required": ["host", "label"]
            }
        }
    },
    # PATCH 13: Universal code_execute tool
    {
        "type": "function",
        "function": {
            "name": "code_execute",
            "description": "Execute arbitrary Python code in a secure sandboxed subprocess. Use for: data processing, automation scripts, file manipulation, API calls, calculations, text processing, web scraping with requests, working with pandas/numpy/json. Allowed libraries: requests, json, csv, re, math, datetime, pathlib, pandas, numpy, openpyxl, paramiko, bs4. Returns stdout, stderr, return_code and any generated files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Use print() to output results."
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what the code does"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds (default: 30, max: 120)",
                        "default": 30
                    }
                },
                "required": [
                    "code"
                ]
            }
        }
    }
]


# ══════════════════════════════════════════════════════════════════════════
# DEDUPLICATION: Remove duplicate tool names (BUG FIX)
# ══════════════════════════════════════════════════════════════════════════
_seen_tool_names = set()
_deduped = []
for _tool in TOOLS_SCHEMA:
    _name = _tool.get("function", {}).get("name", "")
    if _name not in _seen_tool_names:
        _seen_tool_names.add(_name)
        _deduped.append(_tool)
TOOLS_SCHEMA = _deduped
del _seen_tool_names, _deduped, _tool, _name

# ══════════════════════════════════════════════════════════════════════════
# MANUS TOOLS — 10 новых инструментов (Спринт 1 + 2)
# Добавлены: web_scrape, pdf_read, excel_create, slides_create,
#            transcribe_audio, git_execute, http_request,
#            parallel_tasks, research_deep, long_memory_search
# ══════════════════════════════════════════════════════════════════════════
try:
    from manus_tools_schema import MANUS_TOOLS_SCHEMA
    TOOLS_SCHEMA.extend(MANUS_TOOLS_SCHEMA)
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════════
# SPRINT 2 TOOLS — 10 Advanced Manus capabilities
# dev_server_start, dev_server_stop, checkpoint_create, checkpoint_restore,
# web_search_deep, code_run_file, data_analyze, image_process,
# deploy_static, task_memory_save
# ══════════════════════════════════════════════════════════════════════════
try:
    from sprint2_tools_schema import SPRINT2_TOOLS_SCHEMA
    _s2_existing = {t["function"]["name"] for t in TOOLS_SCHEMA}
    for _s2t in SPRINT2_TOOLS_SCHEMA:
        if _s2t["function"]["name"] not in _s2_existing:
            TOOLS_SCHEMA.append(_s2t)
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════════
# SPRINT 3 TOOLS — Docker Sandbox & Runtime Logs
# sandbox_exec, sandbox_create_session, sandbox_list_sessions,
# sandbox_destroy_session, runtime_logs, docker_run_image
# ══════════════════════════════════════════════════════════════════════════
try:
    from sprint3_sandbox_schema import SPRINT3_TOOLS_SCHEMA
    _s3_existing = {t["function"]["name"] for t in TOOLS_SCHEMA}
    for _s3t in SPRINT3_TOOLS_SCHEMA:
        if _s3t["function"]["name"] not in _s3_existing:
            TOOLS_SCHEMA.append(_s3t)
except ImportError:
    pass
