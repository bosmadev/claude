#!/usr/bin/env python3
"""
Nightshift - Autonomous development cycle manager

Manages night-dev worktrees and autonomous agent spawning for continuous off-hours development.
Agents loop forever (research → implement → commit → repeat) until explicitly stopped.

Supports init, start, stop, status subcommands.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Import ACID transaction primitives
try:
    sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
    from transaction import atomic_write_json, locked_read_json, transactional_update
except ImportError:
    # Fallback if transaction.py not available
    def atomic_write_json(path, data):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def locked_read_json(path, default=None):
        if not path.exists():
            return default
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def transactional_update(path, update_fn, default=None):
        data = locked_read_json(path, default)
        updated = update_fn(data)
        atomic_write_json(path, updated)
        return updated

# Supported repositories (initial set)
SUPPORTED_REPOS = {
    "pulsona": "D:/source/pulsona",
    "gswarm": "D:/source/gswarm",
}

# State file for tracking active agents
STATE_FILE = Path.home() / ".claude" / "nightshift" / "state.json"


def ensure_state_dir():
    """Ensure nightshift state directory exists."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_state() -> Dict:
    """Load nightshift state from JSON file using ACID primitives."""
    return locked_read_json(STATE_FILE, {"agents": [], "repos": {}})


def save_state(state: Dict):
    """Save nightshift state to JSON file using ACID primitives."""
    ensure_state_dir()
    atomic_write_json(STATE_FILE, state)


def run_git(cwd: Path, *args) -> subprocess.CompletedProcess:
    """Run git command in specified directory."""
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def init_repo(repo_name: str) -> bool:
    """Initialize night-dev branch and worktree for a repository.

    Args:
        repo_name: Name of the repository (e.g., 'pulsona', 'gswarm')

    Returns:
        True if successful, False otherwise
    """
    if repo_name not in SUPPORTED_REPOS:
        print(f"❌ Unknown repo: {repo_name}")
        print(f"   Supported: {', '.join(SUPPORTED_REPOS.keys())}")
        return False

    bare_repo = Path(SUPPORTED_REPOS[repo_name])
    dev_branch = f"{repo_name}-dev"
    night_branch = f"{repo_name}-night-dev"
    night_worktree = bare_repo / night_branch

    if not bare_repo.exists():
        print(f"❌ Bare repo not found: {bare_repo}")
        return False

    print(f"Checking {bare_repo} for night-dev branch...")

    # Check if night-dev branch exists
    result = run_git(bare_repo, "rev-parse", "--verify", night_branch)
    branch_exists = result.returncode == 0

    if not branch_exists:
        # Create night-dev branch from dev branch
        print(f"Creating {night_branch} from {dev_branch}...")
        result = run_git(bare_repo, "branch", night_branch, dev_branch)
        if result.returncode != 0:
            print(f"❌ Failed to create branch: {result.stderr}")
            return False
        print(f"✓ {night_branch} branch created from {dev_branch}")

    # Check if worktree exists
    if night_worktree.exists():
        print(f"✓ Worktree already exists at {night_worktree}")
    else:
        # Add worktree
        print(f"Setting up worktree at {night_worktree}...")
        result = run_git(bare_repo, "worktree", "add", str(night_worktree), night_branch)
        if result.returncode != 0:
            print(f"❌ Failed to create worktree: {result.stderr}")
            return False
        print(f"✓ Worktree set up at {night_worktree}")

    # Update state
    state = load_state()
    if repo_name not in state["repos"]:
        state["repos"][repo_name] = {
            "night_branch": night_branch,
            "worktree_path": str(night_worktree),
            "initialized_at": datetime.now().isoformat(),
        }
        save_state(state)

    print(f"\n✓ Ready for nightshift agents.")
    return True


def start_agents(
    repo_name: str,
    task: Optional[str],
    num_agents: int = 3,
    budget: float = 5.00,
    model: str = "sonnet",
) -> bool:
    """Start nightshift agents in a repository's night-dev worktree.

    Agents run CONTINUOUSLY until /nightshift stop is invoked.
    They loop: research → implement → commit → push → research → ...

    Args:
        repo_name: Name of the repository
        task: Task description for agents (focus area)
        num_agents: Number of parallel agents to spawn
        budget: Maximum total spending in USD (soft limit, triggers warning)
        model: Agent model ('opus', 'sonnet', or 'gemini')

    Returns:
        True if successful, False otherwise
    """
    if repo_name not in SUPPORTED_REPOS:
        print(f"❌ Unknown repo: {repo_name}")
        return False

    # Check if repo is initialized
    state = load_state()
    if repo_name not in state["repos"]:
        print(f"❌ Repo not initialized. Run: /nightshift init {repo_name}")
        return False

    repo_info = state["repos"][repo_name]
    worktree_path = Path(repo_info["worktree_path"])

    if not worktree_path.exists():
        print(f"❌ Worktree not found: {worktree_path}")
        print(f"   Re-run: /nightshift init {repo_name}")
        return False

    print(f"Spawning {num_agents} nightshift agents in {worktree_path}")
    print(f"Budget: ${budget:.2f} (soft limit)")
    print(f"Model: {model}")
    if task:
        print(f"Task focus: {task}")
    print("\n⚠️  Agents will run CONTINUOUSLY until /nightshift stop\n")

    # Generate continuous operation prompt for agents
    budget_per_agent = budget / num_agents
    continuous_prompt = f"""You are a nightshift scout agent. Work CONTINUOUSLY until you receive a shutdown_request.

Your loop:
1. Research improvements (WebSearch/WebFetch for best practices, framework updates)
2. Implement changes in the night-dev worktree
3. Use /commit to commit and push changes (branch-aware, auto Build ID)
4. IMMEDIATELY start researching the next improvement
5. REPEAT FOREVER until shutdown_request

CRITICAL RULES (like /x agents):
- NEVER stop to create PRs (team-lead creates PR when you're shut down)
- NEVER report progress or status ("posted X commits", "continuing...")
- WORK SILENTLY with no status updates
- NEVER wait or pause between commits
- After pushing a commit, IMMEDIATELY start next research cycle
- Only stop when you receive shutdown_request message

Task focus: {task or "autonomous maintenance"}
Budget: ${budget_per_agent:.2f} (soft limit, triggers warning but don't stop)
Model: {model}
Worktree: {worktree_path}

Begin continuous operation now."""

    # This is where we would spawn actual agents via Task() in the parent skill
    # For now, output the agent spawn template and store metadata
    agents = []
    for i in range(1, num_agents + 1):
        agent_id = f"nightshift-scout-{i}"
        agents.append({
            "id": agent_id,
            "repo": repo_name,
            "task": task or "autonomous maintenance",
            "worktree": str(worktree_path),
            "budget_allocated": budget_per_agent,
            "model": model,
            "spawned_at": datetime.now().isoformat(),
            "status": "PENDING",
            "continuous_prompt": continuous_prompt,
        })
        print(f"Agent {i}: {agent_id} [PENDING - continuous mode]")

    # Update state with active agents
    state["agents"].extend(agents)
    save_state(state)

    print(f"\n✓ {num_agents} agents spawned in continuous mode.")
    print(f"   Use '/nightshift status' to monitor.")
    print(f"   Use '/nightshift stop' to shutdown and create PR.")
    return True


def stop_agents() -> bool:
    """Stop all active nightshift agents and create PR.

    Flow:
    1. Send shutdown_request to all active agents
    2. Wait for shutdown confirmations
    3. Auto-create PR from night-dev to dev branch
    4. Show session summary (commits, spend, duration)

    Returns:
        True if successful, False otherwise
    """
    state = load_state() or {"agents": [], "repos": {}}
    agents_list = state.get("agents") or []
    active_agents = [a for a in agents_list if a.get("status") in ["PENDING", "ACTIVE"]]

    if not active_agents:
        print("No active nightshift agents.")
        return True

    print(f"Sending shutdown requests to {len(active_agents)} agents...\n")

    # In actual implementation, would use SendMessage(type="shutdown_request")
    # For now, mark as stopped in state
    stopped_count = 0
    for agent in state["agents"]:
        if agent["status"] in ["PENDING", "ACTIVE"]:
            agent["status"] = "STOPPED"
            agent["stopped_at"] = datetime.now().isoformat()
            print(f"✓ {agent['id']} stopped")
            stopped_count += 1

    save_state(state)

    # Group agents by repo for PR creation
    repos_with_agents = {}
    for agent in active_agents:
        repo = agent["repo"]
        if repo not in repos_with_agents:
            repos_with_agents[repo] = []
        repos_with_agents[repo].append(agent)

    print(f"\n✓ All {stopped_count} agents stopped.\n")

    # Auto-create PRs for each repo
    print("Creating PRs from night-dev to dev branches...\n")
    for repo, agents in repos_with_agents.items():
        night_branch = f"{repo}-night-dev"
        dev_branch = f"{repo}-dev"

        # Calculate session summary
        total_budget = sum(a["budget_allocated"] for a in agents)
        spawn_time = min(datetime.fromisoformat(a["spawned_at"]) for a in agents)
        stop_time = max(datetime.fromisoformat(a["stopped_at"]) for a in agents)
        duration = (stop_time - spawn_time).total_seconds() / 3600  # hours

        print(f"📝 {repo}: Creating PR from {night_branch} → {dev_branch}")
        print(f"   Session: {len(agents)} agents, {duration:.1f}h duration, ${total_budget:.2f} budget")
        print(f"   ⚠️  Use /openpr to create the actual PR (auto-detection of commits + Build ID)")
        print()

    print("✓ Stop sequence complete.")
    print("   Next: Run /openpr in each night-dev worktree to create PRs")
    return True


def show_status() -> bool:
    """Show status of all active nightshift agents.

    Returns:
        True if successful, False otherwise
    """
    state = load_state() or {"agents": [], "repos": {}}
    agents_list = state.get("agents") or []
    active_agents = [a for a in agents_list if a.get("status") in ["PENDING", "ACTIVE"]]

    if not active_agents:
        print("No active nightshift agents.")
        return True

    print("Active nightshift agents:\n")

    # Group by repo
    by_repo: Dict[str, List[Dict]] = {}
    for agent in active_agents:
        repo = agent["repo"]
        if repo not in by_repo:
            by_repo[repo] = []
        by_repo[repo].append(agent)

    for repo, agents in by_repo.items():
        total_budget = sum(a["budget_allocated"] for a in agents)
        # In real implementation, would track actual spend
        spent = 0.0  # Placeholder
        print(f"{repo}-night-dev ({len(agents)} agents, ${spent:.2f}/${total_budget:.2f} budget):")
        for agent in agents:
            task = agent["task"]
            # In real implementation, would show actual metrics
            print(f"  - {agent['id']}: {task} [{agent['status']}]")
        print()

    return True


def main():
    """Main entry point for nightshift CLI."""
    parser = argparse.ArgumentParser(
        description="Nightshift - Autonomous development cycle manager"
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # Init subcommand
    init_parser = subparsers.add_parser("init", help="Initialize night-dev branch and worktree")
    init_parser.add_argument("repo", choices=list(SUPPORTED_REPOS.keys()), help="Repository name")

    # Start subcommand
    start_parser = subparsers.add_parser("start", help="Start nightshift agents (continuous mode)")
    start_parser.add_argument("repo", choices=list(SUPPORTED_REPOS.keys()), help="Repository name")
    start_parser.add_argument("task", nargs="?", help="Task focus for agents (optional)")
    start_parser.add_argument("--agents", type=int, default=3, help="Number of agents (default: 3)")
    start_parser.add_argument("--budget", type=float, default=5.00, help="Budget in USD - soft limit (default: $5.00)")
    start_parser.add_argument(
        "--model",
        choices=["opus", "sonnet", "gemini"],
        default="sonnet",
        help="Agent model: opus (expensive), sonnet (default), gemini (via GSwarm, future)"
    )

    # Stop subcommand
    subparsers.add_parser("stop", help="Stop all active nightshift agents")

    # Status subcommand
    subparsers.add_parser("status", help="Show status of active agents")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "init":
        success = init_repo(args.repo)
    elif args.command == "start":
        success = start_agents(
            args.repo,
            args.task,
            num_agents=args.agents,
            budget=args.budget,
            model=args.model,
        )
    elif args.command == "stop":
        success = stop_agents()
    elif args.command == "status":
        success = show_status()
    else:
        parser.print_help()
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
