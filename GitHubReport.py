"""
GitReport.py

Platform-agnostic utilities for generating per-student Git
activity reports over a specified date range.

Currently implemented:
- GitHubProvider

Planned:
- GitLabProvider (see TODO markers)

Primary use cases:
- Course grading
- Participation auditing
- Student reflection and feedback
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import requests
import pandas as pd
import matplotlib.pyplot as plt


# ======================================================================
# Provider abstraction
# ======================================================================

class ProviderBase:
    """
    Abstract interface for a Git hosting provider.

    A Provider is responsible for:
    - Authentication
    - API calls
    - Returning normalized data structures

    Group and reporting code should NEVER depend on
    whether the provider is GitHub, GitLab, etc.
    """
    providerurl = ""
    
    def list_repositories(self) -> List[dict]:
        raise NotImplementedError

    def list_members(self) -> List[dict]:
        raise NotImplementedError

    def get_user_commits(
        self, repo: dict, username: str,
        start: datetime, end: datetime
    ) -> List[dict]:
        raise NotImplementedError

    def get_commit_stats(self, repo: dict, sha: str) -> tuple[int, int]:
        raise NotImplementedError

    def get_user_issues(
        self, repo: dict, username: str,
        start: datetime, end: datetime
    ) -> List[dict]:
        raise NotImplementedError

    def get_user_merge_requests(
        self, repo: dict, username: str,
        start: datetime, end: datetime
    ) -> List[dict]:
        raise NotImplementedError

    def get_user_avatar_url(self, username: str) -> Optional[str]:
        return None


# ======================================================================
# GitHub provider implementation
# ======================================================================

class GitHubProvider(ProviderBase):
    """
    GitHub REST API implementation of ProviderBase.
    """

    def __init__(self, org: str, token: str, extra_repos: Optional[List[str]] = None) -> None:
        self.org = org
        self.providerurl = "GitHub.com"
        self.extra_repos = extra_repos or []

        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }

        self.repos = self._load_repositories()

    # ------------------ helpers ------------------

    @staticmethod
    def _iso(dt: datetime) -> str:
        return dt.isoformat().replace("+00:00", "Z")

    def _get_all(self, url: str, params: dict = None) -> List[dict]:
        results: List[dict] = []
        while url:
            resp = requests.get(url, headers=self.headers, params=params)
            resp.raise_for_status()
            results.extend(resp.json())
            url = resp.links.get("next", {}).get("url")
            params = None
        return results

    # ------------------ GitHub API ------------------

    def _load_single_repository(self, full_name: str) -> dict:
        url = f"https://api.github.com/repos/{full_name}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()
    
    def _load_repositories(self) -> List[dict]:
        """
        Load all repositories visible to the organization, plus any explicitly
        provided extra repositories, and normalize them to a canonical schema.
        """
        repos: List[dict] = []
    
        # --- Organization repositories ---
        org_url = f"https://api.github.com/orgs/{self.org}/repos"
        raw_repos = self._get_all(
            org_url,
            params={"per_page": 100, "type": "all"},
        )
    
        repos.extend(self._normalize_repo(r) for r in raw_repos)
    
        # --- Explicitly included external repositories ---
        for repo_name in self.extra_repos:
            raw_repo = self._load_single_repository(repo_name)
            repos.append(self._normalize_repo(raw_repo))
    
        # --- Deduplicate by canonical full_name ---
        unique = {r["full_name"]: r for r in repos}
    
        return list(unique.values())
    
    def _normalize_repo(self, repo: dict) -> dict:
        """
        Normalize a GitHub repository object to the canonical schema.
        """
        return {
            "id": repo["full_name"],                   # GitHub uses owner/name
            "name": repo["name"],
            "full_name": repo["full_name"],
            "web_url": repo.get("html_url"),
            "provider": "github",
            "raw": repo,
        }
    
    # ------------------ ProviderBase API ------------------

    def list_repositories(self) -> List[dict]:
        return self.repos

    def list_members(self) -> List[dict]:
        url = f"https://api.github.com/orgs/{self.org}/members"
        return self._get_all(url, params={"per_page": 100})

    def get_user_commits(self, repo: dict, username: str, start: datetime, end: datetime) -> List[dict]:
        url = f"https://api.github.com/repos/{repo['full_name']}/commits"
        return self._get_all(
            url,
            params={
                "author": username,
                "since": self._iso(start),
                "until": self._iso(end),
                "per_page": 100,
            },
        )

    def get_commit_stats(self, repo: dict, sha: str) -> tuple[int, int]:
        url = f"https://api.github.com/repos/{repo['full_name']}/commits/{sha}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        stats = resp.json().get("stats", {})
        return stats.get("additions", 0), stats.get("deletions", 0)

    def get_user_issues(self, repo: dict, username: str, start: datetime, end: datetime) -> List[dict]:
        url = f"https://api.github.com/repos/{repo['full_name']}/issues"
        raw = self._get_all(url, params={"state": "all", "per_page": 100})

        issues: List[dict] = []
        for i in raw:
            if "pull_request" in i:
                continue
            if i.get("user", {}).get("login") != username:
                continue

            created = datetime.fromisoformat(i["created_at"].replace("Z", "+00:00"))
            if not (start <= created <= end):
                continue

            issues.append({
                "number": i["number"],
                "title": i["title"],
                "created_at": i["created_at"],
            })

        return issues

    def get_user_merge_requests(self, repo: dict, username: str, start: datetime, end: datetime) -> List[dict]:
        url = f"https://api.github.com/repos/{repo['full_name']}/pulls"
        raw = self._get_all(url, params={"state": "all", "per_page": 100})

        prs: List[dict] = []
        for pr in raw:
            if pr.get("user", {}).get("login") != username:
                continue

            created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
            if not (start <= created <= end):
                continue

            prs.append({
                "number": pr["number"],
                "title": pr["title"],
                "created_at": pr["created_at"],
                "merged_at": pr.get("merged_at"),
            })

        return prs

    def get_user_avatar_url(self, username: str) -> str:
        url = f"https://api.github.com/users/{username}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()["avatar_url"]

    # TODO: GitLabProvider will implement same interface
    # TODO: GitLab uses project IDs, merge_requests, and PRIVATE-TOKEN auth


# ======================================================================
# GitLab provider implementation
# ======================================================================

class GitLabProvider(ProviderBase):
    """
    GitLab REST API implementation of ProviderBase.

    NOTE:
    - Uses project IDs internally
    - Assumes self.base_url points to your institution's GitLab
    """

    def __init__(
        self,
        base_url: str,
        group_path: str,
        token: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.group_path = group_path

        self.headers = {
            "PRIVATE-TOKEN": token,
        }
        self.providerurl = "gitlab.msu.edu"
        
        # ✅ REQUIRED: resolve numeric group ID once
        self.group_id = self._resolve_group_id()

        # ✅ Load projects using numeric ID
        self.repos = self._load_projects()
        
    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> list[dict]:
        url = f"{self.base_url}{path}"
        results: list[dict] = []

        while url:
            resp = requests.get(url, headers=self.headers, params=params)
            resp.raise_for_status()

            results.extend(resp.json())

            # GitLab pagination
            next_page = resp.headers.get("X-Next-Page")
            if next_page:
                params = params or {}
                params["page"] = next_page
                url = f"{self.base_url}{path}"
            else:
                url = None

        return results
        
    def _normalize_repo(self, project: dict) -> dict:
        """
        Normalize a GitLab project object to the canonical schema.
        """
        return {
            "id": project["id"],                        # numeric (important)
            "name": project["name"],
            "full_name": project["path_with_namespace"],
            "web_url": project.get("web_url"),
            "provider": "gitlab",
            "raw": project,
        }

    def _resolve_group_id(self) -> int:
        """
        Resolve the numeric GitLab group ID from a group path.
        """
        url = f"{self.base_url}/api/v4/groups/{self.group_path}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()["id"]

    # ------------------------------------------------------------------
    # Required ProviderBase methods
    # ------------------------------------------------------------------

    def list_repositories(self) -> list[dict]:
        return self.repos
    
    def _load_projects(self) -> list[dict]:
        """
        Load all projects in the GitLab group and normalize them
        to the canonical internal repository schema.
        """
        raw_projects = self._get(
            f"/api/v4/groups/{self.group_id}/projects",
            params={"per_page": 100},
        )
    
        projects = [self._normalize_repo(p) for p in raw_projects]
    
        # Deduplicate by canonical full_name (safety, mirrors GitHubProvider)
        unique = {p["full_name"]: p for p in projects}
    
        return list(unique.values())

    def get_user_commits(
        self,
        repo: dict,
        username: str,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """
        Retrieve commits authored by a user within the date window
        and normalize them to the canonical commit schema.
        """
        raw_commits = self._get(
            f"/api/v4/projects/{repo['id']}/repository/commits",
            params={
                "author": username,
                "since": start.isoformat(),
                "until": end.isoformat(),
                "per_page": 100,
            },
        )
    
        commits: list[dict] = []
    
        for c in raw_commits:
            commits.append(
                {
                    # ---- canonical keys expected by Group ----
                    "sha": c["id"],                    # ⬅️ THIS FIXES THE ERROR
                    "commit": {
                        "author": {
                            "date": c["created_at"]
                        },
                        "message": c["message"],
                    },
                    # ---- optional metadata ----
                    "raw": c,
                }
            )
    
        return commits

    def get_commit_stats(self, repo: dict, sha: str) -> tuple[int, int]:
        """
        Retrieve line addition/deletion statistics for a single GitLab commit.
    
        NOTE:
        This endpoint returns a single JSON object (not a list),
        so we do NOT use _get().
        """
        url = f"{self.base_url}/api/v4/projects/{repo['id']}/repository/commits/{sha}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
    
        commit = resp.json()
        stats = commit.get("stats", {})
    
        return stats.get("additions", 0), stats.get("deletions", 0)


    # ------------------------------------------------------------------
    # TODO: issues, merge requests, avatars
    # ------------------------------------------------------------------
    
    def get_user_issues(
        self,
        repo: dict,
        username: str,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """
        Retrieve issues opened by a user within the date window
        for a single GitLab project.
        """
        # GitLab endpoint:
        # GET /projects/:id/issues
        raw_issues = self._get(
            f"/api/v4/projects/{repo['id']}/issues",
            params={
                "state": "all",
                "per_page": 100,
            },
        )
    
        issues: list[dict] = []
    
        for issue in raw_issues:
            # Must be authored by the user
            if issue.get("author", {}).get("username") != username:
                continue
    
            created_at = datetime.fromisoformat(
                issue["created_at"].replace("Z", "+00:00")
            )
    
            # Must be created within semester window
            if not (start <= created_at <= end):
                continue
    
            issues.append(
                {
                    "number": issue["iid"],           # project-local issue number
                    "title": issue["title"],
                    "created_at": issue["created_at"],
                    "closed_at": issue.get("closed_at"),
                }
            )
    
        return issues

    def get_user_merge_requests(
        self,
        repo: dict,
        username: str,
        start: datetime,
        end: datetime,
        ) -> list[dict]:
        """
        Retrieve merge requests opened by a user within the date window.
        """
        # GitLab endpoint:
        # GET /projects/:id/merge_requests
        raw_mrs = self._get(
            f"/api/v4/projects/{repo['id']}/merge_requests",
            params={
                "state": "all",
                "per_page": 100,
            },
        )
        
        mrs: list[dict] = []
        
        for mr in raw_mrs:
            # Must be authored by the user
            if mr.get("author", {}).get("username") != username:
                continue
        
            created_at = datetime.fromisoformat(
                mr["created_at"].replace("Z", "+00:00")
            )
        
            # Must be created within semester window
            if not (start <= created_at <= end):
                continue
        
            mrs.append(
                {
                    "number": mr["iid"],               # project-local MR number
                    "title": mr["title"],
                    "created_at": mr["created_at"],
                    "merged_at": mr.get("merged_at"),
                }
            )
        
        return mrs   

# ======================================================================
# Group: platform-independent reporting logic
# ======================================================================

class Group:
    """
    Semantic reporting layer.

    Owns:
    - provider (GitHub, GitLab, etc.)
    - semester window
    """

    def __init__(self, provider: ProviderBase, start: datetime, end: datetime) -> None:
        self.provider = provider
        self.start = start
        self.end = end
        self.repos = provider.list_repositories()

    def members(self) -> List[dict]:
        return self.provider.list_members()

    def student(self, username: str) -> Dict:
        avatar = self.provider.get_user_avatar_url(username)

        summary = {
            "username": username,
            "avatar": avatar,
            "commits": 0,
            "lines_added": 0,
            "lines_deleted": 0,
            "issues_opened": 0,
            "merge_requests_opened": 0,
            "merge_requests_merged": 0,
            "per_repo": {},
        }

        for repo in self.repos:
            print(repo["full_name"])
            
            record = {
                "commits": 0,
                "lines_added": 0,
                "lines_deleted": 0,
                "issues_opened": 0,
                "merge_requests_opened": 0,
                "merge_requests_merged": 0,
                "commit_messages": [],
                "issue_context": [],
                "mr_context": [],
            }

            commits = self.provider.get_user_commits(repo, username, self.start, self.end)
            record["commits"] = len(commits)

            for c in commits:
                add, delete = self.provider.get_commit_stats(repo, c["sha"])
                record["lines_added"] += add
                record["lines_deleted"] += delete
                record["commit_messages"].append({
                    "date": c["commit"]["author"]["date"],
                    "message": c["commit"]["message"].splitlines()[0],
                })

            issues = self.provider.get_user_issues(repo, username, self.start, self.end)
            record["issues_opened"] = len(issues)
            record["issue_context"] = issues

            mrs = self.provider.get_user_merge_requests(repo, username, self.start, self.end)
            record["merge_requests_opened"] = len(mrs)
            record["merge_requests_merged"] = sum(1 for m in mrs if m.get("merged_at"))
            record["mr_context"] = mrs

            if any(record.values()):
                summary["per_repo"][repo.get("full_name", repo.get("path_with_namespace"))] = record

            for k in ("commits", "lines_added", "lines_deleted", "issues_opened"):
                summary[k] += record[k]

            summary["merge_requests_opened"] += record["merge_requests_opened"]
            summary["merge_requests_merged"] += record["merge_requests_merged"]

        return summary

    def plot_student_activity_calendar(self, activity: dict) -> None:
        """
        Plot a GitHub/GitLab-style activity calendar for a student
        using the group's semester window.
        """
        plot_semester_activity_calendar(
            activity,
            self.start,
            self.end,
        )
# ======================================================================
# Presentation helpers (unchanged, reusable)
# ======================================================================

def render_markdown(activity: Dict) -> str:
    lines: List[str] = []

    if activity.get("avatar"):
        lines.append(f"![{activity['username']}]({activity['avatar']})")

    lines.append(
        f"# {activity.get('group','')} Activity Report for `{activity['username']}`"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Commits: {activity['commits']}")
    lines.append(f"- Lines added: {activity['lines_added']}")
    lines.append(f"- Lines deleted: {activity['lines_deleted']}")
    lines.append(f"- Issues opened: {activity['issues_opened']}")
    lines.append(f"- Merge requests opened: {activity.get('merge_requests_opened', 0)}")
    lines.append(f"- Merge requests merged: {activity.get('merge_requests_merged', 0)}")
    lines.append("")

    lines.append("## Activity by Repository")
    lines.append("")

    for repo, data in activity["per_repo"].items():
        lines.append(f"### `{repo}`")
        lines.append("")
        lines.append(f"- Issues opened: {data['issues_opened']}")
        lines.append(f"- Commits: {data['commits']}")
        lines.append("")

        if data["commit_messages"]:
            lines.append("**Commits:**\n")
            for c in data["commit_messages"]:
                lines.append(f"- {c['date'][:10]} — {c['message']}")
            lines.append("")

        if data["issue_context"]:
            lines.append("**Issues:**\n")
            for i in data["issue_context"]:
                lines.append(f"- issue #{i['number']} — {i['title']}")
            lines.append("")

    return "\n".join(lines)


def plot_semester_activity_calendar(
    activity: Dict,
    start: datetime,
    end: datetime,
) -> None:
    """
    Plot a GitHub-style daily activity heatmap over the semester.

    Activity is aggregated across:
    - commits
    - issues
    - pull requests

    Rows represent weeks (labeled by Monday),
    columns represent days of the week.
    """

    dates = []

    # ---- Collect all activity timestamps ----
    for repo_data in activity["per_repo"].values():
        for c in repo_data.get("commit_messages", []):
            dates.append(pd.to_datetime(c["date"]).normalize())

        for i in repo_data.get("issue_context", []):
            dates.append(pd.to_datetime(i["created_at"]).normalize())

        for pr in repo_data.get("pr_context", []):
            dates.append(pd.to_datetime(pr["created_at"]).normalize())

    if not dates:
        print("No activity to plot.")
        return None

    start = pd.to_datetime(start)
    end = pd.to_datetime(end)

    all_days = pd.date_range(start=start, end=end, freq="D")

    daily_counts = (
        pd.Series(dates)
        .value_counts()
        .reindex(all_days, fill_value=0)
    )

    df = pd.DataFrame({
        "date": all_days,
        "count": daily_counts.values,
    })

    df["weekday"] = df["date"].dt.weekday          # Mon=0 … Sun=6
    df["week"] = ((df["date"] - all_days[0]).dt.days // 7)

    calendar = (
        df.pivot(index="week", columns="weekday", values="count")
        .fillna(0)
    )

    # Monday labels for each week
    week_mondays = [
        (start + pd.Timedelta(days=7 * w)).date()
        for w in calendar.index
    ]

    fig, ax = plt.subplots(
        figsize=(8, max(4, len(calendar) * 0.4))
    )

    im = ax.imshow(calendar, cmap="Greens", aspect="auto")

    ax.set_xticks(range(7))
    ax.set_xticklabels(
        ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    )

    ax.set_yticks(range(len(calendar.index)))
    ax.set_yticklabels(
        [d.strftime("%Y-%m-%d") for d in week_mondays]
    )

    ax.set_xlabel("Day of Week")
    ax.set_ylabel("Week Starting (Monday)")
    ax.set_title(
        f"Semester Activity Heatmap: {activity['username']}"
    )

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Activity Count")

    plt.tight_layout()
    plt.show()