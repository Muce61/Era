import os
from pathlib import Path

# Get legacy coins
legacy_dir = Path("/Users/muce/1m_data/backtest_data_legacy")
legacy_coins = {f.stem for f in legacy_dir.glob("*.csv")}

# Get new coins
new_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
new_coins = {f.stem for f in new_dir.glob("*.csv")}

print("="*60)
print("LEGACY vs NEW DATA ANALYSIS")
print("="*60)
print(f"\nLegacy Data: {len(legacy_coins)} coins")
print(f"New Data: {len(new_coins)} coins")

# Overlap analysis
overlap = legacy_coins & new_coins
only_legacy = legacy_coins - new_coins
only_new = new_coins - legacy_coins

print(f"\n{'='*60}")
print("OVERLAP ANALYSIS")
print("="*60)
print(f"Coins in BOTH datasets: {len(overlap)}")
print(f"Only in Legacy: {len(only_legacy)}")
print(f"Only in New: {len(only_new)}")

# Show overlap coins (quality coins)
print(f"\n{'='*60}")
print(f"QUALITY COINS (in both datasets): {len(overlap)}")
print("="*60)
if overlap:
    sorted_overlap = sorted(list(overlap))
    print("\n".join(sorted_overlap[:50]))
    if len(overlap) > 50:
        print(f"\n... and {len(overlap) - 50} more")

# Sample of new-only coins (potential noise)
print(f"\n{'='*60}")
print(f"NEW-ONLY COINS (potential noise): {len(only_new)}")
print("="*60)
if only_new:
    sorted_new = sorted(list(only_new))
    print("\n".join(sorted_new[:30]))
    if len(only_new) > 30:
        print(f"\n... and {len(only_new) - 30} more")

# Create quality whitelist
quality_whitelist = sorted(list(overlap))

# Save to file for use in backtest
output_file = Path("/Users/muce/PycharmProjects/github/eth/config/quality_whitelist.txt")
with open(output_file, 'w') as f:
    f.write("# Quality Coin Whitelist\n")
    f.write(f"# Coins that exist in both legacy (227) and new (597) datasets\n")
    f.write(f"# Total: {len(quality_whitelist)} coins\n")
    f.write("# These coins have proven track record in legacy data\n")
    f.write("#\n")
    for coin in quality_whitelist:
        f.write(f"{coin}\n")

print(f"\n{'='*60}")
print(f"✅ Quality whitelist saved to: {output_file}")
print(f"   Total: {len(quality_whitelist)} curated coins")
print("="*60)
