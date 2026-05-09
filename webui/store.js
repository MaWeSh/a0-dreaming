import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";

export const store = createStore("dreamingStore", {
    // Configuration state
    sensitivity: 'moderate',
    schedule: 'manual',
    
    // Checkpoint data
    checkpoints: [],
    
    // Detection results
    pendingItems: [],
    selectedItems: [],
    
    // UI state
    status: 'idle',
    lastRun: null,
    lastRunTime: null,
    loading: false,
    error: null,
    
    // Statistics
    stats: {
        sessions_analyzed: 0,
        errors_found: 0,
        patterns_detected: 0
    },
    
    /**
     * Initialize store when modal opens
     */
    onOpen() {
        this.loadCheckpoints();
        this.loadStats();
    },
    
    /**
     * Cleanup when modal closes
     */
    cleanup() {
        this.selectedItems = [];
        this.error = null;
    },
    
    /**
     * Run error detection on sessions
     */
    async runDetection() {
        this.loading = true;
        this.status = 'detecting';
        this.error = null;
        
        try {
            const result = await callJsonApi('/api/plugins/a0_dreaming/dreaming', {
                action: 'detect',
                sensitivity: this.sensitivity,
                limit: 10
            });
            
            if (result.error) {
                throw new Error(result.error);
            }
            
            // Update state with detection results
            this.checkpoints = await this._fetchCheckpoints();
            this.pendingItems = result.errors || [];
            this.stats.sessions_analyzed = result.sessions_analyzed || 0;
            this.stats.errors_found = result.errors_found || 0;
            this.stats.patterns_detected = result.patterns_detected || 0;
            this.lastRun = new Date().toISOString();
            this.lastRunTime = new Date().toLocaleTimeString();
            this.status = 'completed';
            
            toastFrontendSuccess(
                `Detection complete: ${this.stats.errors_found} errors found in ${this.stats.sessions_analyzed} sessions`,
                "Dreaming"
            );
        } catch (e) {
            this.error = e.message;
            this.status = 'error';
            toastFrontendError(`Detection failed: ${e.message}`, "Dreaming");
        } finally {
            this.loading = false;
        }
    },
    
    /**
     * Run dream analysis
     */
    async runDream() {
        this.loading = true;
        this.status = 'dreaming';
        this.error = null;
        
        try {
            const result = await callJsonApi('/api/plugins/a0_dreaming/dreaming', {
                action: 'dream',
                sensitivity: this.sensitivity,
                limit: 10
            });
            
            if (result.error) {
                throw new Error(result.error);
            }
            
            this.stats.patterns_detected = result.recommendations?.length || 0;
            this.lastRun = new Date().toISOString();
            this.lastRunTime = new Date().toLocaleTimeString();
            this.status = 'completed';
            
            toastFrontendSuccess(
                `Dream analysis complete: ${result.recommendations?.length || 0} recommendations`,
                "Dreaming"
            );
        } catch (e) {
            this.error = e.message;
            this.status = 'error';
            toastFrontendError(`Dream analysis failed: ${e.message}`, "Dreaming");
        } finally {
            this.loading = false;
        }
    },
    
    /**
     * Save dream results to memory
     */
    async saveDream() {
        this.loading = true;
        this.error = null;
        
        try {
            const result = await callJsonApi('/api/plugins/a0_dreaming/dreaming', {
                action: 'save_dream',
                sensitivity: this.sensitivity,
                limit: 10
            });
            
            if (result.error) {
                throw new Error(result.error);
            }
            
            toastFrontendSuccess(
                `Saved ${result.memories_created || 0} memories to knowledge base`,
                "Dreaming"
            );
        } catch (e) {
            this.error = e.message;
            toastFrontendError(`Save failed: ${e.message}`, "Dreaming");
        } finally {
            this.loading = false;
        }
    },
    
    /**
     * Consolidate changes from a checkpoint
     */
    async consolidate(checkpointId) {
        if (!checkpointId) {
            toastFrontendError('No checkpoint selected for consolidation', "Dreaming");
            return;
        }
        
        this.loading = true;
        this.error = null;
        
        try {
            const result = await callJsonApi('/api/plugins/a0_dreaming/dreaming', {
                action: 'consolidate',
                checkpoint_id: checkpointId
            });
            
            if (result.error) {
                throw new Error(result.error);
            }
            
            await this.loadCheckpoints();
            toastFrontendSuccess(
                `Consolidation complete: ${result.actions_applied || 0} actions applied`,
                "Dreaming"
            );
        } catch (e) {
            this.error = e.message;
            toastFrontendError(`Consolidation failed: ${e.message}`, "Dreaming");
        } finally {
            this.loading = false;
        }
    },
    
    /**
     * Restore from a checkpoint
     */
    async restore(checkpointId) {
        if (!checkpointId) {
            toastFrontendError('No checkpoint selected for restore', "Dreaming");
            return;
        }
        
        this.loading = true;
        this.error = null;
        
        try {
            const result = await callJsonApi('/api/plugins/a0_dreaming/dreaming', {
                action: 'restore',
                checkpoint_id: checkpointId
            });
            
            if (result.error) {
                throw new Error(result.error);
            }
            
            await this.loadCheckpoints();
            toastFrontendSuccess(
                `Restored from checkpoint ${checkpointId}`,
                "Dreaming"
            );
        } catch (e) {
            this.error = e.message;
            toastFrontendError(`Restore failed: ${e.message}`, "Dreaming");
        } finally {
            this.loading = false;
        }
    },
    
    /**
     * Load available checkpoints
     */
    async loadCheckpoints() {
        try {
            this.checkpoints = await this._fetchCheckpoints();
        } catch (e) {
            console.warn('Failed to load checkpoints:', e);
        }
    },
    
    async _fetchCheckpoints() {
        const result = await callJsonApi('/api/plugins/a0_dreaming/dreaming', {
            action: 'list_backups'
        });
        return result.checkpoints || [];
    },
    
    /**
     * Load statistics
     */
    async loadStats() {
        try {
            const result = await callJsonApi('/api/plugins/a0_dreaming/dreaming', {
                action: 'list',
                limit: 10
            });
            this.stats.sessions_analyzed = result.total_sessions || 0;
        } catch (e) {
            console.warn('Failed to load stats:', e);
        }
    },
    
    /**
     * Clear all backups (with confirmation)
     */
    async clearAllBackups() {
        if (!confirm('Are you sure you want to delete all checkpoints? This cannot be undone.')) {
            return;
        }
        
        this.loading = true;
        this.error = null;
        
        try {
            // Delete each checkpoint file
            for (let i = 1; i <= 3; i++) {
                const cp = this.checkpoints.find(c => c.id === i);
                if (cp) {
                    await callJsonApi('/api/plugins/a0_dreaming/dreaming', {
                        action: 'restore',
                        checkpoint_id: i
                    });
                }
            }
            
            this.checkpoints = [];
            toastFrontendSuccess('All checkpoints cleared', "Dreaming");
        } catch (e) {
            this.error = e.message;
            toastFrontendError(`Clear failed: ${e.message}`, "Dreaming");
        } finally {
            this.loading = false;
        }
    },
    
    /**
     * Toggle item selection for manual approval
     */
    toggleItem(itemId) {
        const index = this.selectedItems.indexOf(itemId);
        if (index === -1) {
            this.selectedItems.push(itemId);
        } else {
            this.selectedItems.splice(index, 1);
        }
    },
    
    /**
     * Select all pending items
     */
    selectAll() {
        this.selectedItems = this.pendingItems.map(item => item.entry_no || item.id);
    },
    
    /**
     * Deselect all items
     */
    deselectAll() {
        this.selectedItems = [];
    },
    
    /**
     * Execute consolidation for selected items only
     */
    async executeConsolidation() {
        if (this.selectedItems.length === 0) {
            toastFrontendError('No items selected for consolidation', "Dreaming");
            return;
        }
        
        // Use the most recent checkpoint
        const latestCheckpoint = this.checkpoints[0];
        if (!latestCheckpoint) {
            toastFrontendError('No checkpoint available. Run detection first.', "Dreaming");
            return;
        }
        
        await this.consolidate(latestCheckpoint.id);
        this.selectedItems = [];
    },
    
    /**
     * Create a backup now (runs detect)
     */
    async createBackup() {
        await this.runDetection();
    },
    
    /**
     * Format timestamp for display
     */
    formatTime(isoString) {
        if (!isoString) return 'Never';
        try {
            return new Date(isoString).toLocaleString();
        } catch {
            return isoString;
        }
    }
});
