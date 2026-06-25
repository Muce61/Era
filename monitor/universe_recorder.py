import json
import os
from datetime import datetime
from pathlib import Path
import threading

class UniverseRecorder:
    def __init__(self, save_dir="logs/universe_history"):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.current_file = self.save_dir / f"universe_{datetime.now().strftime('%Y%m%d')}.json"
        self.lock = threading.Lock()
        
    def record_universe(self, active_symbols):
        """
        Append current universe to daily JSONL file.
        Format: {"timestamp": "...", "symbols": [...]}
        """
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbols": list(active_symbols)
        }
        
        # Periodic check for date rollover
        new_filename = self.save_dir / f"universe_{datetime.now().strftime('%Y%m%d')}.jsonl"
        
        try:
            with self.lock:
                with open(new_filename, 'a') as f:
                    f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"Error recording universe: {e}")
