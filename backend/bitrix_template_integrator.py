"""
Bitrix Template Integrator - integrate HTML landing into Bitrix.
ULTIMATE PATCH Part D5.
"""

import logging
import os
from typing import Dict

logger = logging.getLogger("bitrix_integrator")


class BitrixTemplateIntegrator:
    
    def __init__(self, ssh_executor):
        self._ssh = ssh_executor
    
    def import_static_landing(self, install_path: str, 
                               html_path: str, server=None) -> dict:
        """Mode 1: connect HTML as main page."""
        
        # Backup original index.php
        self._ssh.execute(
            f"cp {install_path}/index.php {install_path}/index.php.bak",
            server
        )
        
        # Copy HTML
        self._ssh.execute(
            f"cp {html_path}/index.html {install_path}/index.html",
            server
        )
        
        # Copy assets
        for folder in ["css", "js", "images", "img", "fonts"]:
            self._ssh.execute(
                f"cp -r {html_path}/{folder} {install_path}/ 2>/dev/null",
                server
            )
        
        return {"success": True, "mode": "static_landing"}
    
    def wire_contact_form(self, install_path: str, 
                           form_config: dict, server=None) -> dict:
        """Connect contact form handler."""
        
        email = form_config.get("email", "admin@example.com")
        
        send_php = """<?php
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    exit('Method not allowed');
}

// Honeypot check
if (!empty($_POST['website'])) {
    exit('Spam detected');
}

$name = htmlspecialchars($_POST['name'] ?? '');
$phone = htmlspecialchars($_POST['phone'] ?? '');
$email_from = htmlspecialchars($_POST['email'] ?? '');
$message = htmlspecialchars($_POST['message'] ?? '');

if (empty($name) || empty($phone)) {
    http_response_code(400);
    exit('Name and phone required');
}

$to = '""" + email + """';
$subject = "Request from website from $name";
$body = "Name: $name\nPhone: $phone\nEmail: $email_from\nMessage: $message";
$headers = "From: noreply@" . $_SERVER['HTTP_HOST'];

mail($to, $subject, $body, $headers);
echo json_encode(['success' => true, 'message' => 'Thank you! We will call back.']);
?>"""
        
        self._ssh.execute(
            f"cat > {install_path}/send.php << 'PHPEOF'\n{send_php}\nPHPEOF",
            server
        )
        
        return {"success": True, "handler": f"{install_path}/send.php"}
