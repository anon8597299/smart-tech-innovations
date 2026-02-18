"""
github_client.py — Pushes generated customer site files to GitHub via a
single Git Tree commit (one commit per customer, not one per file).

Requires:
    GITHUB_PAT  — Personal Access Token (repo scope) in .env
    pip install PyGithub python-dotenv
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from github import Github, GithubException

load_dotenv()

REPO_NAME = "anon8597299/smart-tech-innovations"


def get_github_client() -> Github:
    pat = os.getenv("GITHUB_PAT")
    if not pat:
        raise EnvironmentError(
            "GITHUB_PAT not set. Copy builder/.env.example to builder/.env and add your token."
        )
    return Github(pat)


def push_customer_site(slug: str, files: dict[str, str], commit_message: str = None) -> str:
    """
    Push all customer site files in a single Git Tree commit.

    Args:
        slug:           URL-safe customer identifier, e.g. "smiths-plumbing"
        files:          Dict mapping relative paths (within the customer dir)
                        to rendered HTML/CSS content strings.
                        e.g. {"index.html": "<html>...", "styles.css": "..."}
        commit_message: Optional commit message override.

    Returns:
        The live GitHub Pages URL for the customer's site.
    """
    gh = get_github_client()
    repo = gh.get_repo(REPO_NAME)

    base_path = f"customers/{slug}"
    branch = repo.default_branch
    ref = repo.get_git_ref(f"heads/{branch}")
    base_commit_sha = ref.object.sha
    base_tree_sha = repo.get_git_commit(base_commit_sha).tree.sha

    print(f"  Pushing to {REPO_NAME} / {base_path}/ ...")

    # Build the list of tree elements
    tree_elements = []
    for rel_path, content in files.items():
        full_path = f"{base_path}/{rel_path}"
        blob = repo.create_git_blob(content, "utf-8")
        tree_elements.append({
            "path": full_path,
            "mode": "100644",
            "type": "blob",
            "sha": blob.sha,
        })

    # Create new tree
    new_tree = repo.create_git_tree(tree_elements, base_tree=repo.get_git_tree(base_tree_sha))

    # Create commit
    if commit_message is None:
        commit_message = f"Add customer site: {slug}"

    new_commit = repo.create_git_commit(
        message=commit_message,
        tree=new_tree,
        parents=[repo.get_git_commit(base_commit_sha)],
    )

    # Update branch ref
    ref.edit(new_commit.sha)

    live_url = f"https://anon8597299.github.io/smart-tech-innovations/customers/{slug}/"
    print(f"  ✅ Pushed {len(files)} file(s) in one commit.")
    print(f"  🌐 Live in ~90 seconds: {live_url}")

    return live_url
