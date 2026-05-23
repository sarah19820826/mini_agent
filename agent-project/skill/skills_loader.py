"""Skill loader - parse SKILL.md files, progressive 4-phase loading.

Phase 1: Advertise (startup, scan all skills)
Phase 2: Load (on-demand, return full instructions)
Phase 3: Read (on-demand, read references/assets with path safety)
Phase 4: Run (on-demand, execute scripts with timeout)
"""
import os
import sys
import subprocess
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


class Skill:
    """A parsed skill."""

    def __init__(self, directory: str, metadata: dict, instructions: str):
        self.directory = directory
        self.name = metadata.get("name", os.path.basename(directory))
        self.description = metadata.get("description", "")
        self.metadata = metadata
        self.instructions = instructions
        self.mcp_servers: list = metadata.get("mcp_servers", [])
        self.max_rounds: Optional[int] = None

        meta_sub = metadata.get("metadata")
        if isinstance(meta_sub, dict):
            raw = meta_sub.get("max_rounds")
            if raw is not None:
                self.max_rounds = int(raw)

    @staticmethod
    def _parse_skill_md(filepath: str) -> Tuple[dict, str]:
        """Parse SKILL.md into (frontmatter_dict, markdown_body)."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        frontmatter_text = parts[1].strip()
        instructions = parts[2].strip()

        if yaml:
            metadata = yaml.safe_load(frontmatter_text) or {}
        else:
            # Minimal YAML parsing for key: value and list items
            metadata = _minimal_yaml_parse(frontmatter_text)

        return metadata, instructions


def _minimal_yaml_parse(text: str) -> dict:
    """Fallback YAML parser for simple frontmatter when pyyaml is unavailable."""
    result = {}
    current_list_key = None
    for line in text.split("\n"):
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith("  - "):
            if current_list_key:
                result[current_list_key].append(line.strip()[4:])
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                current_list_key = key
                result[current_list_key] = []
            else:
                current_list_key = None
                # Try to convert types
                if value.lower() in ("true", "false"):
                    result[key] = value.lower() == "true"
                elif value.isdigit():
                    result[key] = int(value)
                else:
                    result[key] = value
    return result


class SkillsLoader:
    """Scan and load skills from directories."""

    def __init__(self, skills_dirs: List[str]):
        self.skills_dirs = skills_dirs
        self.skills: Dict[str, Skill] = {}
        self._discover_skills()

    # Phase 1: Advertise
    def _discover_skills(self):
        """Scan all skill directories, parse SKILL.md frontmatter."""
        for skills_dir in self.skills_dirs:
            if not os.path.isdir(skills_dir):
                continue
            for entry in sorted(os.listdir(skills_dir)):
                skill_path = os.path.join(skills_dir, entry)
                skill_md_path = os.path.join(skill_path, "SKILL.md")
                if not os.path.isdir(skill_path) or not os.path.isfile(skill_md_path):
                    continue
                try:
                    metadata, instructions = Skill._parse_skill_md(skill_md_path)
                    skill = Skill(directory=skill_path, metadata=metadata,
                                  instructions=instructions)
                    self.skills[skill.name] = skill
                except Exception as error:
                    logger.error("[Skills] Failed to parse %s: %s", skill_md_path, error)

    def get_advertise_prompt(self) -> str:
        """Generate skill summary for system prompt (~100 tokens/skill)."""
        lines = [
            "## Available Skills",
            "",
            "The following skills are available. When a user's request matches "
            "a skill's description, use the `load_skill` tool to load its full "
            "instructions before proceeding.",
            "",
        ]
        for skill in self.skills.values():
            disable = skill.metadata.get("disable-model-invocation", False)
            note = " (user-invocable only, do not auto-load)" if disable else ""
            lines.append(f"- **{skill.name}**: {skill.description}{note}")
        return "\n".join(lines)

    # Phase 2: Load
    def load_skill(self, skill_name: str) -> str:
        """Return full SKILL.md body (operation manual)."""
        skill = self.skills.get(skill_name)
        if not skill:
            available = ", ".join(self.skills.keys())
            return f"Skill '{skill_name}' not found. Available skills: {available}"
        return skill.instructions

    # Phase 3: Read
    def read_skill_resource(self, skill_name: str, resource_path: str) -> str:
        """Read a resource file with path traversal protection."""
        skill = self.skills.get(skill_name)
        if not skill:
            return f"Skill '{skill_name}' not found."

        full_path = os.path.join(skill.directory, resource_path)
        real_skill_dir = os.path.realpath(skill.directory)
        real_resource_path = os.path.realpath(full_path)

        if not real_resource_path.startswith(real_skill_dir):
            return "Access denied: resource path escapes skill directory."

        if not os.path.isfile(full_path):
            available = []
            for subdir in ["references", "assets"]:
                subdir_path = os.path.join(skill.directory, subdir)
                if os.path.isdir(subdir_path):
                    for fn in os.listdir(subdir_path):
                        available.append(f"{subdir}/{fn}")
            hint = f" Available: {', '.join(available)}" if available else ""
            return f"Resource not found in skill '{skill_name}'.{hint}"

        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    # Phase 4: Run
    def run_skill_script(self, skill_name: str, script_path: str,
                         args: Optional[List[str]] = None) -> str:
        """Execute a skill script with path safety and timeout."""
        skill = self.skills.get(skill_name)
        if not skill:
            return f"Skill '{skill_name}' not found."

        full_path = os.path.join(skill.directory, script_path)
        real_skill_dir = os.path.realpath(skill.directory)
        real_script_path = os.path.realpath(full_path)

        if not real_script_path.startswith(real_skill_dir):
            return "Access denied: script path escapes skill directory."

        command = [sys.executable, full_path] + (args or [])
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                timeout=30, cwd=skill.directory,
            )
            output = result.stdout
            if result.returncode != 0:
                if result.stderr:
                    output += f"\n[stderr]: {result.stderr}"
                output += f"\n[exit code]: {result.returncode}"
            return output
        except subprocess.TimeoutExpired:
            return f"Script '{script_path}' timed out after 30 seconds."

    # Helpers
    def has_resources(self, skill_name: str) -> bool:
        skill = self.skills.get(skill_name)
        if not skill:
            return False
        for subdir in ["references", "assets"]:
            path = os.path.join(skill.directory, subdir)
            if os.path.isdir(path) and os.listdir(path):
                return True
        return False

    def has_scripts(self, skill_name: str) -> bool:
        skill = self.skills.get(skill_name)
        if not skill:
            return False
        scripts_dir = os.path.join(skill.directory, "scripts")
        return os.path.isdir(scripts_dir) and bool(os.listdir(scripts_dir))

    def list_resources(self, skill_name: str) -> List[str]:
        skill = self.skills.get(skill_name)
        if not skill:
            return []
        resources = []
        for subdir in ["references", "assets"]:
            path = os.path.join(skill.directory, subdir)
            if os.path.isdir(path):
                for fn in os.listdir(path):
                    resources.append(f"{subdir}/{fn}")
        return resources

    def list_scripts(self, skill_name: str) -> List[str]:
        skill = self.skills.get(skill_name)
        if not skill:
            return []
        scripts_dir = os.path.join(skill.directory, "scripts")
        if not os.path.isdir(scripts_dir):
            return []
        return [f for f in os.listdir(scripts_dir) if f.endswith(".py")]
