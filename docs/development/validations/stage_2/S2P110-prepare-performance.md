# S2P110 prepare and adoption performance rehearsal

## Boundary

This was an isolated read-only rehearsal over the real sealed inputs. It created no inputs lock,
Authority, Run, Manifest or publication. A fresh Python process was used for each measurement;
the macOS filesystem cache could not be forcibly cleared, so “cold” below means process-cold, not a
provably empty OS storage cache.

## Results

| Measurement | Result | Gate |
|---|---:|---:|
| process-cold sealed prepare pipeline | `19.06 s` | `<= 60 min` |
| second fresh-process pipeline | `20.01 s` | informational |
| maximum observed RSS | `1,503,215,616 bytes` | `<= 3 GiB` |
| Contract Price partitions bound | `4,752` | exactly `4,752` |
| adopted T12–T18 tasks | `7` | exactly `7` |
| full Trade row rescan | `false` | must be `false` |
| adoption bundle stability | same Hash on both runs | required |

Both runs produced adoption bundle Hash
The adoption tree-root naming was subsequently tightened to use each historical Catalog root;
the current bundle Hash is
`c61b7ee38cb657b487d1894b46bcde2da2ab955fde47ea3b6fd39f6b1ca0270f`.

The old observed prepare had run for 5 hours 10 minutes without completion and used about
26.8 GiB. The new rehearsal completed in about 20 seconds and stayed below 1.5 GiB because it did
not materialize canonical Trade price columns and did not reread all Contract Price content.

## Remaining gate

The exact clean-commit `prepare` must still complete within 60 minutes and at or below 3 GiB. Its
resulting inputs-lock Hash and adoption-bundle Hash are the only values eligible for the next human
approval. Passing this rehearsal does not authorize Authority or Run creation.
