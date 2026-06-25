import logging
import os
from datetime import datetime

def setup_logger(name='trading_bot', log_file='trading.log'):
    """
    Setup logger to file and console.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid adding handlers multiple times
    if logger.hasHandlers():
        return logger
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # File Handler
    if not os.path.exists('logs'):
        os.makedirs('logs')
        
    file_handler = logging.FileHandler(f"logs/{log_file}")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console Handler (only for main bot and monitor, not for status log to avoid clutter)
    if name in ['trading_bot', 'market_monitor']:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger
