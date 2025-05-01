from enum import Enum
import hashlib
import json
import os
import re
import shutil
import git
from openai import OpenAI
import requests
import logging
from pathlib import Path
from datetime import datetime

from monitroing.package import MessagePackage
from tools.file import get_content_from_file, get_file_in_line
from tools.github import GithubRepoClient

# Required environment variables:
# AGENT_API_KEY - API key for DeepSeek
# SOURCE_REPO - URL of the git repository
# GITHUB_TOKEN - Personal access token for GitHub (to avoid login prompts)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
)

logger = logging.getLogger(__name__)

class CodeFixer:
    def __init__(self, ticket: MessagePackage):
        self.ticket = ticket
        self.sandbox_dir: Path | None = None
        self.repo_dir: Path | None = None
        self.gh_client: GithubRepoClient | None = None
        
        assert os.getenv("AGENT_API_KEY"), "AGENT_API_KEY must be set"
        assert os.getenv("SOURCE_REPO"), "SOURCE_REPO must be set"
       
        self.repo_url = str(os.getenv("SOURCE_REPO"))
        
        # Get GitHub token from environment variable
        self.github_token = os.getenv("GITHUB_TOKEN")
        if self.github_token:
            # If token exists, embed it in the repo URL for authentication
            # Format: https://username:token@github.com/username/repo.git
            if self.repo_url.startswith("https://github.com/"):
                self.repo_url = self.repo_url.replace("https://github.com/", f"https://x-access-token:{self.github_token}@github.com/")
            elif self.repo_url.startswith("https://"):
                # Handle other git hosts that use HTTPS
                url_parts = self.repo_url.split("//")
                if len(url_parts) > 1:
                    self.repo_url = f"{url_parts[0]}//x-access-token:{self.github_token}@{url_parts[1]}"
            
            logger.debug(f"Using authenticated repo URL (token hidden)")
        else:
            logger.warning("GITHUB_TOKEN not set, git operations may require manual authentication")
            
        self.gh_client = GithubRepoClient(self.repo_url)
        self.agent = OpenAI(api_key=str(os.getenv("AGENT_API_KEY")), base_url="https://api.deepseek.com")
        
        # Path mapping rules (container path -> local path)
        self.path_mapping = {
            # TODO: add more path mapping rules base on the env
            "/app/": Path(),
        }

    def _clone_repo(self, feature_id: str):
        """Clone the repository"""
        try:
            assert self.repo_dir, "Repo dir is not set"
            if not self.repo_dir.exists():
                logger.debug(f"Cloning repository {self.repo_url}")
                self.repo = git.Repo.clone_from(self.repo_url, self.repo_dir)
            else:
                # If directory exists but not a git repo, remove it and clone
                if not (self.repo_dir / ".git").exists():
                    shutil.rmtree(self.repo_dir)
                    logger.debug(f"Re-cloning repository {self.repo_url}")
                    self.repo = git.Repo.clone_from(self.repo_url, self.repo_dir)
            
            # Check if repo is valid
            self.repo.git.status()
                
            # Configure Git user
            with self.repo.config_writer() as config:
                config.set_value("user", "name", "CodeFix Bot")
                config.set_value("user", "email", "bot@codefix.io")
                
            # checkout a new fix branch
            branch_name = f"fix/{feature_id}"
            logger.debug(f"Creating branch: {branch_name}")
            self.repo.git.checkout("-b", branch_name)
            logger.info(f"Repository cloned successfully: {self.repo_dir}, branch: {branch_name}")
        except git.GitError as e:
            logger.error(f"Git operation failed: {str(e)}")
            raise

    def _parse_error_log(self) -> list[tuple[Path, int]]:
        """Parse error log to locate code files"""
        pattern = r"File \"(?P<file_path>.+?)\", line (?P<line>\d+)"
        matches = re.finditer(pattern, self.ticket.message, re.MULTILINE)
        error_info = []
        
        for match in matches:
            # Convert container path to local path
            file_path = match.group("file_path")
            
            # if containing site-packages, ignore it
            if "site-packages" in file_path:
                continue
            
            for prefix, local_path in self.path_mapping.items():
                if file_path.startswith(prefix):
                    file_path = local_path / file_path[len(prefix):]
                    break
            else:
                # Ensure self.repo_dir is not None
                if self.repo_dir:
                    file_path = self.repo_dir / file_path
                else:
                    file_path = Path(file_path)
            
            error_info.append((file_path, int(match.group("line"))))
        
        logger.info(f"Found {len(error_info)} error files in application")
        logger.debug(f"Error Details: {self.ticket.message}")
            
        return error_info

    def _analyze_with_api(self, context: tuple[Path, int, str]) -> str:
        file_path, line, content = context
        
        """Analyze error using DeepSeek API"""
        prompt = f"""
        Please fix the following Python error:
        
        File path: {file_path}
        Line number: {line}
        Error log:
        {content}
        
        Requirements:
        1. Generate code patch in diff format
        2. Explain the fix reason
        3. Provide testing suggestions
        """
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {str(os.getenv('AGENT_API_KEY'))}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            }
        )
        return response.json()['choices'][0]['message']['content']

    def _analyze(self, context):
        """Analyze error using DeepSeek API"""
        id, raw_message, source_content, prompt, analysis_results, CMD = context
        
        print(f"Analyzing analysis_results: {analysis_results}")
        
        if CMD == "ANALYZE":
            STEP_PROMPT ="""
            You are an experienced operations engineer analyzing Python code errors. Your role is to:
            1. Quickly identify the root cause of errors
            2. Provide practical, production-ready fixes
            3. Consider system stability and performance
            4. Suggest preventive measures
            5. Maintain code behavior and type consistency

            Follow these steps:
            1. Analyze the error message and code context provided
            2. For each step, output a JSON response with:
            {
                "thought": "Your reasoning about the current situation",
                "action": "The action you want to take (ANALYZE/FIX/TEST/TERMINATE)", 
                "details": {
                "explanation": "Detailed explanation of your analysis/fix",
                "inspections": [
                    {
                    "file_path": "path/to/file.py",
                    "line": 42
                    },
                    ...
                ],
                "code_changes": [
                    {
                    "file_path": "path/to/file.py",
                    "line": 42,
                    "old_content": "original code line",
                    "new_content": "fixed code line",
                    "explanation": "explanation for this specific change",
                    "type_compatibility": "Explanation of how the change maintains type compatibility"
                    },
                    ...
                ],
                "tests": "Suggested test cases",
                "prevention": "Suggestions to prevent similar issues in the future"
                },
                "next": "Your planned next step"
            }

            Guidelines:
            - You have been provided with:
            * The complete error message in the context
            * The source code content at the error location
            * The file path and line number where the error occurs
            - The source code is provided in the format: "File: {file_path}@line {line} -> {content}"
            - Use the provided information directly, do not request to see the error or code again
            - As an operations engineer:
            * Focus on system stability and reliability
            * Consider production environment constraints
            * Provide robust error handling
            * Suggest monitoring and alerting improvements
            * Think about scalability and performance
            * Ensure code changes maintain:
                - Type compatibility with existing code
                - Interface consistency
                - Expected behavior patterns
                - Return value types
                - Parameter types
                - Exception handling patterns
            - Start with ANALYZE to understand the error
            - When action is ANALYZE, details must include:
            * inspections: list of code locations to investigate
            * Each inspection item contains:
                - file_path: string path to the file
                - line: integer line number
            * If no specific locations to inspect, use an empty list []
            - Use FIX to propose specific code changes
            - When action is FIX, code_changes must be a list of changes, each containing:
            * file_path: string path to the file
            * line: integer line number
            * old_content: original code line
            * new_content: fixed code line
            * explanation: explanation for this specific change
            * type_compatibility: explanation of how the change maintains type compatibility
            - If no code changes are needed, use an empty list []
            - Use TEST to suggest validation steps
            - Use TERMINATE when analysis is complete
            - Each step should build on previous findings
            - Be specific and detailed in explanations
            - Format code changes as git-style diffs
            - Focus on practical, targeted fixes

            Previous context will be provided as:
            {context}

            Respond with your analysis steps until reaching TERMINATE.
            """
        
            try:
                # start thinking
                response = self.agent.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": STEP_PROMPT},
                        {"role": "user", "content": f"Previous context: {context}"},
                    ],
                    stream=False
                )
                
                # Parse the response
                if not response or not response.choices or not response.choices[0].message:
                    logger.error("Invalid response format")
                    return analysis_results
                content = response.choices[0].message.content
                if not content:
                    logger.error("Empty response content")
                    return analysis_results
                    
                # Remove the markdown code block if present
                if content.startswith('```json'):
                    content = content[7:]  # Remove ```json
                if content.endswith('```'):
                    content = content[:-3]  # Remove ```
                content = content.strip()
                
                # Parse the JSON
                analysis_data = json.loads(content)
                
                # Extract the information
                thought = analysis_data.get('thought', '')
                action = analysis_data.get('action', '')
                details = analysis_data.get('details', {})
                next_step = analysis_data.get('next', '')
                
                # Log the extracted information
                logger.debug(f"Analysis Thought: {thought}")
                logger.debug(f"Action: {action}")
                logger.debug(f"Details: {json.dumps(details, indent=2)}")
                logger.debug(f"Next Step: {next_step}")
                
                # Update the analysis results
                analysis_results.append({
                    'id': id,  # Add the id to the analysis result
                    'thought': thought,
                    'action': action,
                    'details': details,
                    'next': next_step
                })
                
                # Handle the action
                should_continue = self._handle_action({
                    'thought': thought,
                    'action': action,
                    'details': details,
                    'next': next_step
                })
                
                # If we should continue, update the context and call analyze again
                if should_continue:
                    # Call analyze again with updated context
                    analysis_results = self._analyze((
                        id,
                        raw_message,
                        source_content,
                        prompt,
                        analysis_results,
                        action  # Use the current action as the next command
                    ))
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse response JSON: {e}")
                return analysis_results
            except Exception as e:
                logger.error(f"Error processing response: {e}")
                return analysis_results
        return analysis_results
    
    def _commit_fix(self, analysis_results: list):
        """Commit fix suggestions
        
        Args:
            analysis_results: List of analysis results including actions, explanations, etc.
        """
        if not self.repo_dir or not analysis_results:
            logger.warn("Cannot commit: repo_dir is None or analysis_results is empty")
            return
            
        # Get the last FIX action with explanation
        explanation = "Auto fix by agent"
        details = None
        feature_id = None  # Initialize feature_id
        
        # Try to get the feature_id from the first item's id
        if len(analysis_results) > 0 and isinstance(analysis_results[0], dict):
            feature_id = analysis_results[0].get('id', None)
        
        # If feature_id is still None, generate a new one
        if not feature_id:
            # Use the directory name as feature_id
            feature_id = self.sandbox_dir.name if self.sandbox_dir else "unknown"
        
        for result in reversed(analysis_results):
            if result.get('action') == 'FIX':
                details = result.get('details', {})
                if details and 'explanation' in details:
                    explanation = details['explanation']
                    break
        
        # Get code changes for commit message details
        code_changes_info = ""
        if details and 'code_changes' in details:
            for change in details['code_changes']:
                file_path = change.get('file_path', '')
                line = change.get('line', '')
                explanation = change.get('explanation', '')
                code_changes_info += f"\n- {file_path}:{line}: {explanation}"

        # Commit to Git
        commit_message = f"[Bot] Fix: {explanation[:50]}..." if len(explanation) > 50 else f"[Bot] Fix: {explanation}"
        
        try:
            # Also add any changed files from the FIX actions
            changed_files = set()
            for result in analysis_results:
                if result.get('action') == 'FIX':
                    details = result.get('details', {})
                    if details and 'code_changes' in details:
                        for change in details['code_changes']:
                            file_path = change.get('file_path')
                            if file_path:
                                try:
                                    # Convert file_path to Path object if it's a string
                                    if isinstance(file_path, str):
                                        file_path = Path(file_path)
                                    
                                    # Get absolute path first to ensure consistent paths
                                    abs_file_path = file_path.resolve()
                                    abs_repo_dir = self.repo_dir.resolve()
                                    
                                    # Make sure the file is inside the repo
                                    if str(abs_file_path).startswith(str(abs_repo_dir)):
                                        changed_files.add(str(abs_file_path))
                                    else:
                                        logger.error(f"File {file_path} is not inside the repo directory {self.repo_dir}")
                                except Exception as e:
                                    logger.error(f"Error processing file path: {file_path}, {str(e)}")
            
            # Add all changed files
            for file_path in changed_files:
                try:
                    # Use relative path for git add
                    file_path_obj = Path(file_path)
                    repo_dir_obj = self.repo_dir.resolve()
                    relative_path = file_path_obj.relative_to(repo_dir_obj)
                    logger.debug(f"Adding file to git: {relative_path}")
                    self.repo.index.add([str(relative_path)])
                except (ValueError, git.GitCommandError) as e:
                    logger.error(f"Error adding file to git: {file_path}, {str(e)}")
            
            # commit the changes
            self.repo.index.commit(commit_message)
            
            # Push to origin
            branch_name = f"fix/{feature_id}"
            logger.debug(f"Pushing to branch: {branch_name}")
            
            # Set up credential helper to avoid prompts
            if hasattr(self, 'github_token') and self.github_token:
                # Configure Git to use credentials without prompting
                # Create a temporary script for credential helper
                import tempfile
                with tempfile.NamedTemporaryFile('w', delete=False, suffix='.sh') as f:
                    f.write('#!/bin/sh\necho "username=x-access-token\npassword=' + self.github_token + '"')
                    credential_helper = f.name
                os.chmod(credential_helper, 0o700)  # Make executable
                
                try:
                    # Set credential helper for this repo
                    self.repo.git.config("credential.helper", credential_helper)
                    # Push with the configured credential helper
                    self.repo.git.push("origin", branch_name)
                finally:
                    # Remove the temporary file
                    if os.path.exists(credential_helper):
                        os.unlink(credential_helper)
            else:
                # Fall back to regular push
                self.repo.git.push("origin", branch_name)
                
            logger.info(f"Fix committed to branch {branch_name}")
            
            # create a pr
            if self.gh_client:
                # Generate report
                report_str= f"""
                # Auto Fix Report
                
                > ID: {feature_id}
                > Created at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                
                ## Error Log
                ```shell
                {self.ticket.message}
                ```
                
                ## Error Analysis
                {explanation}
                
                ## Code Changes
                {code_changes_info}
                
                ## Analysis Details
                ```json
                {json.dumps(analysis_results, indent=2)}
                ```
                """
                
                pr = self.gh_client.submit_pr(
                    pr_title=f"Fix: {explanation[:50]}...",
                    pr_body=report_str,
                    pr_branch=branch_name
                )
                
                logger.info(f"A fix PR created: {pr.html_url}") 
        except Exception as e:
            logger.error(f"Error during git operations: {str(e)}")
            # Log full traceback for debugging
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def _destroy(self):
        """Destroy the sandbox directory"""
        # remove the sandbox directory
        if self.sandbox_dir and self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir)
            if self.sandbox_dir.exists():
                os.rmdir(self.sandbox_dir)
            logger.info(f"Removed sandbox directory: {self.sandbox_dir}")
        else:
            logger.warning(f"Cannot destroy sandbox: directory does not exist or is None")
    
    def _handle_action(self, analysis_result: dict) -> bool:
        """Handle different actions based on the analysis result
        
        Args:
            analysis_result: The analysis result containing action and details
            
        Returns:
            bool: Whether to continue the analysis process
        """
        action = analysis_result.get('action', '')
        details = analysis_result.get('details', {})
        
        if action == 'ANALYZE':
            # For ANALYZE action, we need to inspect the specified files
            inspections = details.get('inspections', [])
            if not inspections:
                logger.info("No files to inspect, moving to next step")
                return True
                
            # Get content of files to inspect
            for inspection in inspections:
                file_path = inspection.get('file_path')
                line = inspection.get('line')
                if not file_path or not line:
                    continue
                    
                # Use the provided file path directly
                file_path = Path(file_path)
                    
                if not file_path.exists():
                    logger.error(f"File not found: {file_path}")
                    continue
                    
                content = get_file_in_line(file_path, line)
                logger.debug(f"Inspecting file: {file_path}@line {line}")
                logger.debug(f"Content: {content}")
                
            return True     
        elif action == 'FIX':
            # For FIX action, we need to apply the code changes
            code_changes = details.get('code_changes', [])
            if not code_changes:
                logger.debug("No code changes to apply")
                return True  # Continue even if no changes to apply
                
            # Apply each code change
            for change in code_changes:
                file_path = change.get('file_path')
                line = change.get('line')
                old_content = change.get('old_content')
                new_content = change.get('new_content')
                
                if not all([file_path, line, old_content, new_content]):
                    logger.error("Missing required fields in code change")
                    continue
                    
                # Use the provided file path directly
                file_path = Path(file_path)
                    
                if not file_path.exists():
                    logger.error(f"File not found: {file_path}")
                    continue
                    
                # Read the file content
                with open(file_path, 'r') as f:
                    lines = f.readlines()
                    
                # Replace the line
                if 0 <= line - 1 < len(lines):
                    if lines[line - 1].strip() == old_content.strip():
                        lines[line - 1] = new_content + '\n'
                        logger.info(f"Applied change to {file_path}@line {line}")
                    else:
                        logger.error(f"Content mismatch at {file_path}@line {line}")
                        logger.error(f"Expected: {old_content}")
                        logger.error(f"Found: {lines[line - 1]}")
                        continue
                        
                # Write back the changes
                with open(file_path, 'w') as f:
                    f.writelines(lines)
                    
            return True
            
        elif action == 'TEST':
            # For TEST action, we need to run the suggested tests
            tests = details.get('tests', '')
            if not tests:
                logger.info("No tests to run")
                return True
                
            logger.info(f"Suggested tests:\n{tests}")
            # TODO: Implement test running logic
            return True
            
        elif action == 'TERMINATE':
            # For TERMINATE action, we end the analysis process
            logger.info("Analysis process terminated")
            return False
            
        else:
            logger.error(f"Unknown action: {action}")
            return False
        
    async def run(self):
        """Execute full workflow"""
        try:
            """Agent workflow"""
            # 1. Parse error log first
            error_info_list = self._parse_error_log()
            feature_id = hashlib.sha256(''.join([f"{file_path}@{line}" for file_path, line in error_info_list]).encode()).hexdigest()
           
            self.sandbox_dir = Path(f".sandbox/{feature_id}")
            self.repo_dir = self.sandbox_dir / "src"
            self.repo_dir.mkdir(exist_ok=True, parents=True)
           
            logger.debug(f"Found {len(error_info_list)} in ticket {feature_id}")
            
            if len(error_info_list) == 0:
                logger.warn("No error files found, skip")
                return False
            
            # 2. Check if the ticket is already in the pr list
            logger.debug(f"Checking if the ticket {feature_id} is already in the pr list")
            assert self.gh_client, "Github client is not initialized"
            if self.gh_client.branch_exist_remote(f"fix/{feature_id}"):
                logger.warn(f"Ticket {feature_id} is already in the pr list, skip")
                return False
            
            # 2. Clone repository
            try:
                logger.debug(f"Cloning repository {self.repo_url}")
                self._clone_repo(feature_id)
            except Exception as e:
                logger.error(f"Failed to clone repository: {str(e)}")
                self._destroy()
                return False
            
            # 3. Get source code of the error files
            issues_source_content = []
            for error_info in error_info_list:
                file_path, line = error_info
                file_path = self.repo_dir / file_path
                # Verify file exists before trying to read it
                if not file_path.exists():
                    logger.error(f"File not found after clone: {file_path}")
                    continue
                content = get_file_in_line(file_path, line)
                print(f"File: {file_path}, Line: {line}, Content: {content}")
                issues_source_content.append((file_path, line, content))
                
            # Prepare prompt for the agent
            source_content_str = ""
            if len(issues_source_content) > 0:
                for file_path, line, content in issues_source_content:
                    source_content_str += f"File: {file_path}@line {line} -> {content}\n"
            else:
                source_content_str = "No source code found, please check the log message for the details."
            
            USER_PROMPT = f"""
            Raw log message:
            {self.ticket.message}
            
            Source codes:
            {source_content_str}
            """
            
            # Call the analysis method and capture results
            analysis_result = self._analyze((
                feature_id,
                self.ticket.message,
                source_content_str,
                USER_PROMPT,
                [],  # Pass the results array reference
                "ANALYZE", # for agent to think next step
            ))
            
            print(f"Analysis result: {analysis_result}")
            
            # If analysis is successful and has results, try to commit the fix
            if analysis_result and isinstance(analysis_result, list) and len(analysis_result) > 0:
                # If there are code_changes, commit the fixes
                has_fixes = False
                for result in analysis_result:
                    if result.get('action') == 'FIX':
                        details = result.get('details', {})
                        if details and details.get('code_changes'):
                            has_fixes = True
                            break
                
                if has_fixes:
                    logger.info("Code changes detected, committing fixes")
                    self._commit_fix(analysis_result)
                else:
                    logger.info("No code changes detected, skipping commit")
            else:
                logger.warning("No valid analysis results returned, skipping commit")
            
            # cleanup the session
            self._destroy()
            return True
        except Exception as e:
            logger.error(f"Process failed: {str(e)}")
            self._destroy()  # Ensure cleanup on any error
            return False
