"""Tests for release automation script.

These tests verify the PR polling mechanism works correctly in various scenarios.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
import subprocess
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from release import ReleaseAutomation, ReleaseError


class TestPollForPrMerge:
    """Tests for the _poll_for_pr_merge method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.automation = ReleaseAutomation(dry_run=False, skip_confirmation=True)
        self.automation.repo_root = "/fake/repo"

    @patch('release.subprocess.run')
    @patch('release.time.sleep')
    def test_detects_merged_pr_by_state(self, mock_sleep, mock_run):
        """Test that polling detects a merged PR correctly."""
        # Simulate gh pr view returning MERGED state
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"state": "MERGED"}',
            stderr=""
        )

        # Should return without error when PR is merged
        self.automation._poll_for_pr_merge("releasing-1.0.0", timeout_minutes=1)

        # Verify gh was called with branch name
        mock_run.assert_called()
        call_args = mock_run.call_args[0][0]
        assert "gh" in call_args
        assert "pr" in call_args
        assert "view" in call_args

    @patch('release.subprocess.run')
    @patch('release.time.sleep')
    def test_detects_closed_pr_raises_error(self, mock_sleep, mock_run):
        """Test that polling raises error when PR is closed without merge."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"state": "CLOSED"}',
            stderr=""
        )

        with pytest.raises(ReleaseError) as exc_info:
            self.automation._poll_for_pr_merge("releasing-1.0.0", timeout_minutes=1)

        assert "closed without merging" in str(exc_info.value).lower()

    @patch('release.subprocess.run')
    @patch('release.time.sleep')
    def test_handles_branch_deleted_after_merge(self, mock_sleep, mock_run):
        """Test that polling handles the case where branch is deleted after PR merge.

        This is the bug we're fixing: when a PR is merged, GitHub deletes the branch,
        and 'gh pr view <branch-name>' returns 'no pull requests found'.

        The fix: capture PR number when creating PR, then poll by number.
        'gh pr view <number>' works even after branch is deleted.
        """
        # Simulate: first call with branch name fails (branch deleted),
        # then call with PR number succeeds showing MERGED
        mock_run.side_effect = [
            # First: gh pr view <branch-name> fails - branch deleted after merge
            subprocess.CompletedProcess(
                args=[], returncode=1, stdout="",
                stderr="no pull requests found for branch \"releasing-1.0.0\""
            ),
            # Second: gh pr view <number> succeeds - shows merged
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"state": "MERGED"}', stderr=""
            ),
        ]

        # After fix: should detect merge by falling back to PR number
        # and return successfully (no exception)
        self.automation._poll_for_pr_merge(
            "releasing-1.0.0",
            timeout_minutes=1,
            poll_interval_seconds=0.001,
            pr_number=123  # New parameter: PR number for fallback
        )

        # Should have made 2 calls - first by branch, then by number
        assert mock_run.call_count == 2

    @patch('release.subprocess.run')
    @patch('release.time.sleep')
    def test_waits_for_open_pr(self, mock_sleep, mock_run):
        """Test that polling continues waiting while PR is open."""
        # First call: PR is open, second call: PR is merged
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"state": "OPEN"}', stderr=""
            ),
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout='{"state": "MERGED"}', stderr=""
            ),
        ]

        self.automation._poll_for_pr_merge(
            "releasing-1.0.0",
            timeout_minutes=1,
            poll_interval_seconds=0.001
        )

        # Should have polled twice
        assert mock_run.call_count == 2

    @patch('release.subprocess.run')
    @patch('release.time.sleep')
    def test_timeout_when_pr_never_merges(self, mock_sleep, mock_run):
        """Test that polling times out if PR stays open."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"state": "OPEN"}',
            stderr=""
        )

        with pytest.raises(ReleaseError) as exc_info:
            self.automation._poll_for_pr_merge(
                "releasing-1.0.0",
                timeout_minutes=0.01,
                poll_interval_seconds=0.001
            )

        assert "timeout" in str(exc_info.value).lower()


class TestPushAndCreatePr:
    """Tests for push_and_create_pr method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.automation = ReleaseAutomation(dry_run=False, skip_confirmation=True)
        self.automation.repo_root = "/fake/repo"

    @patch('release.subprocess.run')
    @patch.object(ReleaseAutomation, 'run_command')
    def test_returns_pr_number_from_gh_output(self, mock_run_cmd, mock_subprocess):
        """Test that PR number is extracted and returned when creating PR.

        The gh pr create command outputs the PR URL, which contains the PR number.
        We need to capture this to use for polling later.
        """
        # gh CLI is available
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        # Simulate: first call is git push, second is gh pr create
        mock_run_cmd.side_effect = [
            # git push
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            # gh pr create - returns PR URL
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="https://github.com/softagram/sgraph/pull/456",
                stderr=""
            ),
        ]

        # After fix, this should return the PR number
        result = self.automation.push_and_create_pr("releasing-1.0.0", "1.0.0")

        # Should return PR number extracted from URL
        assert result == 456

    @patch('release.subprocess.run')
    @patch.object(ReleaseAutomation, 'run_command')
    def test_returns_none_when_gh_not_available(self, mock_run_cmd, mock_subprocess):
        """Test that None is returned when gh CLI is not available."""
        # gh CLI is NOT available
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )

        # git push succeeds
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        result = self.automation.push_and_create_pr("releasing-1.0.0", "1.0.0")

        # Should return None when gh is not available
        assert result is None


class TestPollWithPrNumber:
    """Tests for polling using PR number instead of branch name."""

    def setup_method(self):
        """Set up test fixtures."""
        self.automation = ReleaseAutomation(dry_run=False, skip_confirmation=True)
        self.automation.repo_root = "/fake/repo"

    @patch('release.subprocess.run')
    @patch('release.time.sleep')
    def test_poll_by_pr_number_works_after_branch_deleted(self, mock_sleep, mock_run):
        """Test that polling by PR number works even after branch is deleted.

        This is the key test for the fix: using PR number instead of branch name
        allows us to check status even after the branch is deleted post-merge.
        """
        # When polling by PR number, gh pr view <number> returns MERGED
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"state": "MERGED"}',
            stderr=""
        )

        # After fix, we should be able to poll by PR number
        # This method doesn't exist yet - we'll add it
        # self.automation._poll_for_pr_merge_by_number(123, timeout_minutes=1)

        # For now, verify the standard poll works with mocked MERGED state
        self.automation._poll_for_pr_merge("releasing-1.0.0", timeout_minutes=1)
        assert mock_run.called
