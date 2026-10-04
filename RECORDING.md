# Recordings

Screen recordings of the work, in six parts, plus a short talk-through with voice.
Times are minutes:seconds into each part (h:mm:ss where a part runs longer than an hour).

## Links

| Part | What it covers | Link |
|---|---|---|
| part-1 | TODO: one line on what part 1 covers | https://drive.google.com/file/d/1it1290_v5DizQk8VF3e9dQy0P0ZS11cq/view?usp=sharing |
| part-2 | Probing the portal, the first soft-ban, the decision on which stores to track | https://drive.google.com/file/d/1mcuskPDXJEbcWSEDInDHidNA6_K4l2Q1/view?usp=sharing |
| part-3 | Database and scraper, the first sweeps, the start of `/osa` | https://drive.google.com/file/d/1o3gfZHfuk5rF1_t9uYn-aD4Y7J_l0kZz/view?usp=sharing |
| part-4 | Reviewing `review_me.py`, the store-rule comparison, running all tests, final commit | TODO: add link |
| part-5 | Documentation - README.md , NOTES.md | TODO: add link |
| part-6 | Documentation - AI_LOG.md , RECORDING.md | TODO: add link |
| talk-through (5 minutes, voice) | What I built, the hardest bug, what I would improve | TODO: add link |

## Key moments

### part-1
| Time | What happens |
|---|---|
| 9:28 | Running through README.md , API.md |

### part-2 (probing the portal)
| Time | What happens |
|---|---|
| 3:42 | Checking the probes and deciding which tests to write |
| 9:23 | Running the read-only probes |
| 21:00 | First soft-ban: running the stress probes |
| 31:00 | Decision 1: which stores to track |

### part-3 (database and scraper)
| Time | What happens |
|---|---|
| 11:02 | The database layout (`db.py`) |
| 13:32 | The sweep logic (`sweep.py`) |
| 21:17 | Running the first sweep |
| 31:38 | Checking the sweeps against the database |
| 41:41 | Reporting the scraper gaps |
| 52:39 | Committing the scraper |
| 53:56 | Starting `/osa` |
| 57:20 | Why `/osa` reads the stored sweeps and does not fetch from the portal on each request |

### part-4 (`review_me.py` and final checks)
| Time | What happens |
|---|---|
| 9:57 | Listing the critical problems in `review_me.py` to fix |
| 23:28 | Running `review_me.py` |
| 36:30 | Committing the `review_me.py` fixes |
| 38:33 | Store-rule comparison: active and serviceable (Rule A) against active only (Rule B) |
| 51:50 | Running all the tests: the manual checks and the automated pytest suite |
| 1:36:09 | Final commit of the code |

