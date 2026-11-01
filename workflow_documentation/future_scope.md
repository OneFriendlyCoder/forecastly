# Future Scope

These are gaps in the information the system receives today. See the event list in `schemas/event.v1.json`.

| Gap | Today | What it would take |
|---|---|---|
| **Written content** | Email text, meeting notes and call recordings aren't included. We know a reply was negative, but not what it said | Bring in the text through the CRM connector, then let the agent search and quote it. This needs a privacy review, and text from buyers must be treated as untrusted input to the LLM |
| **Free-form notes** | There's no event for something like "the budget got cut" | Add a `note_added` event type, then let the agent read notes. The model would need new features to use them |
| **Deal details in events** | Product and amount come from the `deals` table, not from events | Add a `deal_updated` event, so changes reach the system through Kafka like everything else and the `deals` table stays current |
