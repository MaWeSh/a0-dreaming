"""
Memory helper module for a0-dreaming plugin.

Provides functions to store distilled insights from dream analysis
into Agent Zero's memory system for cross-session learning.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
import json

# Import Memory from the _memory plugin
from plugins._memory.helpers.memory import Memory


def _format_error_pattern(pattern: Dict[str, Any]) -> str:
    """Format an error pattern for memory storage."""
    error_type = pattern.get("type", "unknown")
    signature = pattern.get("signature", "")[:100]
    occurrences = pattern.get("occurrences", 1)
    sessions = pattern.get("session_count", 1)
    
    return f"Error Pattern [{error_type}]: {signature} (occurred {occurrences} times across {sessions} sessions)"


def _format_success_pattern(pattern: Dict[str, Any]) -> str:
    """Format a success pattern for memory storage."""
    session_name = pattern.get("session_name", "unknown")
    error_rate = pattern.get("error_rate", 0)
    top_tools = pattern.get("top_tools", [])[:3]
    tools_str = ", ".join([f"{t[0]}({t[1]})" for t in top_tools if isinstance(t, tuple) and len(t) >= 2])
    
    return f"Success Pattern: Session '{session_name}' achieved {error_rate:.1%} error rate using tools: {tools_str}"


def _format_recommendation(rec: str, index: int) -> str:
    """Format a recommendation for memory storage."""
    return f"Recommendation #{index}: {rec}"


async def store_error_pattern(agent, pattern: Dict[str, Any]) -> str:
    """Store an error pattern in memory.
    
    Args:
        agent: Agent instance for memory access
        pattern: Error pattern dict with type, signature, occurrences, session_count
    
    Returns:
        Memory ID of stored pattern
    """
    db = await Memory.get(agent)
    
    text = _format_error_pattern(pattern)
    error_type = pattern.get("type", "unknown")
    
    metadata = {
        "area": "solutions",
        "tags": ["dreaming", "error-pattern", error_type],
        "source": "a0-dreaming",
        "stored_at": datetime.now().isoformat(),
    }
    
    memory_id = await db.insert_text(text, metadata)
    return memory_id


async def store_success_pattern(agent, pattern: Dict[str, Any]) -> str:
    """Store a success pattern in memory.
    
    Args:
        agent: Agent instance for memory access
        pattern: Success pattern dict with session_name, error_rate, top_tools
    
    Returns:
        Memory ID of stored pattern
    """
    db = await Memory.get(agent)
    
    text = _format_success_pattern(pattern)
    
    metadata = {
        "area": "solutions",
        "tags": ["dreaming", "success-pattern", "best-practice"],
        "source": "a0-dreaming",
        "stored_at": datetime.now().isoformat(),
    }
    
    memory_id = await db.insert_text(text, metadata)
    return memory_id


async def store_recommendation(agent, recommendation: str, index: int = 1) -> str:
    """Store a recommendation in memory.
    
    Args:
        agent: Agent instance for memory access
        recommendation: Recommendation text
        index: Recommendation number for ordering
    
    Returns:
        Memory ID of stored recommendation
    """
    db = await Memory.get(agent)
    
    text = _format_recommendation(recommendation, index)
    
    metadata = {
        "area": "main",
        "tags": ["dreaming", "recommendation", "insight"],
        "source": "a0-dreaming",
        "stored_at": datetime.now().isoformat(),
    }
    
    memory_id = await db.insert_text(text, metadata)
    return memory_id


async def store_distilled_knowledge(agent, distilled: List[str]) -> List[str]:
    """Store distilled knowledge items in memory.
    
    Args:
        agent: Agent instance for memory access
        distilled: List of distilled knowledge strings
    
    Returns:
        List of memory IDs for stored items
    """
    db = await Memory.get(agent)
    memory_ids = []
    
    for i, item in enumerate(distilled):
        text = f"Distilled Insight: {item}"
        
        metadata = {
            "area": "main",
            "tags": ["dreaming", "distilled", "insight"],
            "source": "a0-dreaming",
            "stored_at": datetime.now().isoformat(),
            "priority": i,  # Lower = higher priority
        }
        
        memory_id = await db.insert_text(text, metadata)
        memory_ids.append(memory_id)
    
    return memory_ids


async def get_dream_memories(agent, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve dream-related memories.
    
    Args:
        agent: Agent instance for memory access
        limit: Maximum number of memories to retrieve
    
    Returns:
        List of memory documents related to dreaming
    """
    db = await Memory.get(agent)
    
    # Search for dream-related memories
    # Note: This uses similarity search with "dreaming" as query
    results = await db.searchSimilar("dreaming error pattern success recommendation", k=limit)
    
    # Filter to only dream-related memories
    dream_memories = []
    for doc, score in results:
        metadata = doc.metadata or {}
        if "dreaming" in metadata.get("tags", []):
            dream_memories.append({
                "id": doc.id,
                "content": doc.page_content,
                "metadata": metadata,
                "score": score,
            })
    
    return dream_memories


async def store_dream_analysis(agent, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Store complete dream analysis results.
    
    Stores error patterns, success patterns, recommendations, and distilled knowledge.
    
    Args:
        agent: Agent instance for memory access
        analysis: Complete analysis dict from dream action
    
    Returns:
        Summary of what was stored
    """
    stored = {
        "error_patterns": [],
        "success_patterns": [],
        "recommendations": [],
        "distilled_knowledge": [],
    }
    
    # Store recurring error patterns
    recurring = analysis.get("recurring_errors", [])
    for pattern in recurring[:5]:  # Top 5 recurring errors
        try:
            mid = await store_error_pattern(agent, pattern)
            stored["error_patterns"].append(mid)
        except Exception as e:
            stored["error_patterns"].append(f"error: {str(e)[:50]}")
    
    # Store success patterns
    success = analysis.get("success_patterns", [])
    for pattern in success[:3]:  # Top 3 success patterns
        try:
            mid = await store_success_pattern(agent, pattern)
            stored["success_patterns"].append(mid)
        except Exception as e:
            stored["success_patterns"].append(f"error: {str(e)[:50]}")
    
    # Store recommendations
    recommendations = analysis.get("recommendations", [])
    for i, rec in enumerate(recommendations[:5]):  # Top 5 recommendations
        try:
            mid = await store_recommendation(agent, rec, i + 1)
            stored["recommendations"].append(mid)
        except Exception as e:
            stored["recommendations"].append(f"error: {str(e)[:50]}")
    
    # Store distilled knowledge
    distilled = analysis.get("distilled_knowledge", [])
    if distilled:
        try:
            stored["distilled_knowledge"] = await store_distilled_knowledge(agent, distilled)
        except Exception as e:
            stored["distilled_knowledge"] = [f"error: {str(e)[:50]}"]
    
    return stored
