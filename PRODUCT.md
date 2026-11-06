# ClearToPay

## Purpose
Before a company pays a new vendor, ClearToPay checks that vendor against three official US sources (OFAC sanctions search, SAM.gov federal exclusions, the Colorado Secretary of State business registry) and returns a vendor file: one row per check with the screenshot, the URL, the time, a SHA-256 hash and a verdict. Each check runs a real browser inside its own disposable microVM on Vultr, with network access only to that source, no secrets inside, and proof that the microVM was destroyed afterwards. The vendor's own website is opened as untrusted content; if it tries to give the agent instructions, the attempt is contained and shown. Payment release stays behind a human approval button.

## Audience
- Primary user: an accounts-payable or procurement analyst at a US company with 50 to 2,000 employees who onboards several new vendors a week and today does these searches by hand, pasting screenshots into a folder for the auditor.
- Deciders seeing it: hackathon judges (lablab panel: software engineers from large US tech companies, a few business and security profiles). They give each project a few minutes and must understand it from one screen.

## The key screen
The vendor file ("expediente"): the result of checking one vendor. It must answer at a glance: can I pay this vendor, and why. Then let the analyst open any check to see the evidence and what the sandbox contained.

## Voice
Plain, calm, exact. Sentence case. English UI for a US audience. No security jargon in headings ("Needs a human: the vendor's website tried to give instructions to the agent"). Never "AI-powered", "seamless", "next-gen".

## Constraints
- Every number shown comes from a real run or from the committed eval.
- Three possible decisions: clear to pay, needs a human, blocked. Never show "clear" while checks are still running.
- The final payment action is simulated and says so.
- Mode: operate (a tool used several times a day).

## Real proof available
- Real check results from 3-nov runs (OFAC hit on "BANK SADERAT PLC", SAM exclusion on "Morales Construction, Inc.", Colorado Good Standing for "Ball Corporation").
- Eval k=1: 27 of 30 decisions correct, 0 of 18 dangerous vendors cleared, 3 of 12 clean vendors sent to review. About 28 seconds per vendor for three checks.
- Containment facts per check: 1 vCPU, 2 GiB, 150 s max, allowed hosts list, blocked hosts list, environment variable names inside the sandbox (no keys), destroyed = true.
