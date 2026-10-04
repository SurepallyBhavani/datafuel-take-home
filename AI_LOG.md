# AI log

## Tools I used, and for what

I used **Claude Code in VS Code**, for:
- reading and summarising the four task files, and listing the server behaviours that could give a wrong number
- planning the order of work and the open questions in the README
- writing throwaway scripts to watch the mock portal (roster, pagination, rate limit, soft-ban)
- writing the code: `db.py`, `sweep.py` and `app.py`
- writing the tests, and checking them by deliberately breaking the code
- reviewing `review_me.py`
- writing a live verification script that recomputes the city figures straight from the portal
- drafting the documentation (NOTES.md, REVIEW.md, README.md) from results I had confirmed

## Prompts that mattered

**1. The first prompt.** It set the whole plan.

```
I'm doing a backend take-home assignment. The files in this folder are README.md,
API.md, mock_portal.py and review_me.py. Please read all four carefully. Don't write
or edit any code yet, and don't modify mock_portal.py.

Then give me:

1. A short summary of what I'm building and what's being tested, in your own words.
2. Everything in the server's behaviour that could give a wrong number, split into
   (a) things API.md or the README tell me and (b) things you can only tell from the
   code in mock_portal.py. For each one, say how I could observe it by calling the
   API myself.
3. The decisions I need to make before coding, with your recommendation and reasoning
   for each: which stores to track, how to decide a store's data is complete or
   incomplete, how to detect the soft ban, how to map sweeps to IST days, how to
   treat stores with no products, and what to do when a re-run gives a worse result.
4. A step-by-step order of work from setup to submission, with a check I can run
   after each step to confirm it worked.
5. What review_me.py is for in this project, and what I should do with it.
6. Anything in the README or API.md that's ambiguous or that you're unsure about.

Keep it concise. I'll work through the steps one at a time, and I'll want to verify
things myself, so flag anything you're guessing at.
```

**2. My store rule and `as_of` prompts.** I asked to use stores that are active **and** serviceable, and to record the flags per sweep, keyed by `as_of`, so a day's figure uses the status at that sweep. Then I asked to add up the in-stock counts and the totals across a day's sweeps. These two shaped the design.

**3. My review prompts.** I listed the problems in `review_me.py` first, then asked what I had missed, then picked the fixes. I also pointed out two gaps in the scraper (`finished_at` being overwritten, and a ban costing about 155 seconds per store), which led to the "stop after 3 stores in a row" rule.

Other instructions that changed how the work went: keep the probes minimal and use one script, make changes only after I approve, and show me the list of completed tests so that I can point out the gaps.

After the first prompt, the rest was instructions and discussion with the agent.

## Times the AI was wrong, and how I noticed

**1. The items and pages for MUM-001.** The AI predicted about 29 items over 2 pages. When I ran the probe I got 3 pages and 33 rows for 32 distinct products. That is where the duplicate rows at the page boundary were recognised.

**2. The soft-ban recovery.** The AI predicted `origin` again after 25 seconds of silence. In the soft-ban probe 8 replies were `origin`, 22 were rate-limited (429, no source), and the ban started at request 31. When I retried after 25 seconds the portal was still returning `edge`, and it was only over after 65 seconds, because a request made during a ban extends it by 5 seconds. That is why the scraper waits 25 seconds and then 65.

## What I decided myself

The store rule (active and serviceable), the flags saved per sweep, the day's figure as a total over all its sweeps, assigning a sweep to its IST day by `as_of`, treating a store with no products as complete, the scraper gaps above, and which problems to fix in `review_me.py`.
