"""API endpoints for a0-dreaming plugin.

Provides HTTP API access to dreaming functionality:
- detect: Analyze sessions for error patterns
- dream: Full analysis with recommendations
- list: List available sessions
- analyze: Analyze multiple sessions
- extract_errors: Extract all errors
- list_backups: Show available checkpoints
- restore: Rollback to checkpoint

Note: consolidate and save_dream require agent context for memory storage.
Use the dreaming tool directly for those actions.
"""
from __future__ import annotations

from helpers.api import ApiHandler, Input, Output, Request
from typing import Dict, Any, List
from datetime import datetime
import json


class Dreaming(ApiHandler):
    """Dreaming API handler - provides HTTP access to session analysis."""

    async def process(self, input: Input, request: Request) -> Output:
        action = input.get("action", "list_backups")
        
        try:
            # Import the tool class to access classmethods
            # Import tool - handle hyphen in folder name
            import sys, os
            plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            from usr.plugins.a0_dreaming.tools.dreaming import Dreaming as DreamingTool
            
            # Extract common parameters
            sensitivity = input.get("sensitivity", "moderate")
            limit = min(int(input.get("limit") or 10), 100)
            checkpoint_id = int(input.get("checkpoint_id") or 0)
            
            if action == "detect":
                return self._run_detect(DreamingTool, limit, sensitivity)
                
            elif action == "dream":
                return self._run_dream(DreamingTool, limit, sensitivity)
                
            elif action == "list":
                return self._run_list(DreamingTool, limit)
                
            elif action == "analyze":
                return self._run_analyze(DreamingTool, limit, sensitivity)
                
            elif action == "extract_errors":
                return self._run_extract_errors(DreamingTool, limit, sensitivity)
                
            elif action == "list_backups":
                return self._run_list_backups(DreamingTool)
                
            elif action == "restore":
                if not checkpoint_id:
                    return {"success": False, "error": "checkpoint_id required for restore action"}
                return self._run_restore(DreamingTool, checkpoint_id)
                
            elif action == "consolidate":
                return {
                    "success": False, 
                    "error": "consolidate requires agent context for memory storage",
                    "hint": "Use the dreaming tool directly: call tool with action='consolidate' and checkpoint_id"
                }
                
            elif action == "save_dream":
                return {
                    "success": False,
                    "error": "save_dream requires agent context for memory storage",
                    "hint": "Use the dreaming tool directly: call tool with action='save_dream'"
                }
                
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
                
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    
    def _run_detect(self, DreamingTool, limit: int, sensitivity: str) -> Dict[str, Any]:
        """Run detection analysis using classmethod helpers."""
        chat_dirs = DreamingTool._get_chat_dirs()[:limit]
        
        all_errors = []
        sessions_data = []
        
        for chat_dir in chat_dirs:
            session = DreamingTool._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
            sessions_data.append(session)
            for err in session.get("errors") or []:
                err["session_id"] = session.get("id")
                err["session_name"] = session.get("name")
                all_errors.append(err)
        
        # Enhanced analysis
        error_patterns = DreamingTool._group_errors_by_type(all_errors)
        recurring_errors = DreamingTool._find_recurring_errors(all_errors)
        success_patterns = DreamingTool._identify_success_patterns(sessions_data)
        
        # Build sessions summary
        sessions_summary = [{
            "id": s.get("id"),
            "name": s.get("name"),
            "message_count": s.get("message_count"),
            "error_count": len(s.get("errors") or []),
            "tool_calls_count": len(s.get("tool_calls") or []),
        } for s in sessions_data]
        
        # Plan consolidation actions
        actions_planned = []
        for err in all_errors[:20]:
            actions_planned.append({
                "type": "note_error_pattern",
                "session_id": err.get("session_id"),
                "error_preview": (err.get("content") or "")[:100],
                "entry_no": err.get("entry_no"),
            })
        
        # Create backup checkpoint
        analysis_data = {
            "error_patterns": {k: len(v) for k, v in error_patterns.items()},
            "patterns_detected": len(recurring_errors),  # Frontend compatibility
            "recurring_count": len(recurring_errors),
            "success_count": len(success_patterns),
        }
        checkpoint = DreamingTool._create_checkpoint(sessions_summary, all_errors, actions_planned, analysis_data)
        
        return {
            "success": True,
            "action": "detect",
            "mode": "manual_only",
            "checkpoint_created": True,
            "checkpoint_id": checkpoint.get("id"),
            "sessions_analyzed": len(sessions_summary),
            "sessions": sessions_summary,
            "total_errors": len(all_errors),
            "errors_found": len(all_errors),  # Frontend compatibility
            "error_patterns": {k: len(v) for k, v in error_patterns.items()},
            "patterns_detected": len(recurring_errors),  # Frontend compatibility
            "errors_by_type": {k: v[:5] for k, v in error_patterns.items()},  # Limit sample
            "recurring_errors": recurring_errors[:5],
            "success_patterns": success_patterns[:5],
            "errors": all_errors[:50],  # Frontend expects 'errors' for pendingItems display
            "errors_sample": all_errors[:10],
            "actions_planned_count": len(actions_planned),
            "next_step": "Review findings. To apply changes, use the dreaming tool with action='consolidate' and checkpoint_id=1",
            "no_changes_made": True,
        }
    
    def _run_dream(self, DreamingTool, limit: int, sensitivity: str) -> Dict[str, Any]:
        """Run dream analysis using classmethod helpers."""
        chat_dirs = DreamingTool._get_chat_dirs()[:limit]
        
        sessions_data = []
        all_errors = []
        all_tool_calls = []
        
        for chat_dir in chat_dirs:
            session = DreamingTool._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
            sessions_data.append(session)
            
            for err in session.get("errors") or []:
                err["session_id"] = session.get("id")
                err["session_name"] = session.get("name")
                all_errors.append(err)
            
            all_tool_calls.extend(session.get("tool_calls") or [])
        
        # Analysis
        error_patterns = DreamingTool._group_errors_by_type(all_errors)
        recurring_errors = DreamingTool._find_recurring_errors(all_errors)
        success_patterns = DreamingTool._identify_success_patterns(sessions_data)
        tool_insights = DreamingTool._analyze_tool_patterns(sessions_data)
        recommendations = DreamingTool._generate_recommendations(
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
        
        # Create checkpoint
        analysis_result = {
            "error_patterns": {k: len(v) for k, v in error_patterns.items()},
            "patterns_detected": len(recurring_errors),  # Frontend compatibility
            "recurring_errors_count": len(recurring_errors),
            "success_patterns_count": len(success_patterns),
            "recommendations_count": len(recommendations),
        }
        
        checkpoint = DreamingTool._create_checkpoint(
            [{"id": s.get("id"), "name": s.get("name"), "error_count": len(s.get("errors") or [])} for s in sessions_data],
            all_errors,
            [],
            analysis_result
        )
        
        return {
            "success": True,
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
            "errors_found": len(all_errors),  # Frontend compatibility
                "total_tool_calls": len(all_tool_calls),
                "error_rate_per_session": round(len(all_errors) / max(len(sessions_data), 1), 2),
                "sessions_with_errors": sum(1 for s in sessions_data if len(s.get("errors") or []) > 0),
            },
            "no_changes_made": True,
            "message": f"Dream analysis complete. Analyzed {len(sessions_data)} sessions, found {len(all_errors)} errors, {len(recurring_errors)} recurring patterns.",
        }
    
    def _run_list(self, DreamingTool, limit: int) -> Dict[str, Any]:
        """List available sessions."""
        chat_dirs = DreamingTool._get_chat_dirs()[:limit]
        
        sessions = []
        for chat_dir in chat_dirs:
            chat_data = DreamingTool._read_chat_json(chat_dir)
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
        
        return {
            "success": True,
            "action": "list",
            "total_sessions": len(sessions),
            "sessions": sessions,
        }
    
    def _run_analyze(self, DreamingTool, limit: int, sensitivity: str) -> Dict[str, Any]:
        """Analyze multiple sessions for patterns."""
        chat_dirs = DreamingTool._get_chat_dirs()[:limit]
        
        all_tool_calls = []
        all_errors = []
        sessions_summary = []
        
        for chat_dir in chat_dirs:
            session = DreamingTool._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
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
        
        return {
            "success": True,
            "action": "analyze",
            "sessions_analyzed": len(sessions_summary),
            "sessions": sessions_summary,
            "tool_usage": tool_usage,
            "total_errors": len(all_errors),
            "errors_found": len(all_errors),  # Frontend compatibility
            "errors": all_errors[:20],
        }
    
    def _run_extract_errors(self, DreamingTool, limit: int, sensitivity: str) -> Dict[str, Any]:
        """Extract all errors from sessions."""
        chat_dirs = DreamingTool._get_chat_dirs()[:limit]
        
        all_errors = []
        for chat_dir in chat_dirs:
            session = DreamingTool._extract_session_data(chat_dir, include_logs=False, sensitivity=sensitivity)
            for err in session.get("errors") or []:
                err["session_id"] = session.get("id")
                err["session_name"] = session.get("name")
                all_errors.append(err)
        
        return {
            "success": True,
            "action": "extract_errors",
            "total_errors": len(all_errors),
            "errors_found": len(all_errors),  # Frontend compatibility
            "errors": all_errors,
        }
    
    def _run_list_backups(self, DreamingTool) -> Dict[str, Any]:
        """Show all available checkpoints."""
        checkpoints = DreamingTool._list_checkpoints()
        
        return {
            "success": True,
            "action": "list_backups",
            "max_checkpoints": DreamingTool.MAX_CHECKPOINTS,
            "backup_dir": str(DreamingTool.BACKUP_DIR),
            "checkpoints_available": len(checkpoints),
            "checkpoints": checkpoints,
            "usage": {
                "detect": "Creates checkpoint_1 (analyzer only, no changes)",
                "dream": "Creates checkpoint with full analysis (read-only)",
                "save_dream": "Stores dream analysis in memory (requires tool)",
                "consolidate": "Applies checkpoint (requires tool)",
                "restore": "Rolls back to checkpoint state",
            },
        }
    
    def _run_restore(self, DreamingTool, checkpoint_id: int) -> Dict[str, Any]:
        """Rollback to a checkpoint."""
        result = DreamingTool._restore_checkpoint(checkpoint_id)
        
        return {
            "success": True,
            "action": "restore",
            **result,
        }
