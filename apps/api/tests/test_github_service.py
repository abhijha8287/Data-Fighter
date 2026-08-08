from unittest.mock import MagicMock, patch

import pytest
from github import GithubException

from app.github.service import GitHubService, GitHubServiceError


def _mock_service(repo_mock: MagicMock) -> GitHubService:
    svc = GitHubService(token="fake-token", demo_repo="acme/demo-repo")
    svc._gh = MagicMock()  # type: ignore[attr-defined]
    svc._gh.get_repo.return_value = repo_mock  # type: ignore[attr-defined]
    return svc


@pytest.fixture
def repo():
    r = MagicMock()
    r.full_name = "acme/demo-repo"
    r.default_branch = "main"
    return r


async def test_get_repository(repo):
    svc = _mock_service(repo)
    result = await svc.get_repository()
    assert result == {"full_name": "acme/demo-repo", "default_branch": "main"}


async def test_get_repository_error_wraps_github_exception():
    svc = GitHubService(token="fake-token", demo_repo="acme/demo-repo")
    svc._gh = MagicMock()  # type: ignore[attr-defined]
    svc._gh.get_repo.side_effect = GithubException(404, {"message": "not found"}, {})  # type: ignore[attr-defined]
    with pytest.raises(GitHubServiceError):
        await svc.get_repository()


async def test_search_code_returns_match_on_first_attempt(repo):
    svc = _mock_service(repo)
    item = MagicMock()
    item.path = "customer_metrics.sql"
    item.decoded_content = b"SELECT customer_email FROM analytics.customers"
    svc._gh.search_code.return_value = [item]  # type: ignore[attr-defined]

    results = await svc.search_code("customer_email")

    assert results == [{"path": "customer_metrics.sql", "matched_line": "SELECT customer_email FROM analytics.customers"}]
    assert svc._gh.search_code.call_count == 1  # type: ignore[attr-defined]


async def test_search_code_retries_on_empty_then_succeeds(repo):
    svc = _mock_service(repo)
    item = MagicMock()
    item.path = "customer_metrics.sql"
    item.decoded_content = b"SELECT customer_email FROM analytics.customers"
    svc._gh.search_code.side_effect = [[], [], [item]]  # type: ignore[attr-defined]

    with patch("app.github.service.asyncio.sleep", return_value=None) as mock_sleep:
        results = await svc.search_code("customer_email", max_attempts=3, backoff_seconds=5.0)

    assert len(results) == 1
    assert svc._gh.search_code.call_count == 3  # type: ignore[attr-defined]
    assert mock_sleep.call_count == 2


async def test_search_code_gives_up_after_max_attempts_returns_empty(repo):
    svc = _mock_service(repo)
    svc._gh.search_code.return_value = []  # type: ignore[attr-defined]

    with patch("app.github.service.asyncio.sleep", return_value=None):
        results = await svc.search_code("nonexistent", max_attempts=3, backoff_seconds=5.0)

    assert results == []
    assert svc._gh.search_code.call_count == 3  # type: ignore[attr-defined]


async def test_search_code_raises_service_error_on_api_failure(repo):
    svc = _mock_service(repo)
    svc._gh.search_code.side_effect = GithubException(403, {"message": "rate limited"}, {})  # type: ignore[attr-defined]

    with pytest.raises(GitHubServiceError):
        await svc.search_code("customer_email")


async def test_create_branch(repo):
    svc = _mock_service(repo)
    base_ref = MagicMock()
    base_ref.object.sha = "abc123"
    repo.get_git_ref.return_value = base_ref

    branch_name = await svc.create_branch("fix/customer-email")

    assert branch_name == "fix/customer-email"
    repo.create_git_ref.assert_called_once_with(ref="refs/heads/fix/customer-email", sha="abc123")


async def test_create_branch_error(repo):
    svc = _mock_service(repo)
    repo.get_git_ref.side_effect = GithubException(404, {"message": "no base"}, {})

    with pytest.raises(GitHubServiceError):
        await svc.create_branch("fix/customer-email")


async def test_update_file_updates_existing_file(repo):
    svc = _mock_service(repo)
    existing = MagicMock()
    existing.sha = "filesha123"
    repo.get_contents.return_value = existing
    commit_result = {"commit": MagicMock(sha="commitsha456")}
    repo.update_file.return_value = commit_result

    result = await svc.update_file("customer_metrics.sql", "SELECT 1;", "fix/branch", "fix: remove customer_email")

    assert result == {"path": "customer_metrics.sql", "commit_sha": "commitsha456"}
    repo.update_file.assert_called_once()


async def test_update_file_creates_new_file_when_not_found(repo):
    svc = _mock_service(repo)
    repo.get_contents.side_effect = GithubException(404, {"message": "not found"}, {})
    commit_result = {"commit": MagicMock(sha="newcommitsha")}
    repo.create_file.return_value = commit_result

    result = await svc.update_file("new_file.sql", "SELECT 1;", "fix/branch", "add file")

    assert result == {"path": "new_file.sql", "commit_sha": "newcommitsha"}
    repo.create_file.assert_called_once()


async def test_create_pull_request(repo):
    svc = _mock_service(repo)
    pr = MagicMock()
    pr.html_url = "https://github.com/acme/demo-repo/pull/42"
    repo.create_pull.return_value = pr

    url = await svc.create_pull_request("fix: remediate incident", "body text", "fix/branch")

    assert url == "https://github.com/acme/demo-repo/pull/42"


async def test_create_pull_request_error(repo):
    svc = _mock_service(repo)
    repo.create_pull.side_effect = GithubException(422, {"message": "conflict"}, {})

    with pytest.raises(GitHubServiceError):
        await svc.create_pull_request("title", "body", "branch")
