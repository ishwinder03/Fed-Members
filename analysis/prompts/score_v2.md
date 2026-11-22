You rate the monetary-policy stance of one FOMC participant from one document.

THE MANDATE
The Federal Reserve's dual mandate is maximum employment and stable prices. Price stability means inflation of 2 percent over the longer run, measured by the PCE price index. A member's stance reflects which side of the mandate they treat as the bigger risk and what policy that implies. Concern that inflation stays above 2 percent is hawkish (keep rates higher, or raise them). Concern that the labour market is weakening is dovish (lower rates). Judge the balance of risks the member describes, not merely which topics they mention.

THE SCALE
Stance is measured RELATIVE TO THE CURRENT POLICY RATE given in POLICY CONTEXT, not relative to a neutral rate or to history. Half points (e.g. 1.5) are allowed.

+5  wants bigger or faster hikes than a single 25bps move. e.g. "a 50 basis point increase would be appropriate"; "we are behind the curve and must act forcefully"
+4  wants a hike at the next meeting. e.g. "I would support raising the target range at our next meeting"
+3  leans toward further hikes, timing not tied to the next meeting; a tightening bias. e.g. "further firming may well be needed"; "I am not convinced we are done"
+2  hold, but inflation is clearly the bigger risk; would resist cuts. e.g. "policy needs to remain restrictive for some time"; "I see no case for easing"
+1  hold, with a mild hawkish tilt. e.g. "I want to see more progress on inflation before considering any change"
 0  comfortable holding; risks balanced; no bias. e.g. "policy is well positioned"; "we can afford to wait and see"
-1  hold, with a mild dovish tilt. e.g. "I am watching the softening in hiring closely"
-2  hold for now but expects cuts; employment is the bigger risk. e.g. "reductions would likely be appropriate later this year"
-3  leans toward cuts, timing not tied to the next meeting; an easing bias. e.g. "a cut could be appropriate in the coming meetings"
-4  wants a cut at the next meeting. e.g. "I would support lowering the target range at our next meeting"
-5  wants big or fast cuts (50bps, or a series). e.g. "we should move quickly to bring the rate down"

RULES
1. Rate only views the speaker states as their own. Ignore questions put to them, other people's views they describe, and staff or market forecasts they do not endorse.
2. If the document has little or no monetary-policy content (payments, regulation, supervision, history, research, community development), set policy_relevance near 0, stance 0 and confidence low. Do not infer a stance from the speaker's reputation, past views or past votes.
3. Standard disclaimers ("my views are my own", "data dependent", "meeting by meeting") are not evidence for either side.
4. next_meeting_call gives the probability that the speaker would favour each action at the NEXT MEETING named in POLICY CONTEXT (not at some later meeting). The three numbers sum to 1.
   - Give hike (or cut) the highest probability only when the speaker signals a move at the next meeting, or says action is needed now, without delay, or at "our next meeting" / "in [that month]".
   - Wanting more hikes (or cuts) "over time", "in coming months", "later this year", "if the data evolve as expected", or without naming when, usually means HOLD at the next meeting with a bias, especially soon after a move. Put hold highest in that case, and express the lean through the stance (+3 or -3) and a hike (or cut) probability below 0.5.
   - A stance of +4 or above means hike is the most likely call; -4 or below means cut; between -3 and +3 hold is usually the most likely call.
5. policy_relevance (0-1): how much of the document is about the outlook for monetary policy. confidence (0-1): how clearly the text reveals the speaker's stance.
6. mandate_balance runs from -1 (worried only about employment) to +1 (worried only about inflation); 0 means the risks are treated as balanced. Give a one-line mandate_reason.
7. sub_views: one short sentence each on inflation, the labour market, the preferred policy path, and urgency. Write "not discussed" where the text says nothing.
8. evidence: 2 or 3 quotes copied EXACTLY, character for character, from the TEXT, each under 40 words, with the document date. Choose the passages that most determine the stance. Do not paraphrase, join or shorten quotes.
9. summary: one line on the speaker's stance and why.
