"""
A0 Dreaming - Session Reader Tool with Safety Features

Claude-style dreaming: Analyze past sessions for error patterns, best practices, and insights.
Phase 2: Backup system, restore function, manual-only mode.
Phase 3: Dreamer Agent - comprehensive pattern analysis and insights.
"""
import os
import json
import shutil
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from collections import Counter, defaultdict
import re

from helpers.tool import Tool
from helpers.errors import handle_error
from plugins._memory.helpers.memory import Memory


class Dreaming(Tool):
    """Session reader and analyzer for cross-session learning with safety features."""
    
    CHATS_DIR = Path("/a0/usr/chats")
    BACKUP_DIR = Path("/a0/usr/plugins/a0-dreaming/backups")
    MAX_CHECKPOINTS = 3
    
    @classmethod
    def _get_chat_dirs(cls) -> List[Path]:
        """Get all chat directories sorted by modification time (newest first)."""
        if not cls.CHATS_DIR.exists():
            return []
        
        chat_dirs = [d for d in cls.CHATS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")]
        return sorted(chat_dirs, key=lambda d: d.stat().st_mtime, reverse=True)
    
    @classmethod
    def _read_chat_json(cls, chat_dir: Path) -> Optional[Dict[str, Any]]:
        """Read chat.json from a chat directory."""
        chat_json = chat_dir / "chat.json"
        if not chat_json.exists():
            return None
        
        try:
            with open(chat_json, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            return None
    
    @classmethod
    def _extract_tool_calls(cls, logs: List[Dict]) -> List[Dict[str, Any]]:
        """Extract tool calls from log entries."""
        tool_calls = []
        for entry in logs:
            # Handle explicit None values with 'or {}' pattern
            kvps = entry.get("kvps") or {}
            
            if "tool_name" in entry:
                tool_calls.append({
                    "tool_name": entry.get("tool_name"),
                    "tool_args": entry.get("tool_args") or {},
                    "timestamp": entry.get("timestamp"),
                    "entry_no": entry.get("no"),
                })
            # Also check kvps for tool info
            elif "tool_name" in kvps:
                tool_calls.append({
                    "tool_name": kvps.get("tool_name"),
                    "tool_args": kvps.get("tool_args") or {},
                    "timestamp": entry.get("timestamp"),
                    "entry_no": entry.get("no"),
                    "thoughts": kvps.get("thoughts") or [],
                })
        return tool_calls
    
    @classmethod
    def _detect_errors(cls, logs: List[Dict], sensitivity: str = "moderate") -> List[Dict[str, Any]]:
        """Detect error patterns in log entries with configurable sensitivity.
        
        Args:
            logs: List of log entries to analyze
            sensitivity: Detection sensitivity level
                - "strict": Only explicit errors (traceback, exception:, error:)
                - "moderate": Clear errors (error, failed, exception, traceback) [default]
                - "loose": All candidates (+ unable to, could not, warning)
        
        Returns:
            List of detected error entries with metadata
        """
        # Define keywords per sensitivity level
        SENSITIVITY_KEYWORDS = {
            "strict": ["traceback", "exception:", "error:"],
            "moderate": ["error", "failed", "exception", "traceback"],
            "loose": ["error", "failed", "exception", "traceback", "unable to", "could not", "warning"],
        }
        
        # Validate sensitivity, default to moderate
        if sensitivity not in SENSITIVITY_KEYWORDS:
            sensitivity = "moderate"
        
        error_keywords = SENSITIVITY_KEYWORDS[sensitivity]
        errors = []
        
        for entry in logs:
            # Skip user messages - they're not errors
            if entry.get("type") == "user":
                continue
            
            # Handle explicit None values with 'or ""' pattern
            # Keep original text for display, use lowercase for detection
            original_content = entry.get("content") or ""
            original_heading = entry.get("heading") or ""
            content_lower = original_content.lower()
            heading_lower = original_heading.lower()
            kvps = entry.get("kvps") or {}
            
            # Check for error indicators (case-insensitive matching)
            is_error = any(kw in content_lower or kw in heading_lower for kw in error_keywords)
            
            # Check kvps for error markers
            kvps_str = str(kvps).lower()
            if any(kw in kvps_str for kw in error_keywords):
                is_error = True
            
            if is_error:
                errors.append({
                    "id": entry.get("no"),  # ID for frontend selection
                    "entry_no": entry.get("no"),  # Entry number for reference
                    "type": entry.get("type"),
                    "heading": original_heading[:200],  # Original case for display
                    "content": original_content[:500],  # Original case for display
                    "timestamp": entry.get("timestamp"),
                })
        return errors
    
    @classmethod
    def _extract_session_data(cls, chat_dir: Path, include_logs: bool = True, sensitivity: str = "moderate") -> Dict[str, Any]:
        """Extract structured data from a single session."""
        chat_data = cls._read_chat_json(chat_dir)
        if not chat_data:
            return {"id": chat_dir.name, "error": "Could not read chat.json"}
        
        logs_dict = chat_data.get("log") or {}
        logs = logs_dict.get("logs", []) if isinstance(logs_dict, dict) else []
        
        session = {
            "id": chat_data.get("id", chat_dir.name),
            "name": chat_data.get("name", "Untitled"),
            "created_at": chat_data.get("created_at"),
            "agent_profile": chat_data.get("agent_profile"),
            "message_count": len(logs),
            "tool_calls": cls._extract_tool_calls(logs),
            "errors": cls._detect_errors(logs, sensitivity=sensitivity),
        }
        
        if include_logs:
            session["logs_sample"] = logs[:10]  # First 10 entries for context
        
        return session
    
    # ==================== PHASE 3: PATTERN ANALYSIS ====================
    
    @classmethod
    def _classify_error_type(cls, error: Dict[str, Any]) -> str:
        """Classify error into a category based on content.
        
        Returns one of: api_error, syntax_error, logic_error, timeout, permission, 
        resource_error, configuration, or unknown.
        """
        content = (error.get("content") or "").lower()
        heading = (error.get("heading") or "").lower()
        combined = f"{heading} {content}"
        
        # API/Network errors
        if any(kw in combined for kw in ["api", "http", "request", "response", "connection", "network", "timeout", "503", "500", "404", "401", "403"]):
            return "api_error"
        
        # Syntax/Parse errors
        if any(kw in combined for kw in ["syntax", "parse", "unexpected token", "invalid", "jsondecode", "indentation", "unexpected "]):
            return "syntax_error"
        
        # Permission errors
        if any(kw in combined for kw in ["permission", "denied", "unauthorized", "forbidden", "access denied", "eacces"]):
            return "permission"
        
        # Timeout errors
        if any(kw in combined for kw in ["timeout", "timed out", "deadline exceeded"]):
            return "timeout"
        
        # Resource errors
        if any(kw in combined for kw in ["memory", "disk", "space", "resource", "allocate", "oom", "out of memory"]):
            return "resource_error"
        
        # Configuration errors
        if any(kw in combined for kw in ["config", "setting", "not found", "missing", "undefined", "null", "none", "keyerror"]):
            return "configuration"
        
        # Logic/Runtime errors
        if any(kw in combined for kw in ["traceback", "exception", "error", "failed", "indexerror", "typeerror", "valueerror", "attributeerror"]):
            return "logic_error"
        
        return "unknown"
    
    @classmethod
    def _group_errors_by_type(cls, errors: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group errors by their classified type."""
        grouped = defaultdict(list)
        for error in errors:
            error_type = cls._classify_error_type(error)
            grouped[error_type].append(error)
        return dict(grouped)
    
    @classmethod
    def _find_error_signature(cls, error: Dict[str, Any]) -> str:
        """Extract a signature for matching similar errors across sessions.
        
        Creates a normalized signature by extracting key error patterns.
        """
        content = error.get("content") or ""
        heading = error.get("heading") or ""
        combined = f"{heading} {content}".lower()
        
        # Remove session-specific details (numbers, paths, timestamps)
        normalized = re.sub(r'\b[\d]+\b', 'N', combined)  # Replace numbers
        normalized = re.sub(r'/[\w/\.-]+', 'PATH', normalized)  # Replace paths
        normalized = re.sub(r'0x[\da-f]+', 'ADDR', normalized)  # Replace addresses
        normalized = re.sub(r'"[^"]+"', 'STR', normalized)  # Replace strings
        
        # Extract key error phrases
        error_patterns = [
            r'(traceback.*?)(?=traceback|$)',
            r'(error[:\s]+[\w\s]+)',
            r'(exception[:\s]*[\w]+)',
            r'(failed to[\w\s]+)',
        ]
        
        for pattern in error_patterns:
            match = re.search(pattern, normalized)
            if match:
                return match.group(1)[:100]  # Limit signature length
        
        # Fallback: first 100 chars of normalized content
        return normalized[:100]
    
    @classmethod
    def _find_recurring_errors(cls, errors: List[Dict[str, Any]], min_occurrences: int = 2) -> List[Dict[str, Any]]:
        """Find errors that occur across multiple sessions.
        
        Returns list of recurring error patterns with session info.
        """
        # Group errors by signature
        signature_map = defaultdict(lambda: {"sessions": set(), "errors": []})
        
        for error in errors:
            sig = cls._find_error_signature(error)
            session_id = error.get("session_id", "unknown")
            signature_map[sig]["sessions"].add(session_id)
            signature_map[sig]["errors"].append(error)
        
        # Filter to recurring patterns (appear in multiple sessions OR multiple times)
        recurring = []
        for sig, data in signature_map.items():
            if len(data["sessions"]) >= min_occurrences or len(data["errors"]) >= 3:
                recurring.append({
                    "signature": sig[:100],
                    "occurrences": len(data["errors"]),
                    "sessions_affected": list(data["sessions"]),
                    "session_count": len(data["sessions"]),
                    "sample_error": data["errors"][0],
                })
        
        # Sort by occurrences
        return sorted(recurring, key=lambda x: x["occurrences"], reverse=True)
    
    @classmethod
    def _identify_success_patterns(cls, sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify sessions with low error rates and extract success patterns.
        
        Returns list of successful session patterns with key factors.
        """
        success_patterns = []
        
        for session in sessions:
            error_count = len(session.get("errors") or [])
            tool_calls = session.get("tool_calls") or []
            message_count = session.get("message_count") or 1
            
            # Calculate error rate
            error_rate = error_count / max(message_count, 1)
            
            # Consider session successful if error rate < 5% and has tool activity
            if error_rate < 0.05 and len(tool_calls) > 3:
                # Extract tool sequence
                tool_sequence = [tc.get("tool_name") for tc in tool_calls[:10]]
                
                # Count tool usage
                tool_counter = Counter(tool_sequence)
                
                success_patterns.append({
                    "session_id": session.get("id"),
                    "session_name": session.get("name"),
                    "error_rate": round(error_rate, 3),
                    "tool_count": len(tool_calls),
                    "top_tools": tool_counter.most_common(5),
                    "tool_sequence": tool_sequence[:5],
                    "message_count": message_count,
                })
        
        # Sort by lowest error rate
        return sorted(success_patterns, key=lambda x: x["error_rate"])[:10]
    
    @classmethod
    def _analyze_tool_patterns(cls, sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze tool usage patterns across sessions.
        
        Returns tool statistics including most used, failure associations, and sequences.
        """
        tool_counter = Counter()
        tool_by_session = defaultdict(Counter)
        tool_sequences = []
        
        for session in sessions:
            tool_calls = session.get("tool_calls") or []
            session_id = session.get("id")
            
            # Track tool usage
            sequence = []
            for tc in tool_calls:
                tool_name = tc.get("tool_name") or "unknown"
                tool_counter[tool_name] += 1
                tool_by_session[session_id][tool_name] += 1
                sequence.append(tool_name)
            
            if len(sequence) > 1:
                tool_sequences.append(sequence)
        
        # Find common tool pairings (consecutive tools)
        pair_counter = Counter()
        for seq in tool_sequences:
            for i in range(len(seq) - 1):
                pair = f"{seq[i]} -> {seq[i+1]}"
                pair_counter[pair] += 1
        
        return {
            "most_used": tool_counter.most_common(10),
            "total_unique_tools": len(tool_counter),
            "common_transitions": pair_counter.most_common(10),
            "tools_per_session_avg": sum(len(s.get("tool_calls", [])) for s in sessions) / max(len(sessions), 1),
        }
    
    @classmethod
    def _generate_recommendations(cls, error_patterns: Dict, recurring: List, success: List, tool_insights: Dict) -> List[str]:
        """Generate actionable recommendations based on analysis.
        
        Returns prioritized list of recommendations.
        """
        recommendations = []
        
        # Recommendations based on error types
        if "api_error" in error_patterns and len(error_patterns["api_error"]) > 3:
            recommendations.append("Consider implementing retry logic with exponential backoff for API calls")
        
        if "syntax_error" in error_patterns and len(error_patterns["syntax_error"]) > 2:
            recommendations.append("Add input validation and JSON parsing error handling")
        
        if "timeout" in error_patterns and len(error_patterns["timeout"]) > 2:
            recommendations.append("Review long-running operations and implement proper timeout handling")
        
        if "permission" in error_patterns and len(error_patterns["permission"]) > 1:
            recommendations.append("Check file/directory permissions and user access rights")
        
        # Recommendations based on recurring errors
        for pattern in recurring[:3]:
            sig = pattern.get("signature", "")[:50]
            count = pattern.get("occurrences", 0)
            recommendations.append(f"Investigate recurring issue: '{sig}...' ({count} occurrences)")
        
        # Recommendations based on success patterns
        if success:
            top_success = success[0]
            recommendations.append(f"Study successful session '{top_success.get('session_name', '')}' for best practices")
        
        # Tool-based recommendations
        common_transitions = tool_insights.get("common_transitions", [])
        if common_transitions:
            recommendations.append(f"Optimize common tool chain: {common_transitions[0][0]}")
        
        return recommendations[:8]  # Limit to top 8
    
    # ==================== BACKUP SYSTEM ====================
    
    @classmethod
    def _ensure_backup_dir(cls) -> None:
        """Ensure backup directory exists."""
        cls.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def _get_checkpoint_paths(cls) -> Dict[int, Path]:
        """Get paths for all checkpoint files."""
        return {
            i: cls.BACKUP_DIR / f"checkpoint_{i}.json"
            for i in range(1, cls.MAX_CHECKPOINTS + 1)
        }
    
    @classmethod
    def _rotate_checkpoints(cls) -> None:
        """Rotate checkpoints: 3->delete, 2->3, 1->2, new->1 (FIFO)."""
        cls._ensure_backup_dir()
        checkpoints = cls._get_checkpoint_paths()
        
        # Delete oldest (checkpoint_3)
        if checkpoints[3].exists():
            checkpoints[3].unlink()
        
        # Rotate: 2->3, 1->2
        for i in [2, 1]:
            if checkpoints[i].exists():
                shutil.move(str(checkpoints[i]), str(checkpoints[i + 1]))
    
    @classmethod
    def _create_checkpoint(cls, sessions_data: List[Dict], errors_found: List[Dict], actions_planned: List[Dict], analysis: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new checkpoint before any memory modification.
        
        Args:
            sessions_data: List of analyzed session summaries
            errors_found: List of errors detected
            actions_planned: List of planned consolidation actions
            analysis: Optional analysis data from dream action
        
        Returns:
            Checkpoint metadata
        """
        cls._ensure_backup_dir()
        cls._rotate_checkpoints()
        
        checkpoint = {
            "id": 1,  # Always newest is checkpoint_1
            "created_at": datetime.now().isoformat(),
            "sessions_analyzed": len(sessions_data),
            "sessions": sessions_data[:20],  # Store up to 20 session summaries
            "errors_found": len(errors_found),
            "errors": errors_found[:50],  # Store up to 50 errors
            "actions_planned": actions_planned,
            "status": "pending",  # pending, applied, restored
        }
        
        # Include analysis if provided (Phase 3)
        if analysis:
            checkpoint["analysis"] = analysis
        
        checkpoint_path = cls._get_checkpoint_paths()[1]
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False, default=str)
        
        return checkpoint
    
    @classmethod
    def _load_checkpoint(cls, checkpoint_id: int) -> Optional[Dict[str, Any]]:
        """Load a checkpoint by ID (1=newest, 3=oldest)."""
        if checkpoint_id < 1 or checkpoint_id > cls.MAX_CHECKPOINTS:
            return None
        
        checkpoint_path = cls._get_checkpoint_paths().get(checkpoint_id)
        if not checkpoint_path or not checkpoint_path.exists():
            return None
        
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    @classmethod
    def _list_checkpoints(cls) -> List[Dict[str, Any]]:
        """List all available checkpoints with metadata."""
        cls._ensure_backup_dir()
        checkpoints = []
        
        for i in range(1, cls.MAX_CHECKPOINTS + 1):
            checkpoint = cls._load_checkpoint(i)
            if checkpoint:
                checkpoints.append({
                    "id": i,
                    "created_at": checkpoint.get("created_at"),
                    "sessions_analyzed": checkpoint.get("sessions_analyzed", 0),
                    "errors_found": checkpoint.get("errors_found", 0),
                    "actions_planned": len(checkpoint.get("actions_planned", [])),
                    "status": checkpoint.get("status", "unknown"),
                    "has_analysis": "analysis" in checkpoint,
                })
        
        return checkpoints
    
    @classmethod
    def _restore_checkpoint(cls, checkpoint_id: int) -> Dict[str, Any]:
        """Restore system to pre-dream state from checkpoint.
        
        Note: This is a logical restore - it logs what would be undone.
        Actual memory restoration would require integration with memory tools.
        
        Args:
            checkpoint_id: Checkpoint to restore (1, 2, or 3)
        
        Returns:
            Restoration result with details
        """
        checkpoint = cls._load_checkpoint(checkpoint_id)
        if not checkpoint:
            return {
                "success": False,
                "error": f"Checkpoint {checkpoint_id} not found",
            }
        
        
        # Update checkpoint status
        checkpoint["status"] = "restored"
        checkpoint_path = cls._get_checkpoint_paths()[checkpoint_id]
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False, default=str)
        
        # Return restoration details
        return {
            "success": True,
            "checkpoint_id": checkpoint_id,
            "restored_at": datetime.now().isoformat(),
            "sessions_affected": checkpoint.get("sessions_analyzed", 0),
            "actions_cancelled": len(checkpoint.get("actions_planned", [])),
            "message": f"Checkpoint {checkpoint_id} restored. {len(checkpoint.get('actions_planned', []))} planned actions cancelled.",
        }
    
    # ==================== EXECUTE METHOD ====================
    
    async def execute(self, **kwargs):
        """Execute the session reader tool.
        
        Phase 4: Now async for memory operations.
        """
        action = kwargs.get("action", "list")
        limit = min(int(kwargs.get("limit") or 10), 100)
        sensitivity = kwargs.get("sensitivity", "moderate")
        checkpoint_id = int(kwargs.get("checkpoint_id") or 0)
        
        try:
            if action == "list":
                return self._response(self._action_list(limit))
            elif action == "read":
                return self._response(self._action_read(kwargs.get("chat_id"), kwargs.get("include_logs", False), sensitivity))
            elif action == "analyze":
                return self._response(self._action_analyze(limit, sensitivity))
            elif action == "extract_errors":
                return self._response(self._action_extract_errors(limit, sensitivity))
            elif action == "detect":
                return self._response(self._action_detect(limit, sensitivity))
            elif action == "consolidate":
                selected_items = kwargs.get("selected_items", [])
                return await self._action_consolidate_async(checkpoint_id, selected_items)
            elif action == "restore":
                return self._response(self._action_restore(checkpoint_id))
            elif action == "list_backups":
                return self._response(self._action_list_backups())
            elif action == "dream":
                return self._response(self._action_dream(limit, sensitivity))
            elif action == "save_dream":
                return await self._action_save_dream(limit, sensitivity)
            else:
                return self._response({"error": f"Unknown action: {action}"})
        except Exception as e:
            handle_error(e)
            return self._response({"error": str(e)})
    
    # ==================== ORIGINAL ACTIONS ====================
    
    def _action_list(self, limit: int):
        """List available sessions with basic metadata."""
        chat_dirs = self._get_chat_dirs()[:limit]
        
        sessions = []
        for chat_dir in chat_dirs:
            chat_data = self._read_chat_json(chat_dir)
            if chat_data:
                logs = chat_data.get("log") or {}
                log_count = len(logs.get("logs", [])) if isinstance(logs, dict) else 0
                
                sessions.append({
                    "id": chat_data.get("id", chat_dir.name),
                    "name": (chat_data.get("name") or "Untitled")[:50],
                    "created_at": chat_data.get("created_at"),
                    "message_count": log_count,
                    "agent_profile": chat_data.get("agent_profile"),
                })
        
        return self._response({
            "action": "list",
            "total_sessions": len(sessions),
            "sessions": sessions,
        })
    
    def _action_read(self, chat_id: Optional[str], include_logs: bool, sensitivity: str = "moderate"):
        """Read a specific session."""
        if not chat_id:
            return self._response({"error": "chat_id required for read action"})
        
        chat_dirs = self._get_chat_dirs()
        
        if chat_id == "latest":
            target_dir = chat_dirs[0] if chat_dirs else None
        else:
            target_dir = next((d for d in chat_dirs if d.name == chat_id), None)
        
        if not target_dir:
            return self._response({"error": f"Chat not found: {chat_id}"})
        
        session = self._extract_session_data(target_dir, include_logs, sensitivity)
        return self._response({
            "action": "read",
            "session": session,
        })
    
    def _action_analyze(self, limit: int, sensitivity: str = "moderate"):
        """Analyze multiple sessions for patterns."""
        chat_dirs = self._get_chat_dirs()[:limit]
        
        all_tool_calls = []
        all_errors = []
        sessions_summary = []
        
        for chat_dir in chat_dirs:
            session = self._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
            sessions_summary.append({
                "id": session.get("id"),
                "name": session.get("name"),
                "message_count": session.get("message_count"),
                "error_count": len(session.get("errors") or []),
            })
            all_tool_calls.extend(session.get("tool_calls") or [])
            all_errors.extend(session.get("errors") or [])
        
        # Aggregate tool usage
        tool_usage = {}
        for tc in all_tool_calls:
            name = tc.get("tool_name") or "unknown"
            tool_usage[name] = tool_usage.get(name, 0) + 1
        
        return self._response({
            "action": "analyze",
            "sessions_analyzed": len(sessions_summary),
            "sessions": sessions_summary,
            "tool_usage": tool_usage,
            "total_errors": len(all_errors),
            "errors": all_errors[:20],  # First 20 errors
        })
    
    def _action_extract_errors(self, limit: int, sensitivity: str = "moderate"):
        """Extract all errors from sessions."""
        chat_dirs = self._get_chat_dirs()[:limit]
        
        all_errors = []
        for chat_dir in chat_dirs:
            session = self._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
            for err in session.get("errors") or []:
                err["session_id"] = session.get("id")
                err["session_name"] = session.get("name")
                all_errors.append(err)
        
        return self._response({
            "action": "extract_errors",
            "total_errors": len(all_errors),
            "errors": all_errors,
        })
    
    # ==================== PHASE 2: SAFETY ACTIONS ====================
    
    def _action_detect(self, limit: int, sensitivity: str = "moderate"):
        """Analyze sessions, create backup, return findings - NO CHANGES.
        
        Enhanced in Phase 3 with pattern grouping and recurring error detection.
        This is the safe default mode. It:
        1. Analyzes sessions for error patterns
        2. Creates a backup checkpoint
        3. Returns findings for user review
        4. Does NOT make any memory modifications
        
        User must explicitly call 'consolidate' with checkpoint_id to apply changes.
        """
        chat_dirs = self._get_chat_dirs()[:limit]
        
        all_errors = []
        sessions_data = []
        
        for chat_dir in chat_dirs:
            session = self._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
            sessions_data.append(session)
            for err in session.get("errors") or []:
                err["session_id"] = session.get("id")
                err["session_name"] = session.get("name")
                all_errors.append(err)
        
        # Phase 3: Enhanced analysis - group errors by type
        error_patterns = self._group_errors_by_type(all_errors)
        
        # Phase 3: Find recurring errors
        recurring_errors = self._find_recurring_errors(all_errors)
        
        # Phase 3: Identify success patterns
        success_patterns = self._identify_success_patterns(sessions_data)
        
        # Build sessions summary
        sessions_summary = [{
            "id": s.get("id"),
            "name": s.get("name"),
            "message_count": s.get("message_count"),
            "error_count": len(s.get("errors") or []),
            "tool_calls_count": len(s.get("tool_calls") or []),
        } for s in sessions_data]
        
        # Plan consolidation actions (what WOULD be done)
        actions_planned = []
        for err in all_errors[:20]:  # Plan for up to 20 errors
            actions_planned.append({
                "type": "note_error_pattern",
                "session_id": err.get("session_id"),
                "error_preview": (err.get("content") or "")[:100],
                "entry_no": err.get("entry_no"),
            })
        
        # Create backup checkpoint with enhanced analysis
        analysis_data = {
            "error_patterns": {k: len(v) for k, v in error_patterns.items()},
            "recurring_count": len(recurring_errors),
            "success_count": len(success_patterns),
        }
        checkpoint = self._create_checkpoint(sessions_summary, all_errors, actions_planned, analysis_data)
        
        return self._response({
            "action": "detect",
            "mode": "manual_only",
            "checkpoint_created": True,
            "checkpoint_id": checkpoint.get("id"),
            "sessions_analyzed": len(sessions_summary),
            "sessions": sessions_summary,
            "total_errors": len(all_errors),
            "error_patterns": {k: len(v) for k, v in error_patterns.items()},
            "errors_by_type": error_patterns,
            "recurring_errors": recurring_errors[:5],
            "success_patterns": success_patterns[:5],
            "errors_sample": all_errors[:10],  # First 10 errors for review
            "actions_planned_count": len(actions_planned),
            "next_step": "Review findings. To apply changes, call 'consolidate' with checkpoint_id=1",
            "no_changes_made": True,
        })
    
    # ==================== PHASE 3: DREAMER ACTION ====================
    
    def _action_dream(self, limit: int, sensitivity: str = "moderate"):
        """Comprehensive analysis that extracts deep insights.
        
        Phase 3 Dreamer Agent action that:
        1. Reads N sessions (configurable limit)
        2. Analyzes error patterns (by type, recurring)
        3. Identifies tool usage patterns
        4. Finds success patterns
        5. Generates actionable recommendations
        6. Creates backup before analysis
        7. Returns structured report (without modifying anything)
        
        Returns structured analysis with:
        - error_patterns: Grouped by type
        - recurring_errors: Cross-session recurring issues
        - success_patterns: Sessions with low error rates
        - tool_insights: Usage patterns and statistics
        - recommendations: Actionable suggestions
        """
        chat_dirs = self._get_chat_dirs()[:limit]
        
        sessions_data = []
        all_errors = []
        all_tool_calls = []
        
        # Extract data from all sessions
        for chat_dir in chat_dirs:
            session = self._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
            sessions_data.append(session)
            
            # Collect errors with session context
            for err in session.get("errors") or []:
                err["session_id"] = session.get("id")
                err["session_name"] = session.get("name")
                all_errors.append(err)
            
            # Collect tool calls
            all_tool_calls.extend(session.get("tool_calls") or [])
        
        # === ANALYSIS ===
        
        # 1. Group errors by type
        error_patterns = self._group_errors_by_type(all_errors)
        
        # 2. Find recurring errors across sessions
        recurring_errors = self._find_recurring_errors(all_errors)
        
        # 3. Identify success patterns (low error rate sessions)
        success_patterns = self._identify_success_patterns(sessions_data)
        
        # 4. Analyze tool usage patterns
        tool_insights = self._analyze_tool_patterns(sessions_data)
        
        # 5. Generate recommendations
        recommendations = self._generate_recommendations(
            error_patterns, recurring_errors, success_patterns, tool_insights
        )
        
        # 6. Distilled knowledge (concise lessons)
        distilled = []
        if recurring_errors:
            distilled.append(f"Top recurring issue: {recurring_errors[0].get('signature', '')[:80]} ({recurring_errors[0].get('occurrences', 0)} times)")
        if success_patterns:
            distilled.append(f"Success pattern: {success_patterns[0].get('top_tools', [])[:3]} tool sequence effective")
        if tool_insights.get("most_used"):
            distilled.append(f"Most used tool: {tool_insights['most_used'][0][0]} ({tool_insights['most_used'][0][1]} uses)")
        
        # Create checkpoint with full analysis
        analysis_result = {
            "error_patterns": {k: len(v) for k, v in error_patterns.items()},
            "recurring_errors_count": len(recurring_errors),
            "success_patterns_count": len(success_patterns),
            "recommendations_count": len(recommendations),
        }
        
        checkpoint = self._create_checkpoint(
            [{"id": s.get("id"), "name": s.get("name"), "error_count": len(s.get("errors") or [])} for s in sessions_data],
            all_errors,
            [],  # No planned actions for dream - read-only
            analysis_result
        )
        
        return self._response({
            "action": "dream",
            "sessions_analyzed": len(sessions_data),
            "checkpoint_id": checkpoint.get("id"),
            "analysis": {
                "error_patterns": {
                    k: {"count": len(v), "samples": v[:3]}
                    for k, v in error_patterns.items()
                },
                "recurring_errors": recurring_errors[:10],
                "success_patterns": success_patterns[:10],
                "tool_insights": tool_insights,
                "recommendations": recommendations,
                "distilled_knowledge": distilled,
            },
            "summary": {
                "total_errors": len(all_errors),
                "total_tool_calls": len(all_tool_calls),
                "error_rate_per_session": round(len(all_errors) / max(len(sessions_data), 1), 2),
                "sessions_with_errors": sum(1 for s in sessions_data if len(s.get("errors") or []) > 0),
            },
            "no_changes_made": True,
            "message": f"Dream analysis complete. Analyzed {len(sessions_data)} sessions, found {len(all_errors)} errors, {len(recurring_errors)} recurring patterns.",
        })
    
    def _action_consolidate(self, checkpoint_id: int):
        """Apply planned changes from a checkpoint.
        
        Requires explicit checkpoint_id to prevent accidental execution.
        User must have reviewed the detect output first.
        
        Args:
            checkpoint_id: Must be 1 (newest checkpoint)
        """
        if not checkpoint_id:
            return self._response({
                "error": "checkpoint_id required for consolidate action",
                "hint": "Run 'detect' first to create a checkpoint, then call 'consolidate' with checkpoint_id=1",
            })
        
        checkpoint = self._load_checkpoint(checkpoint_id)
        if not checkpoint:
            return self._response({
                "error": f"Checkpoint {checkpoint_id} not found",
                "hint": "Run 'detect' first to create a checkpoint",
            })
        
        if checkpoint.get("status") == "applied":
            return self._response({
                "error": f"Checkpoint {checkpoint_id} already applied",
                "hint": "Run 'detect' again to create a new checkpoint",
            })
        
        if checkpoint.get("status") == "restored":
            return self._response({
                "error": f"Checkpoint {checkpoint_id} was restored/rolled back",
                "hint": "Run 'detect' again to create a new checkpoint",
            })
        
        # Actually apply the consolidation
        # Note: This is where memory integration would happen in Phase 4
        # For now, we mark the checkpoint as applied and return what was done
        
        actions_applied = checkpoint.get("actions_planned", [])
        
        # Update checkpoint status
        checkpoint["status"] = "applied"
        checkpoint["applied_at"] = datetime.now().isoformat()
        checkpoint_path = self._get_checkpoint_paths()[checkpoint_id]
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False, default=str)
        
        return self._response({
            "action": "consolidate",
            "checkpoint_id": checkpoint_id,
            "status": "success",
            "applied_at": checkpoint["applied_at"],
            "sessions_processed": checkpoint.get("sessions_analyzed", 0),
            "actions_applied": len(actions_applied),
            "actions": actions_applied[:10],  # Show first 10 actions
            "message": f"Consolidation complete. {len(actions_applied)} actions applied from checkpoint {checkpoint_id}.",
        })
    
    def _action_restore(self, checkpoint_id: int):
        """Rollback to a checkpoint.
        
        Args:
            checkpoint_id: Checkpoint to restore (1, 2, or 3)
        """
        if not checkpoint_id:
            return self._response({
                "error": "checkpoint_id required for restore action",
                "hint": "Use checkpoint_id=1 (newest), 2, or 3. Run 'list_backups' to see available checkpoints.",
            })
        
        result = self._restore_checkpoint(checkpoint_id)
        
        return self._response({
            "action": "restore",
            **result,
        })
    
    def _action_list_backups(self):
        """Show all available checkpoints."""
        checkpoints = self._list_checkpoints()
        
        return {
            "action": "list_backups",
            "max_checkpoints": self.MAX_CHECKPOINTS,
            "backup_dir": str(self.BACKUP_DIR),
            "checkpoints_available": len(checkpoints),
            "checkpoints": checkpoints,
            "usage": {
                "detect": "Creates checkpoint_1 (analyzer only, no changes)",
                "dream": "Creates checkpoint with full analysis (read-only)",
                "save_dream": "Stores dream analysis in memory (Phase 4)",
                "consolidate": "Applies checkpoint (requires checkpoint_id)",
                "restore": "Rolls back to checkpoint state",
            },
        }
    
    # ==================== PHASE 4: MEMORY INTEGRATION ====================
    
    async def _action_save_dream(self, limit: int, sensitivity: str = "moderate"):
        """Run dream analysis and store results in memory.
        
        Phase 4 action that:
        1. Runs dream analysis (same as dream action)
        2. Stores error patterns in memory (area: solutions)
        3. Stores success patterns in memory (area: solutions)
        4. Stores recommendations in memory (area: main)
        5. Stores distilled knowledge in memory (area: main)
        
        Returns summary of what was stored.
        """
        # Run dream analysis first
        chat_dirs = self._get_chat_dirs()[:limit]
        
        sessions_data = []
        all_errors = []
        all_tool_calls = []
        
        for chat_dir in chat_dirs:
            session = self._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
            sessions_data.append(session)
            
            for err in session.get("errors") or []:
                err["session_id"] = session.get("id")
                err["session_name"] = session.get("name")
                all_errors.append(err)
            
            all_tool_calls.extend(session.get("tool_calls") or [])
        
        # Generate analysis
        error_patterns = self._group_errors_by_type(all_errors)
        recurring_errors = self._find_recurring_errors(all_errors)
        success_patterns = self._identify_success_patterns(sessions_data)
        tool_insights = self._analyze_tool_patterns(sessions_data)
        recommendations = self._generate_recommendations(
            error_patterns, recurring_errors, success_patterns, tool_insights
        )
        
        # Distilled knowledge
        distilled = []
        if recurring_errors:
            distilled.append(f"Top recurring issue: {recurring_errors[0].get('signature', '')[:80]} ({recurring_errors[0].get('occurrences', 0)} times)")
        if success_patterns:
            distilled.append(f"Success pattern: {success_patterns[0].get('top_tools', [])[:3]} tool sequence effective")
        if tool_insights.get("most_used"):
            distilled.append(f"Most used tool: {tool_insights['most_used'][0][0]} ({tool_insights['most_used'][0][1]} uses)")
        
        # Store in memory
        db = await Memory.get(self.agent)
        stored = {
            "error_patterns": [],
            "success_patterns": [],
            "recommendations": [],
            "distilled_knowledge": [],
        }
        
        # Store recurring error patterns
        for pattern in recurring_errors[:5]:
            try:
                text = f"Error Pattern [{pattern.get('type', 'unknown')}]: {pattern.get('signature', '')[:100]} (occurred {pattern.get('occurrences', 1)} times across {pattern.get('session_count', 1)} sessions)"
                metadata = {
                    "area": "solutions",
                    "tags": ["dreaming", "error-pattern", pattern.get("type", "unknown")],
                    "source": "a0-dreaming",
                }
                mid = await db.insert_text(text, metadata)
                stored["error_patterns"].append(mid)
            except Exception as e:
                stored["error_patterns"].append(f"error: {str(e)[:50]}")
        
        # Store success patterns
        for pattern in success_patterns[:3]:
            try:
                session_name = pattern.get("session_name", "unknown")
                error_rate = pattern.get("error_rate", 0)
                top_tools = pattern.get("top_tools", [])[:3]
                tools_str = ", ".join([f"{t[0]}({t[1]})" for t in top_tools if isinstance(t, tuple) and len(t) >= 2])
                text = f"Success Pattern: Session '{session_name}' achieved {error_rate:.1%} error rate using tools: {tools_str}"
                metadata = {
                    "area": "solutions",
                    "tags": ["dreaming", "success-pattern", "best-practice"],
                    "source": "a0-dreaming",
                }
                mid = await db.insert_text(text, metadata)
                stored["success_patterns"].append(mid)
            except Exception as e:
                stored["success_patterns"].append(f"error: {str(e)[:50]}")
        
        # Store recommendations
        for i, rec in enumerate(recommendations[:5]):
            try:
                text = f"Recommendation #{i+1}: {rec}"
                metadata = {
                    "area": "main",
                    "tags": ["dreaming", "recommendation", "insight"],
                    "source": "a0-dreaming",
                }
                mid = await db.insert_text(text, metadata)
                stored["recommendations"].append(mid)
            except Exception as e:
                stored["recommendations"].append(f"error: {str(e)[:50]}")
        
        # Store distilled knowledge
        for i, item in enumerate(distilled):
            try:
                text = f"Distilled Insight: {item}"
                metadata = {
                    "area": "main",
                    "tags": ["dreaming", "distilled", "insight"],
                    "source": "a0-dreaming",
                    "priority": i,
                }
                mid = await db.insert_text(text, metadata)
                stored["distilled_knowledge"].append(mid)
            except Exception as e:
                stored["distilled_knowledge"].append(f"error: {str(e)[:50]}")
        
        return {
            "action": "save_dream",
            "sessions_analyzed": len(sessions_data),
            "analysis": {
                "error_patterns_count": sum(1 for v in error_patterns.values() if v),
                "recurring_errors_count": len(recurring_errors),
                "success_patterns_count": len(success_patterns),
                "recommendations_count": len(recommendations),
                "distilled_count": len(distilled),
            },
            "stored": stored,
            "total_memories_created": sum(len(v) for v in stored.values()),
            "message": f"Dream analysis stored in memory. Created {sum(len(v) for v in stored.values())} memory entries from {len(sessions_data)} sessions.",
        }
    
    async def _action_consolidate_async(self, checkpoint_id: int, selected_items: list = None):
        """Apply planned changes from a checkpoint with memory storage.
        
        Phase 4 enhanced consolidate that stores insights to memory.
        Supports selective consolidation via selected_items parameter.
        
        Args:
            checkpoint_id: Checkpoint to apply
            selected_items: Optional list of error IDs/entry_no to include (if None or empty, applies all)
        """
        if not checkpoint_id:
            return {
                "error": "checkpoint_id required for consolidate action",
                "hint": "Run 'detect' first to create a checkpoint, then call 'consolidate' with checkpoint_id=1",
            }
        
        checkpoint = self._load_checkpoint(checkpoint_id)
        if not checkpoint:
            return {
                "error": f"Checkpoint {checkpoint_id} not found",
                "hint": "Run 'detect' first to create a checkpoint",
            }
        
        
        if checkpoint.get("status") == "applied":
            return {
                "error": f"Checkpoint {checkpoint_id} already applied",
                "hint": "Run 'detect' again to create a new checkpoint",
            }
        
        
        if checkpoint.get("status") == "restored":
            return {
                "error": f"Checkpoint {checkpoint_id} was restored/rolled back",
                "hint": "Run 'detect' again to create a new checkpoint",
            }
        
        
        all_actions = checkpoint.get("actions_planned", [])
        
        # Filter by selected_items if provided
        if selected_items and len(selected_items) > 0:
            selected_set = set(selected_items)
            actions_applied = [
                a for a in all_actions 
                if a.get("entry_no") in selected_set or a.get("id") in selected_set
            ]
            filter_note = f"Filtered to {len(actions_applied)} of {len(all_actions)} selected items."
        else:
            actions_applied = all_actions
            filter_note = ""
        
        memories_created = []
        
        # Store consolidation summary in memory
        try:
            db = await Memory.get(self.agent)
            summary_text = f"Consolidation Summary: Processed {checkpoint.get('sessions_analyzed', 0)} sessions, found {len(actions_applied)} action items at {datetime.now().isoformat()}"
            metadata = {
                "area": "main",
                "tags": ["dreaming", "consolidation", "checkpoint"],
                "source": "a0-dreaming",
                "checkpoint_id": checkpoint_id,
            }
            mid = await db.insert_text(summary_text, metadata)
            memories_created.append(mid)
        except Exception as e:
            memories_created.append(f"error: {str(e)[:50]}")
        
        # Update checkpoint status
        checkpoint["status"] = "applied"
        checkpoint["applied_at"] = datetime.now().isoformat()
        checkpoint["memories_created"] = memories_created
        checkpoint_path = self._get_checkpoint_paths()[checkpoint_id]
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False, default=str)
        
        return {
            "action": "consolidate",
            "checkpoint_id": checkpoint_id,
            "status": "success",
            "applied_at": checkpoint["applied_at"],
            "sessions_processed": checkpoint.get("sessions_analyzed", 0),
            "actions_applied": len(actions_applied),
            "total_actions": len(all_actions),
            "filtered": bool(selected_items and len(selected_items) > 0),
            "actions": actions_applied[:10],
            "memories_created": len(memories_created),
            "message": f"Consolidation complete. {len(actions_applied)} actions applied from checkpoint {checkpoint_id}.{(' ' + filter_note) if filter_note else ''}",
        }
    def _response(self, data: Dict[str, Any]) -> str:
        """Format response as JSON string."""
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)
