"""GitHubService — thin wrapper over the GitHub REST API (via PyGithub),
scoped to GITHUB_DEMO_REPO from env. All calls operate on that single repo —
no user-supplied repo/branch targets, closing off the injection surface a
more general client would have.

search_code() is called ONCE per incident (by investigate_root_cause) and
its result is cached on IncidentState (state["affected_files"]).
generate_fix and validate_fix's file-path-mapping check both READ that
cached result — they do NOT call search_code() again. This guarantees
root-cause claims, the generated fix, and the validation check all
reference the exact same file set for one incident, never independently
re-derived (which could silently disagree).
"""

from __future__ import annotations

import asyncio

from github import Auth, Github, GithubException
from github.Repository import Repository


class GitHubServiceError(Exception):
    """Raised on unrecoverable GitHub API failures (auth, rate limit,
    branch conflict). Callers (LangGraph nodes) catch this and record it on
    IncidentState rather than letting it propagate as a raw exception."""


class GitHubService:
    def __init__(self, token: str, demo_repo: str) -> None:
        self._gh = Github(auth=Auth.Token(token))
        self._repo_name = demo_repo
        self._repo: Repository | None = None

    def _get_repo(self) -> Repository:
        if self._repo is None:
            try:
                self._repo = self._gh.get_repo(self._repo_name)
            except GithubException as exc:
                raise GitHubServiceError(f"cannot access repo {self._repo_name}: {exc}") from exc
        return self._repo

    async def get_repository(self) -> dict:
        repo = await asyncio.to_thread(self._get_repo)
        return {"full_name": repo.full_name, "default_branch": repo.default_branch}

    async def search_code(
        self, query: str, *, max_attempts: int = 3, backoff_seconds: float = 5.0
    ) -> list[dict]:
        """Returns [{"path": str, "matched_line": str}, ...].

        GitHub's code search index has real propagation lag after a push —
        if the demo repo was seeded shortly before this call, results can
        come back empty/stale. Retries with backoff rather than trusting
        the first response; still returns [] (not an exception) if every
        attempt comes up empty, since "no matches" is sometimes the
        correct, real answer.
        """
        repo = await asyncio.to_thread(self._get_repo)

        def _search() -> list[dict]:
            results = self._gh.search_code(f"{query} repo:{repo.full_name}")
            matches = []
            for item in results:
                matched_line = query
                try:
                    content = item.decoded_content.decode("utf-8")
                    for line in content.splitlines():
                        if query in line:
                            matched_line = line.strip()
                            break
                except Exception:
                    pass
                matches.append({"path": item.path, "matched_line": matched_line})
            return matches

        last_result: list[dict] = []
        for attempt in range(max_attempts):
            try:
                last_result = await asyncio.to_thread(_search)
            except GithubException as exc:
                raise GitHubServiceError(f"search_code failed: {exc}") from exc
            if last_result:
                return last_result
            if attempt < max_attempts - 1:
                await asyncio.sleep(backoff_seconds)
        return last_result

    async def get_file_content(self, path: str, ref: str | None = None) -> str:
        """Reads the current content of a file at `ref` (default branch if
        unset). Not part of the original pinned interface sketch, but a
        required primitive: generate_fix cannot produce an "after" version
        of a file without reading the "before" content first."""
        repo = await asyncio.to_thread(self._get_repo)

        def _get() -> str:
            content_file = repo.get_contents(path, ref=ref) if ref else repo.get_contents(path)
            return content_file.decoded_content.decode("utf-8")  # type: ignore[union-attr]

        try:
            return await asyncio.to_thread(_get)
        except GithubException as exc:
            raise GitHubServiceError(f"get_file_content({path}) failed: {exc}") from exc

    async def create_branch(self, name: str, base: str | None = None) -> str:
        repo = await asyncio.to_thread(self._get_repo)

        def _create() -> str:
            base_branch = base or repo.default_branch
            base_ref = repo.get_git_ref(f"heads/{base_branch}")
            repo.create_git_ref(ref=f"refs/heads/{name}", sha=base_ref.object.sha)
            return name

        try:
            return await asyncio.to_thread(_create)
        except GithubException as exc:
            raise GitHubServiceError(f"create_branch({name}) failed: {exc}") from exc

    async def update_file(self, path: str, content: str, branch: str, message: str) -> dict:
        repo = await asyncio.to_thread(self._get_repo)

        def _update() -> dict:
            try:
                existing = repo.get_contents(path, ref=branch)
                result = repo.update_file(
                    path, message, content, existing.sha, branch=branch  # type: ignore[union-attr]
                )
            except GithubException as exc:
                if exc.status == 404:
                    result = repo.create_file(path, message, content, branch=branch)
                else:
                    raise
            return {"path": path, "commit_sha": result["commit"].sha}

        try:
            return await asyncio.to_thread(_update)
        except GithubException as exc:
            raise GitHubServiceError(f"update_file({path}) failed: {exc}") from exc

    async def create_pull_request(
        self, title: str, body: str, head: str, base: str | None = None
    ) -> str:
        repo = await asyncio.to_thread(self._get_repo)

        def _create() -> str:
            base_branch = base or repo.default_branch
            pr = repo.create_pull(title=title, body=body, head=head, base=base_branch)
            return pr.html_url

        try:
            return await asyncio.to_thread(_create)
        except GithubException as exc:
            raise GitHubServiceError(f"create_pull_request failed: {exc}") from exc
