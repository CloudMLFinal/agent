from github import Github
from github import Auth
import os
import logging
import re
import hashlib
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GithubRepoClient:
    def __init__(self, repo_url: str):
        """Initialize the GithubRepoClient
        Args:
            repo_url (str): The URL of the repo
        """
        assert os.getenv("GITHUB_TOKEN"), "GITHUB_TOKEN must be set"
        auth = Auth.AppAuthToken(str(os.getenv("GITHUB_TOKEN")))
        gh = Github(auth=auth)
        
        assert gh, "Failed to initialize Github client"
        assert repo_url, "Repo URL is required"
        
        # get owner and repo name from the repo url
        owner, repo = repo_url.split("/")[-2:]
        repo = repo.split(".")[0]
        logger.info(f"Getting repo {owner}/{repo}")
        # get the repo
        self.repo = gh.get_repo(f"{owner}/{repo}")
        
        assert self.repo, "Failed to get repo"
        
        # Get the default branch
        self.curr_branch = self.repo.default_branch

    def submit_pr(self, pr_title: str, pr_body: str, pr_branch: str):
        """Submit a PR to the repo
        Args:
            pr_title (str): The title of the PR
            pr_body (str): The body of the PR
            pr_branch (str): The branch to merge the PR into
            tag (str): The tag of the PR
        Returns:
            The PR object
        """
        pr = self.repo.create_pull(
            title=pr_title, 
            body=pr_body, 
            base=self.curr_branch, 
            head=pr_branch
        )
        logger.info(f"PR created: {pr.html_url}")
        return pr

    def get_pr_list(self):
        """Get the list of PRs in the repo
        Returns:
            The list of PRs
        """
        prs = self.repo.get_pulls(state="open")
        return prs

    def analyze_error(self, error_file: Path) -> tuple[str, str, int]:
        """Analyze error log to extract file, line number and generate feature ID
        Args:
            error_file (Path): Path to the error log file
            
        Returns:
            tuple[str, str, int]: (file_path, feature_id, line_number)
        """
        with open(error_file, "r") as f:
            error_content = f.read()
            
        # Extract file and line number from error trace
        file_pattern = r'File "(.+?)", line (\d+)'
        match = re.search(file_pattern, error_content)
        if not match:
            return "", "", 0
            
        file_path = match.group(1)
        line_number = int(match.group(2))
        
        # Generate feature ID based on error content
        error_hash = hashlib.md5(error_content.encode()).hexdigest()[:8]
        feature_id = f"fix_{error_hash}"
        
        return file_path, feature_id, line_number
        
    def read_content(self, file_path: Path):
        """Read the content of a file
        Args:
            file_path (Path): Path to the file
            
        Returns:
            The content of the file
        """
        content = self.repo.get_contents(file_path.as_posix())
        if isinstance(content, list):
            raise ValueError(f"Path {file_path} is a directory, not a file")
        
        return content.decoded_content.decode()
    
    def clone_repo(self, path: Path):
        """Clone the repo to the path
        Args:
            path (Path): The path to clone the repo to
        """
    
    def check_existing_pr(self, feature_id: str) -> bool:
        """Check if there's an existing PR for this feature ID
        Args:
            feature_id (str): The feature ID to check
            
        Returns:
            bool: True if PR exists, False otherwise
        """
        prs = self.repo.get_pulls(state="open")
        for pr in prs:
            if feature_id in pr.title:
                return True
        return False