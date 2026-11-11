# Snapdeal Virtual KAM (Anaya) - Design Note

**What it is:** a browser voice bot that calls a Snapdeal seller whose sales dropped, finds the likely causes from mock data, recommends three ranked actions, and takes ownership by creating tasks, scheduling a follow-up and sending a summary.

## Models and voice
- **LLM:** Google Gemini (gemini-2.5-flash, configurable) with function calling. Temperature 0.4.
- **Speech to text:** browser Web Speech API (Chrome, en-IN).
- **Text to speech:** browser speechSynthesis (en-IN voice). Both are free and need no extra keys.
- Interaction is turn-based: the mic stops while the bot speaks, so it does not hear itself.

## Workflow
1. Seller speaks -> text -> `POST /api/turn`.
2. The agent loop sends the conversation and 10 tool definitions to Gemini. If Gemini calls a tool, Python runs it and returns the result, up to 6 rounds, then Gemini writes a reply of at most two short sentences.
3. The reply is spoken. The action log and summary card update from the session state.

## Tools (deterministic Python, the LLM never does arithmetic)
get_seller_snapshot, analyze_decline, get_oos_products, get_cancellation_reasons, estimate_impact, create_task, schedule_followup, send_summary (mock), escalate_to_human, finish_call.

## Conversation design
Listen, diagnose with at most three one-at-a-time questions, recommend exactly three ranked actions with estimated impact, confirm, create tasks and follow-up, then close with a spoken summary. Upset sellers are escalated to a human. Pricing is not blamed because average selling price did not change.

## Findings from the mock data
Sales and orders both fell 32.5%. Price is flat at Rs 500. Out-of-stock products rose from 5 to 18, cancellations from 8% to 14%. Ranked causes: stock-outs, cancellations, visibility (unknown, so the bot asks), pricing (low).

## Assumptions (all mock)
- Sales = orders x average price.
- 60 active products; per-product order counts, stock-out days and restock lead times are invented.
- Cancellation reasons: 55% stock unavailable, 30% dispatch delay, 15% buyer request.
- Restocking recovers about 60% of the lost orders. Impact figures (about Rs 41,000 from restocking the top 5, about Rs 8,000 from fewer cancellations) are estimates, not promises.
- Send summary, tasks and follow-ups are simulated, not real integrations.

## Limitations
Chrome only; use headphones; no barge-in; free hosting may sleep on first request; English only. With more time: Gemini Live for streaming audio and interruptions, real seller data, and a real WhatsApp integration.

## Testing
9 automated tests (tools, agent loop with a fake model, API) and an eval script with 6 seller personas: cooperative, vague, angry, off-topic, pricing advice and Hinglish.
