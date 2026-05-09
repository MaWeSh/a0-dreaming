# A0-Dreaming

Claude-style dreaming for Agent Zero - cross-session error pattern recognition and knowledge distillation.

## Features
- Session analysis with configurable sensitivity
- Error pattern detection across sessions
- Success pattern extraction
- Memory integration for persistent learning
- Backup/restore with 3 checkpoints
- Manual-only mode (user approval required)

## Actions
| Action | Description |
|--------|-------------|
| `detect` | Analyze sessions, create backup, NO changes |
| `dream` | Full analysis with recommendations |
| `save_dream` | Analyze + store insights to memory |
| `consolidate` | Apply changes (requires checkpoint_id) |
| `restore` | Rollback to checkpoint |
| `list_backups` | Show available checkpoints |

## Sensitivity Levels
| Level | Description |
|-------|-------------|
| `strict` | Only tracebacks, explicit exceptions |
| `moderate` | Clear errors (default) |
| `loose` | All candidates including warnings |

## Usage
```json
{"action": "detect", "sensitivity": "strict", "limit": 10}
{"action": "save_dream", "limit": 5}
{"action": "consolidate", "checkpoint_id": 1}
```

## Safety
- Backup before any modification
- Manual approval required for consolidation
- 3 checkpoints retention (FIFO)
- Rollback capability
