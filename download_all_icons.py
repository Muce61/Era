#!/usr/bin/env python3
"""
Batch download all Binance Futures contract icons.
This script downloads icons for all USDT-M perpetual contracts.
"""

from utils.icon_helper import batch_download_all_icons

if __name__ == "__main__":
    print("=" * 60)
    print("Binance Futures Icon Batch Downloader")
    print("=" * 60)
    batch_download_all_icons()
