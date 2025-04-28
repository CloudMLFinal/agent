import os
import re
import git
import requests
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class CodeFixer:
    def __init__(self, error_file: Path):
        self.error_file = error_file
        self.repo_url = "https://github.com/CloudMLFinal/example-app.git"
        self.repo_dir = Path("example-app")
        self.api_key = "sk-e784bd0529d4429fa8756c69e745aeb1"
        
        # Path mapping rules (container path -> local path)
        self.path_mapping = {
            "/app/": self.repo_dir / "app/",
            "/home/app/": self.repo_dir
        }

    def _clone_repository(self):
        """Clone or update repository"""
        try:
            if not self.repo_dir.exists():
                logger.info(f"Cloning repository {self.repo_url}")
                self.repo = git.Repo.clone_from(self.repo_url, self.repo_dir)
            else:
                self.repo = git.Repo(self.repo_dir)
                logger.info("Updating existing repository")
                self.repo.remotes.origin.pull()
                
            # Configure Git user
            with self.repo.config_writer() as config:
                config.set_value("user", "name", "CodeFix Bot")
                config.set_value("user", "email", "bot@example.com")
                
        except git.GitError as e:
            logger.error(f"Git operation failed: {str(e)}")
            raise

    def _parse_error_log(self) -> dict:
        """Parse error log to locate code file"""
        with open(self.error_file, "r") as f:
            log = f.read()
        
        pattern = r"File \"(?P<file_path>.+?)\", line (?P<line>\d+)"
        match = re.search(pattern, log)
        if not match:
            raise ValueError("Failed to parse error log")
        
        # Convert container path to local path
        container_path = match.group("file_path")
        for prefix, local_path in self.path_mapping.items():
            if container_path.startswith(prefix):
                file_path = local_path / container_path[len(prefix):]
                break
        else:
            file_path = self.repo_dir / container_path
        
        return {
            "file": file_path,
            "line": int(match.group("line")),
            "content": log
        }

    def _analyze_with_api(self, context: dict) -> str:
        """Analyze error using DeepSeek API"""
        prompt = f"""
        Please fix the following Python error:
        
        File path: {context['file']}
        Line number: {context['line']}
        Error log:
        {context['content']}
        
        Requirements:
        1. Generate code patch in diff format
        2. Explain the fix reason
        3. Provide testing suggestions
        """
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            }
        )
        return response.json()['choices'][0]['message']['content']

    def _commit_fix(self, analysis: str):
        """Commit fix suggestions"""
        branch_name = f"fix/{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.repo.git.checkout("-b", branch_name)
        
        # Generate report
        report_path = self.repo_dir / "reports" / f"report_{self.error_file.stem}.md"
        report_path.parent.mkdir(exist_ok=True)
        
        with open(report_path, "w") as f:
            f.write(f"# Auto Fix Report\n\n")
            f.write(f"## Error File\n`{self.error_file.name}`\n\n")
            f.write(f"## Analysis Result\n```diff\n{analysis}\n```")
        
        # Commit to Git
        self.repo.index.add([str(report_path.relative_to(self.repo_dir))])
        self.repo.index.commit(f"[Bot] Fix {self.error_file.stem}")
        self.repo.git.push("origin", branch_name)
        logger.info(f"Fix committed to branch {branch_name}")

    def run(self):
        """Execute full workflow"""
        try:
            self._clone_repository()
            error_info = self._parse_error_log()
            analysis = self._analyze_with_api(error_info)
            self._commit_fix(analysis)
            return True
        except Exception as e:
            logger.error(f"Process failed: {str(e)}")
            return False

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python agent.py <error_file>")
        exit(1)
    
    fixer = CodeFixer(Path(sys.argv[1]))
    fixer.run()