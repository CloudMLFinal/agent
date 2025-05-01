from pathlib import Path

def get_content_from_file(file_path: Path) -> dict[str, str | Path]:
    """Get content from file"""
    with open(file_path, "r") as f:
        return {
            "content": f.read(),
            "file_path": file_path
        }

def get_file_in_line(file_path: Path, line_number: int) -> dict[str, str | Path | int]:
    """Get content from file"""
    with open(file_path, "r") as f:
        return {
            "content": f.readlines()[line_number - 1],
            "file_path": file_path,
            "line_number": line_number
        }
        
def write_content_to_file(file_path: Path, content: str) -> None:
    """Write content to file"""
    with open(file_path, "w") as f:
        f.write(content)

def replace_content_in_file(file_path: Path, replaced_content: str, new_content: str, line_number: int | None = None) -> None:
    """Replace content in file"""
    with open(file_path, "r") as f:
        lines = f.readlines()
        
        if line_number is not None:
            lines[line_number - 1] = lines[line_number - 1].replace(replaced_content, new_content)
        else:
            lines = ''.join(lines).replace(replaced_content, new_content).splitlines(True)

    with open(file_path, "w") as f:
        f.writelines(lines)

