"""
GitHubReport.py

A small utility module for generating per-student GitHub activity reports
for a GitHub organization over a specified date range.

Primary use cases:
- Course grading
- Participation auditing
- Student reflection and feedback

Design goals:
- Readable, explicit code
- Minimal magic
- Easy to extend in a Jupyter or scripting environment
"""

from datetime import datetime
from typing import Dict, List

import requests
import pandas as pd
import matplotlib.pyplot as plt


class Group:
    """
    Represents a GitHub organization ("group") and a reporting window.

    A Group object owns:
    - Organization name
    - Authentication token
    - Date range (semester)
    - Repository list

    Example
    -------
    >>> group = Group("see-insight", token, start, end)
    >>> summary = group.student("colbrydi")
    """


    def __init__(
        self,
        org: str,
        token: str,
        semester_start: datetime,
        semester_end: datetime,
        extra_repos: List[str] | None = None,
    ) -> None:

        """
        Initialize a Group.

        Parameters
        ----------
        org : str
            GitHub organization name (e.g. "see-insight")
        token : str
            GitHub Personal Access Token
        semester_start : datetime
            Start of reporting window (timezone-aware)
        semester_end : datetime
            End of reporting window (timezone-aware)
        """
        self.org = org
        self.semester_start = semester_start
        self.semester_end = semester_end
    
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        self.extra_repos = extra_repos or []
        
        self.repos = self._load_repositories()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    
    def _load_single_repository(self, full_name: str) -> dict:
        """
        Load metadata for a single GitHub repository given 'owner/repo'.
        """
        url = f"https://api.github.com/repos/{full_name}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()  
    
    @staticmethod
    def _iso(dt: datetime) -> str:
        """
        Convert datetime to GitHub-compatible ISO string.
        """
        return dt.isoformat().replace("+00:00", "Z")

    def _github_get_all(self, url: str, params: dict = None) -> List[dict]:
        """
        GET all pages from a GitHub REST endpoint.

        Handles GitHub pagination automatically.

        Parameters
        ----------
        url : str
            Base GitHub API endpoint
        params : dict, optional
            Query parameters for first request

        Returns
        -------
        List[dict]
            Aggregated JSON responses
        """
        results: List[dict] = []

        while url:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            results.extend(response.json())

            url = response.links.get("next", {}).get("url")
            params = None  # only needed for first request

        return results


    def _load_repositories(self) -> List[dict]:
        """
        Load all repositories in the organization, plus any explicitly
        provided external repositories.
        """
        repos: List[dict] = []
    
        # --- Organization repositories ---
        org_url = f"https://api.github.com/orgs/{self.org}/repos"
        repos.extend(
            self._github_get_all(
                org_url,
                params={"type": "all", "per_page": 100},
            )
        )
    
        # --- Explicitly included extra repositories ---
        for repo_name in self.extra_repos:
            print(f"Including external repo: {repo_name}")
            repos.append(self._load_single_repository(repo_name))
    
        # --- Deduplicate by full_name ---
        unique = {}
        for repo in repos:
            unique[repo["full_name"]] = repo
    
        return list(unique.values())
    
    # ------------------------------------------------------------------
    # GitHub queries (scoped per repository)
    # ------------------------------------------------------------------

    def members(self):
        members_url = f"https://api.github.com/orgs/{self.org}/members"
        members = self._github_get_all(
            members_url,
            params={"per_page": 100}
        )
        return members
    
    def _get_user_commits(
        self, repo_full_name: str, username: str
    ) -> List[dict]:
        """
        Retrieve commits authored by a user within the semester window.
        """
        url = f"https://api.github.com/repos/{repo_full_name}/commits"
        return self._github_get_all(
            url,
            params={
                "author": username,
                "since": self._iso(self.semester_start),
                "until": self._iso(self.semester_end),
                "per_page": 100,
            },
        )

    def _get_commit_stats(
        self, repo_full_name: str, sha: str
    ) -> tuple[int, int]:
        """
        Retrieve line addition/deletion statistics for a single commit.
        """
        url = f"https://api.github.com/repos/{repo_full_name}/commits/{sha}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        stats = response.json().get("stats", {})
        return stats.get("additions", 0), stats.get("deletions", 0)

    def _get_user_issues(
        self, repo_full_name: str, username: str
    ) -> List[dict]:
        """
        Retrieve issues *opened* by a user within the semester window.
        """
        url = f"https://api.github.com/repos/{repo_full_name}/issues"
        raw_issues = self._github_get_all(
            url,
            params={
                "state": "all",
                "since": self._iso(self.semester_start),
                "per_page": 100,
            },
        )

        issues: List[dict] = []

        for issue in raw_issues:
            if "pull_request" in issue:
                continue

            if issue.get("user", {}).get("login") != username:
                continue

            created_at = datetime.fromisoformat(
                issue["created_at"].replace("Z", "+00:00")
            )

            if not (self.semester_start <= created_at <= self.semester_end):
                continue

            issues.append(
                {
                    "number": issue["number"],
                    "title": issue["title"],
                    "created_at": issue["created_at"],
                    "closed_at": issue.get("closed_at"),
                    "labels": [label["name"] for label in issue.get("labels", [])],
                }
            )

        return issues

    def _get_user_pull_requests(
        self, repo_full_name: str, username: str
    ) -> List[dict]:
        """
        Retrieve pull requests opened by a user within the semester window.
        """
        url = f"https://api.github.com/repos/{repo_full_name}/pulls"
        raw_prs = self._github_get_all(
            url,
            params={"state": "all", "per_page": 100},
        )

        prs: List[dict] = []

        for pr in raw_prs:
            if pr.get("user", {}).get("login") != username:
                continue

            created_at = datetime.fromisoformat(
                pr["created_at"].replace("Z", "+00:00")
            )

            if not (self.semester_start <= created_at <= self.semester_end):
                continue

            prs.append(
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "created_at": pr["created_at"],
                    "merged_at": pr["merged_at"],
                }
            )

        return prs


    def plot_student_activity_calendar(self, activity: dict) -> None:
        """
        Plot a GitHub-style activity calendar for a student using
        the group's semester start and end dates.
        """
        plot_semester_activity_calendar(
            activity,
            self.semester_start,
            self.semester_end,
        )
    
    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_user_avatar_url(self, username: str) -> str:
        """
        Return the avatar URL for a GitHub user.
        """
        url = f"https://api.github.com/users/{username}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()["avatar_url"]
    
    def student(self, username: str) -> Dict:
        """
        Collect and aggregate GitHub activity for a single student.

        Returns a structured dictionary suitable for:
        - Markdown rendering
        - Visualization
        - Further analysis
        """

        avitar = self.get_user_avatar_url(username)
        
        summary = {
            "username": username,
            "avitar": avitar,
            "commits": 0,
            "lines_added": 0,
            "lines_deleted": 0,
            "issues_opened": 0,
            "pull_requests_opened": 0,
            "pull_requests_merged": 0,
            "per_repo": {},
        }

        for repo in self.repos:
            repo_name = repo["full_name"]
            print(f"{repo_name}")

            repo_record = {
                "commits": 0,
                "lines_added": 0,
                "lines_deleted": 0,
                "issues_opened": 0,
                "pull_requests_opened": 0,
                "pull_requests_merged": 0,
                "commit_messages": [],
                "issue_context": [],
                "pr_context": [],
            }

            # ---- Commits ----
            commits = self._get_user_commits(repo_name, username)
            repo_record["commits"] = len(commits)

            for commit in commits:
                additions, deletions = self._get_commit_stats(
                    repo_name, commit["sha"]
                )
                repo_record["lines_added"] += additions
                repo_record["lines_deleted"] += deletions
                repo_record["commit_messages"].append(
                    {
                        "sha": commit["sha"],
                        "date": commit["commit"]["author"]["date"],
                        "message": commit["commit"]["message"].splitlines()[0],
                    }
                )

            # ---- Issues ----
            issues = self._get_user_issues(repo_name, username)
            repo_record["issues_opened"] = len(issues)
            repo_record["issue_context"] = issues

            # ---- Pull requests ----
            prs = self._get_user_pull_requests(repo_name, username)
            repo_record["pull_requests_opened"] = len(prs)
            repo_record["pull_requests_merged"] = sum(
                1 for pr in prs if pr.get("merged_at")
            )
            repo_record["pr_context"] = prs

            if any(
                [
                    repo_record["commits"],
                    repo_record["issues_opened"],
                    repo_record["pull_requests_opened"],
                ]
            ):
                summary["per_repo"][repo_name] = repo_record

            # ---- Aggregate totals ----
            summary["commits"] += repo_record["commits"]
            summary["lines_added"] += repo_record["lines_added"]
            summary["lines_deleted"] += repo_record["lines_deleted"]
            summary["issues_opened"] += repo_record["issues_opened"]
            summary["pull_requests_opened"] += repo_record["pull_requests_opened"]
            summary["pull_requests_merged"] += repo_record[
                "pull_requests_merged"
            ]

        return summary



# ----------------------------------------------------------------------
# Presentation helpers (kept functional on purpose)
# ----------------------------------------------------------------------




def render_markdown(activity: Dict) -> str:
    """
    Render a student activity summary as Markdown.
    """
    lines: List[str] = []
    lines.append(f"![{activity['username']}]({activity['avitar']})")
    lines.append(f"# GitHub Activity Report: `{activity['username']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Commits: {activity['commits']}")
    lines.append(f"- Lines added: {activity['lines_added']}")
    lines.append(f"- Lines deleted: {activity['lines_deleted']}")
    lines.append(f"- Issues opened: {activity['issues_opened']}")
    lines.append(f"- Pull requests opened: {activity['pull_requests_opened']}")
    lines.append(f"- Pull requests merged: {activity['pull_requests_merged']}")
    lines.append("")

    lines.append("## Activity by Repository")
    lines.append("")

    for repo, data in activity["per_repo"].items():
        lines.append(f"### `{repo}`")
        lines.append("")
        lines.append(f"- Commits: {data['commits']}")
        lines.append(f"- Issues opened: {data['issues_opened']}")
        lines.append("")

        if data["commit_messages"]:
            lines.append("**Commits:**\n")
            for commit in data["commit_messages"]:
                lines.append(
                    f"- {commit['date'][:10]} — {commit['message']}"
                )
            lines.append("")

        if data["issue_context"]:
            lines.append("**Issues:**\n")
            for issue in data["issue_context"]:
                lines.append(f"- {issue['number']} — {issue['title']}")
            lines.append("")

    return "\n".join(lines)


def plot_semester_activity_calendar(
    activity: dict,
    semester_start: datetime,
    semester_end: datetime,
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

    start = pd.to_datetime(semester_start)
    end = pd.to_datetime(semester_end)

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
        f"Semester GitHub Activity Heatmap: {activity['username']}"
    )

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Activity Count")

    plt.tight_layout()