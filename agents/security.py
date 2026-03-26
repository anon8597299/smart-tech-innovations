"""
agents/security.py — Security Manager Agent

Full-stack defensive security agent for the IYS system.
Acts as an autonomous pen tester and vulnerability expert.

What it does on every run:
  1. Secret scan   — regex scan all source files for leaked credentials
  2. Git audit     — check git history for ever-committed secrets
  3. Gitignore     — verify all sensitive files are properly excluded
  4. Endpoint test — probe dashboard API auth (auth bypass, missing protection)
  5. Dep check     — scan Python dependencies for known CVEs via pip-audit
  6. Permissions   — check .env and key files aren't world-readable
  7. Public scan   — verify no sensitive files ended up in git-tracked files
  8. Code review   — OWASP Top 10 scan via Claude on critical files

Schedule: 6:00 AM daily + on-demand via dashboard
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from dashboard import db

PROJECT_ROOT = Path(__file__).parent.parent
SECURITY_DIR = PROJECT_ROOT / "security"
REPORT_FILE  = SECURITY_DIR / "security_report.json"

SECURITY_DIR.mkdir(exist_ok=True)

# ── Secret patterns — what we hunt for ───────────────────────────────────────

SECRET_PATTERNS = [
    (r'sk-ant-api\d{2}-[A-Za-z0-9_\-]{80,}',         'Anthropic API key'),
    (r'ghp_[A-Za-z0-9]{36}',                           'GitHub Personal Access Token'),
    (r'sk_live_[A-Za-z0-9]{24,}',                      'Stripe live secret key'),
    (r'sk_test_[A-Za-z0-9]{24,}',                      'Stripe test secret key'),
    (r'AIzaSy[A-Za-z0-9_\-]{33}',                      'Google API key'),
    (r'pplx-[A-Za-z0-9]{48}',                          'Perplexity API key'),
    (r'GMAIL_APP_PASS\s*=\s*[a-z]{4}\s[a-z]{4}',      'Gmail App Password (plain text)'),
    (r'(?i)password\s*=\s*["\'][^"\']{8,}["\']',       'Hardcoded password'),
    (r'(?i)secret\s*=\s*["\'][^"\']{8,}["\']',         'Hardcoded secret'),
    (r'GOCSPX-[A-Za-z0-9_\-]{28}',                     'Google OAuth client secret'),
    (r'1//[A-Za-z0-9_\-]{40,}',                        'Google Refresh Token'),
    (r'EAA[A-Za-z0-9]{100,}',                          'Meta/Facebook access token'),
]

# Files to exclude from secret scanning (expected to hold secrets)
EXCLUDE_FROM_SCAN = {
    'builder/.env',
    '.env',
    'security/security_report.json',
}

# Extensions to scan
SCAN_EXTENSIONS = {'.py', '.js', '.html', '.json', '.yaml', '.yml', '.sh', '.md', '.txt'}

# Files/dirs to never scan
SKIP_DIRS = {'__pycache__', '.git', 'node_modules', '.venv', 'venv', 'customers', 'showcase'}

# ── Dashboard endpoints that MUST require auth ────────────────────────────────

PROTECTED_ENDPOINTS = [
    '/api/agents',
    '/api/tasks',
    '/api/events',
    '/api/escalations',
    '/api/env',
    '/api/agents/social/run',
]

PUBLIC_ENDPOINTS = ['/health', '/']

# ── OWASP focus areas for code review ────────────────────────────────────────

OWASP_REVIEW_FILES = [
    'dashboard/app.py',
    'dashboard/db.py',
    'agents/leads.py',
    'agents/openclaw.py',
]


class SecurityAgent(BaseAgent):
    agent_id = "security"
    name     = "Security Manager"

    def run(self):
        self.log_info("Security Manager: starting full security scan")
        findings = []

        # 1. Secret scan across source files
        tid = self.create_task("scan", "Secret scan — all source files")
        secret_findings = self._scan_secrets()
        findings += secret_findings
        count = len(secret_findings)
        if count:
            self.fail_task(tid, f"{count} secret(s) found in source files")
        else:
            self.complete_task(tid, "Clean — no secrets in source files")

        # 2. Git history audit
        tid = self.create_task("scan", "Git history — secret leak check")
        git_findings = self._scan_git_history()
        findings += git_findings
        if git_findings:
            self.fail_task(tid, f"{len(git_findings)} secret(s) found in git history")
        else:
            self.complete_task(tid, "Clean git history — no leaked secrets")

        # 3. Gitignore coverage
        tid = self.create_task("audit", "Gitignore coverage audit")
        gi_findings = self._audit_gitignore()
        findings += gi_findings
        if gi_findings:
            self.fail_task(tid, f"{len(gi_findings)} file(s) not properly excluded")
        else:
            self.complete_task(tid, "Gitignore covers all sensitive files")

        # 4. Dashboard endpoint auth testing
        tid = self.create_task("pentest", "Dashboard API endpoint auth test")
        ep_findings = self._test_endpoints()
        findings += ep_findings
        if ep_findings:
            self.fail_task(tid, f"{len(ep_findings)} unprotected endpoint(s) found")
        else:
            self.complete_task(tid, "All endpoints require auth")

        # 5. Dependency CVE check
        tid = self.create_task("audit", "Python dependency CVE scan")
        dep_findings = self._check_dependencies()
        findings += dep_findings
        self.complete_task(tid, f"{len(dep_findings)} vulnerability/outdated package(s) found"
                           if dep_findings else "Dependencies clean")

        # 6. File permissions
        tid = self.create_task("audit", "Sensitive file permissions check")
        perm_findings = self._check_permissions()
        findings += perm_findings
        if perm_findings:
            self.fail_task(tid, f"{len(perm_findings)} permission issue(s)")
        else:
            self.complete_task(tid, "File permissions OK")

        # 7. Public git exposure check
        tid = self.create_task("audit", "Public git exposure — tracked file check")
        pub_findings = self._check_public_exposure()
        findings += pub_findings
        if pub_findings:
            self.fail_task(tid, f"{len(pub_findings)} sensitive file(s) tracked by git")
        else:
            self.complete_task(tid, "No sensitive files tracked in git")

        # 8. OWASP code review via Claude
        tid = self.create_task("review", "OWASP Top 10 code review")
        owasp_findings = self._owasp_review()
        findings += owasp_findings
        self.complete_task(tid, f"{len(owasp_findings)} code issue(s) identified"
                           if owasp_findings else "Code review clean")

        # ── Save report ──────────────────────────────────────────────────────
        score   = self._calculate_score(findings)
        report  = self._save_report(findings, score)

        critical = [f for f in findings if f.get('severity') == 'critical']
        high     = [f for f in findings if f.get('severity') == 'high']

        summary = (
            f"Score: {score}/100 | "
            f"{len(findings)} finding(s): "
            f"{len(critical)} critical, {len(high)} high"
        )
        self.log_info(f"Security Manager: {summary}")

        if critical or high:
            self.send_email(
                subject=f"[SECURITY] {len(critical)} critical, {len(high)} high finding(s)",
                body=self._format_email(findings),
            )

    # ── 1. Secret scanning ────────────────────────────────────────────────────

    def _scan_secrets(self) -> list[dict]:
        findings = []
        for path in self._walkfiles():
            rel = str(path.relative_to(PROJECT_ROOT))
            if rel in EXCLUDE_FROM_SCAN:
                continue
            try:
                text = path.read_text(errors='ignore')
            except Exception:
                continue
            for pattern, label in SECRET_PATTERNS:
                for m in re.finditer(pattern, text):
                    line_no = text[:m.start()].count('\n') + 1
                    snippet = m.group()[:40] + '…' if len(m.group()) > 40 else m.group()
                    findings.append({
                        "severity":    "critical",
                        "category":    "secret_exposure",
                        "title":       f"{label} found in source file",
                        "location":    f"{rel}:{line_no}",
                        "detail":      f"Pattern: {snippet}",
                        "fix":         f"Remove from {rel}, rotate the credential immediately, add to .gitignore",
                    })
        return findings

    def _walkfiles(self):
        for p in PROJECT_ROOT.rglob('*'):
            if p.is_dir():
                continue
            if any(s in p.parts for s in SKIP_DIRS):
                continue
            if p.suffix.lower() in SCAN_EXTENSIONS:
                yield p

    # ── 2. Git history scan ───────────────────────────────────────────────────

    def _scan_git_history(self) -> list[dict]:
        findings = []
        try:
            result = subprocess.run(
                ['git', 'log', '--all', '-p', '--follow', '--', '*.env', '*.py', '*.js', '*.html'],
                cwd=str(PROJECT_ROOT),
                capture_output=True, text=True, timeout=30,
            )
            history = result.stdout
        except Exception as e:
            self.log_warn(f"Security: git history scan failed: {e}")
            return findings

        for pattern, label in SECRET_PATTERNS:
            for m in re.finditer(pattern, history):
                context_start = max(0, m.start() - 100)
                context       = history[context_start:m.start() + 60]
                commit_match  = re.search(r'commit ([a-f0-9]{8})', context)
                commit        = commit_match.group(1) if commit_match else 'unknown'
                findings.append({
                    "severity":    "critical",
                    "category":    "git_history_leak",
                    "title":       f"{label} found in git history",
                    "location":    f"commit {commit}",
                    "detail":      f"Value: {m.group()[:30]}…",
                    "fix":         "Run git-filter-repo to purge from history. Rotate credential immediately.",
                })
        return findings

    # ── 3. Gitignore audit ────────────────────────────────────────────────────

    def _audit_gitignore(self) -> list[dict]:
        findings = []
        must_ignore = [
            ('builder/.env', '.env file with all API keys'),
            ('ops.html',     'ops.html contains hardcoded Anthropic API key'),
            ('admin.html',   'admin.html password-protected admin panel'),
            ('*.db',         'SQLite database files'),
            ('*.db-wal',     'SQLite WAL files'),
            ('*.db-shm',     'SQLite SHM files'),
        ]
        try:
            gi = (PROJECT_ROOT / '.gitignore').read_text()
        except Exception:
            findings.append({
                "severity": "critical",
                "category": "config",
                "title":    "No .gitignore file found",
                "location": ".gitignore",
                "detail":   "All files are at risk of being committed",
                "fix":      "Create a .gitignore immediately",
            })
            return findings

        for pattern, reason in must_ignore:
            base = pattern.lstrip('*').lstrip('.')
            if base not in gi and pattern not in gi:
                findings.append({
                    "severity": "high",
                    "category": "config",
                    "title":    f"{pattern} not in .gitignore",
                    "location": ".gitignore",
                    "detail":   reason,
                    "fix":      f"Add '{pattern}' to .gitignore",
                })
        return findings

    # ── 4. Endpoint auth testing ──────────────────────────────────────────────

    def _test_endpoints(self) -> list[dict]:
        findings = []
        base = 'http://localhost:8080'

        for endpoint in PROTECTED_ENDPOINTS:
            url = base + endpoint
            try:
                req = urllib.request.Request(url, method='GET')
                with urllib.request.urlopen(req, timeout=3) as r:
                    # If we get a 200 without auth — it's unprotected
                    if r.status == 200:
                        findings.append({
                            "severity": "critical",
                            "category": "auth_bypass",
                            "title":    f"Unauthenticated access to {endpoint}",
                            "location": f"GET {endpoint}",
                            "detail":   f"Returned HTTP 200 without credentials",
                            "fix":      "Add Depends(verify_auth) to this FastAPI route",
                        })
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    pass  # Correct — auth required
                else:
                    self.log_warn(f"Security: endpoint {endpoint} returned {e.code}")
            except Exception:
                pass  # Dashboard not running — skip

        return findings

    # ── 5. Dependency CVE check ───────────────────────────────────────────────

    def _check_dependencies(self) -> list[dict]:
        findings = []
        req_file = PROJECT_ROOT / 'dashboard' / 'requirements.txt'
        if not req_file.exists():
            return findings

        # Try pip-audit first
        try:
            result = subprocess.run(
                ['pip-audit', '--requirement', str(req_file), '--format', 'json'],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode in (0, 1):
                try:
                    audit = json.loads(result.stdout)
                    for dep in audit:
                        for vuln in dep.get('vulns', []):
                            findings.append({
                                "severity": "high",
                                "category": "dependency_cve",
                                "title":    f"CVE in {dep['name']} {dep['version']}: {vuln['id']}",
                                "location": "dashboard/requirements.txt",
                                "detail":   vuln.get('description', '')[:200],
                                "fix":      f"Upgrade {dep['name']} to fix {vuln['id']}",
                            })
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            # pip-audit not installed — try safety
            try:
                result = subprocess.run(
                    ['safety', 'check', '-r', str(req_file), '--json'],
                    capture_output=True, text=True, timeout=60,
                )
                if result.stdout:
                    try:
                        vulns = json.loads(result.stdout)
                        for v in (vulns or []):
                            findings.append({
                                "severity": "high",
                                "category": "dependency_cve",
                                "title":    f"CVE: {v[0]} {v[1]} — {v[4]}",
                                "location": "dashboard/requirements.txt",
                                "detail":   v[3][:200] if len(v) > 3 else '',
                                "fix":      f"Upgrade {v[0]} to a patched version",
                            })
                    except Exception:
                        pass
            except FileNotFoundError:
                self.log_warn("Security: neither pip-audit nor safety installed — skipping CVE check")

        return findings

    # ── 6. File permissions ───────────────────────────────────────────────────

    def _check_permissions(self) -> list[dict]:
        findings = []
        sensitive = [
            PROJECT_ROOT / 'builder' / '.env',
            PROJECT_ROOT / 'dashboard' / 'iys_agents.db',
        ]
        for fp in sensitive:
            if not fp.exists():
                continue
            mode = fp.stat().st_mode & 0o777
            if mode & 0o044:  # group/other readable
                findings.append({
                    "severity": "medium",
                    "category": "permissions",
                    "title":    f"Sensitive file is world/group readable: {fp.name}",
                    "location": str(fp.relative_to(PROJECT_ROOT)),
                    "detail":   f"Current permissions: {oct(mode)}",
                    "fix":      f"Run: chmod 600 {fp.relative_to(PROJECT_ROOT)}",
                })
        return findings

    # ── 7. Public git exposure ────────────────────────────────────────────────

    def _check_public_exposure(self) -> list[dict]:
        findings = []
        risky_patterns = ['.env', 'ops.html', 'admin.html', '.db', 'secret', 'private']
        try:
            result = subprocess.run(
                ['git', 'ls-files'],
                cwd=str(PROJECT_ROOT),
                capture_output=True, text=True, timeout=10,
            )
            tracked = result.stdout.splitlines()
            for f in tracked:
                for pattern in risky_patterns:
                    if pattern in f.lower():
                        findings.append({
                            "severity": "critical",
                            "category": "public_exposure",
                            "title":    f"Sensitive file tracked by git: {f}",
                            "location": f,
                            "detail":   f"This file is in git and may be pushed to GitHub",
                            "fix":      f"Run: git rm --cached {f} && add to .gitignore",
                        })
                        break
        except Exception as e:
            self.log_warn(f"Security: git ls-files check failed: {e}")
        return findings

    # ── 8. OWASP code review via Claude ──────────────────────────────────────

    def _owasp_review(self) -> list[dict]:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return []
        try:
            import anthropic
        except ImportError:
            return []

        # Read the critical files for review
        code_blocks = []
        for rel_path in OWASP_REVIEW_FILES:
            fp = PROJECT_ROOT / rel_path
            if fp.exists():
                text = fp.read_text(errors='ignore')[:4000]
                code_blocks.append(f"=== {rel_path} ===\n{text}")

        if not code_blocks:
            return []

        code_text = "\n\n".join(code_blocks)

        prompt = f"""You are a senior penetration tester and security code reviewer.
Review the following Python/FastAPI source files for security vulnerabilities.
Focus on: OWASP Top 10, authentication bypass, injection, path traversal,
SSRF, command injection, insecure deserialization, broken access control.

Return ONLY valid JSON — an array of findings:
[
  {{
    "severity": "critical|high|medium|low",
    "category": "one of: injection, auth, exposure, access_control, config, crypto",
    "title": "Short description (max 80 chars)",
    "location": "filename:linerange",
    "detail": "What the vulnerability is and how it could be exploited",
    "fix": "Exact code change or concrete remediation step"
  }}
]

If no issues found, return [].

Source files to review:
{code_text}"""

        try:
            client   = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
            )
            # Get the text block (last block after thinking)
            raw = next(
                (b.text for b in reversed(response.content) if hasattr(b, 'text')),
                ""
            ).strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            findings = json.loads(raw.strip())
            return findings if isinstance(findings, list) else []
        except Exception as e:
            self.log_warn(f"Security: OWASP review failed: {e}")
            return []

    # ── Deep pen test via OpenClaw ────────────────────────────────────────────

    def run_deep_pentest(self, target: str = "full") -> dict:
        """
        Escalate a comprehensive pen test to OpenClaw (Claude Code CLI).
        Claude gets full tool access to read, grep and analyse the codebase.
        Called from the dashboard 'Deep Pen Test' button.
        """
        tid = self.create_task("pentest", f"Deep pen test via OpenClaw — target: {target}")
        self.update_progress(tid, 5)

        prompt = f"""You are a senior penetration tester conducting a self-audit of the IYS Agent System.

Project root: {PROJECT_ROOT}
Target: {target}

Conduct a comprehensive security assessment:

1. READ dashboard/app.py — audit every API endpoint:
   - Does it require authentication?
   - Is input validated and sanitised?
   - Any SQL injection via db.py calls?
   - Any path traversal in file operations?
   - CORS policy — is it too permissive?
   - Rate limiting — are sensitive endpoints rate-limited?

2. READ dashboard/db.py — check all SQL:
   - Any raw string interpolation in SQL queries?
   - Parameterised queries used throughout?
   - Transaction isolation appropriate?

3. READ agents/openclaw.py — check subprocess usage:
   - Is the prompt passed to claude CLI sanitised?
   - Any shell injection possible in the command construction?
   - Timeout and error handling complete?

4. READ agents/leads.py — check email/web operations:
   - Any SSRF risk in URL fetching?
   - Email header injection possible?

5. GREP for: eval(, exec(, os.system(, shell=True — any dangerous patterns?

6. GLOB for any .env files outside the gitignored path

7. Check if iys_agents.db is accessible without authentication

For each finding provide:
- Severity: CRITICAL / HIGH / MEDIUM / LOW / INFO
- File and line number
- Exact vulnerability description
- Proof of concept exploit
- Exact fix (code snippet where possible)

End your report with an overall security score (0-100) and top 3 priority fixes.
Be thorough — this is a real system handling real business data."""

        result = self.escalate_to_openclaw(
            prompt=prompt,
            task_id=tid,
            timeout=300,
            allowed_tools=["Read", "Grep", "Glob", "Bash"],
        )

        if result.get("success"):
            self.complete_task(tid, f"Deep pen test complete — see OpenClaw #{result.get('esc_id')}")
            # Save the pen test output to the security report
            report = {}
            if REPORT_FILE.exists():
                try:
                    report = json.loads(REPORT_FILE.read_text())
                except Exception:
                    pass
            report["last_pentest"] = {
                "date":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "target": target,
                "output": result.get("output", ""),
                "esc_id": result.get("esc_id"),
            }
            REPORT_FILE.write_text(json.dumps(report, indent=2))
        else:
            self.fail_task(tid, f"Deep pen test failed: {result.get('error')}")

        return result

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _calculate_score(self, findings: list[dict]) -> int:
        score = 100
        deductions = {
            "critical": 20,
            "high":     10,
            "medium":    5,
            "low":       2,
        }
        for f in findings:
            score -= deductions.get(f.get("severity", "low"), 2)
        return max(0, score)

    # ── Report ────────────────────────────────────────────────────────────────

    def _save_report(self, findings: list[dict], score: int) -> dict:
        # Load existing to keep pentest history
        existing = {}
        if REPORT_FILE.exists():
            try:
                existing = json.loads(REPORT_FILE.read_text())
            except Exception:
                pass

        report = {
            "date":     datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "score":    score,
            "total":    len(findings),
            "by_severity": {
                "critical": len([f for f in findings if f.get("severity") == "critical"]),
                "high":     len([f for f in findings if f.get("severity") == "high"]),
                "medium":   len([f for f in findings if f.get("severity") == "medium"]),
                "low":      len([f for f in findings if f.get("severity") == "low"]),
            },
            "findings": findings,
            "last_pentest": existing.get("last_pentest"),
        }
        REPORT_FILE.write_text(json.dumps(report, indent=2))
        return report

    def _format_email(self, findings: list[dict]) -> str:
        critical = [f for f in findings if f.get("severity") == "critical"]
        high     = [f for f in findings if f.get("severity") == "high"]
        lines = ["IYS Security Manager — Alert\n"]
        for sev, group in [("CRITICAL", critical), ("HIGH", high)]:
            for f in group:
                lines.append(f"[{sev}] {f['title']}")
                lines.append(f"  Location: {f.get('location','?')}")
                lines.append(f"  Detail:   {f.get('detail','')}")
                lines.append(f"  Fix:      {f.get('fix','')}")
                lines.append("")
        return "\n".join(lines)
