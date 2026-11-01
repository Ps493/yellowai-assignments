# AI Log

I used Claude (Anthropic) to help build both assignments. This log records what I asked, what it produced, and what I changed. Prompts are quoted as I typed them.

## 1\. The initial prompt

I attached both assignment PDFs and the invitation email and wrote:

> now act senior ai engineer and help me build this assognment perfectly and very good and human made nad neat and clean as per industry standards here are both the assignments attached

That was the only build instruction; I did not send separate prompts per feature. Both topics the brief asks about were therefore covered by that single prompt and the PDFs:

### Parallel fetching

**What came back:** an `asyncio` + `httpx` script that fetches each distinct city with `asyncio.gather`, with a semaphore capping in-flight requests at 10.

**Result:** `return\_exceptions=True` is on so that one failing city can't cancel the rest, and the test suite includes a timing test that fails if the calls run one after another.

### Error handling

**What came back:** custom exceptions (`CityNotFoundError`, `WeatherAPIError`); 404 logged without retry (so `InvalidCity123` doesn't crash the run); 401 fails fast; 429, 5xx and timeouts retry with backoff; malformed responses are reported as errors; failed orders keep their status and get an `error` field.

**Result:** a unit test runs the sample orders (including `InvalidCity123`) through the script and checks that the valid cities are still processed and the bad one is recorded as an error.

### Other things in the first version

An apology function, `.env` loading, offline tests with a mocked API, and the whole of Assignment 1 (the n8n workflow, Code-node sources, Logic Log and unit tests).

## 2\. Second round: fixes after a review

I had the first version reviewed in a separate chat, then sent the list of problems back to Claude with the instruction to apply all of them. The fixes:

* Gemini output cap raised from 120 to 1024 tokens (thinking tokens could leave the pitch empty), and the Discord footer now says when the fallback pitch was used.
* Assignment 2 is safe to re-run: stale delays, apologies and weather values are cleared; exit code 3 if every lookup fails.
* Extra tests: re-run behaviour, an end-to-end `run()` test, and a less timing-sensitive concurrency test.
* Watermark in Assignment 1 now also remembers the logins seen at the newest timestamp, so same-second stars aren't skipped.
* Logic Log wording corrected where it overclaimed what retries do, and the known limits expanded.
* README and repo cleanup.

## 3\. My own changes and decisions

`3. My own changes and decisions



I reviewed the generated implementation and the final submission package rather than submitting the first generated version unchanged. I personally:



\- reviewed the Assignment 2 flow and ran it with my own OpenWeather API key on 2 Nov 2026;

\- verified the live behaviour for New York, Mumbai and London, and confirmed that `InvalidCity123` was logged as an error without crashing the whole run;

\- ran the complete test suite myself and verified that all 22 tests passed;

\- decided not to manually alter `orders.json` to create a delayed order when the live weather did not meet the delay conditions;

\- reviewed the Assignment 1 workflow behaviour and the submission requirements, including the GitHub rate-limit handling, lead filtering, AI pitch generation and Discord output;

\- reviewed the final repository for submission, including removing secrets and private configuration before publishing;

\- replaced the real OpenWeather API key that had accidentally been placed in `.env.example` with a safe placeholder before the final GitHub submission;

\- decided that the documentation should state the actual limitations and testing results rather than claiming behaviour I could not demonstrate live.



4\. Follow-up prompts I actually sent



After the initial build prompt, I used follow-up conversations to review the generated work, identify issues and request corrections. The exact wording of those conversations should only be included here if it can be copied from my actual chat history. The main follow-up requests were to review the assignments against the brief, identify implementation and submission issues, and apply the fixes described in Section 2.



I also independently ran the final Assignment 2 implementation and tests before submission.

