-- Must match ml/features/features.py. test_scoring.py compares the two on real deals.
-- "Now" is the deal's latest event, because replayed events are years old.
SELECT h.deal_id, json_build_object(
    'deal_id', h.deal_id,
    'as_of', h.last_event_at,
    'event_published_at', f.event_published_at,
    'product', d.product,
    'amount', d.amount,
    'days_since_engaged', extract(epoch FROM h.last_event_at - f.engaged_at)::float8 / 86400,
    'emails_sent_14d', f.emails_sent_14d,
    'replies_14d', f.replies_14d,
    'meetings_14d', f.meetings_14d,
    'days_since_last_reply', extract(epoch FROM h.last_event_at - f.last_reply_at)::float8 / 86400,
    'median_reply_hours', f.median_reply_hours,
    'negative_replies', f.negative_replies,
    'contacts_added', f.contacts_added,
    'buyers_replied', f.buyers_replied,
    'no_shows', f.no_shows,
    'close_date_pushes', f.close_date_pushes
)::text
FROM deal_health h
JOIN deals d USING (deal_id)
CROSS JOIN LATERAL (
    SELECT
        max(e.published_at) AS event_published_at,
        min(e.occurred_at) FILTER (WHERE e.event_type = 'stage_changed') AS engaged_at,
        count(*) FILTER (WHERE e.event_type = 'email_sent' AND e.occurred_at > h.last_event_at - interval '14 days') AS emails_sent_14d,
        count(*) FILTER (WHERE e.event_type = 'email_replied' AND e.occurred_at > h.last_event_at - interval '14 days') AS replies_14d,
        count(*) FILTER (WHERE e.event_type = 'meeting_held' AND e.occurred_at > h.last_event_at - interval '14 days') AS meetings_14d,
        max(e.occurred_at) FILTER (WHERE e.event_type = 'email_replied') AS last_reply_at,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY (e.payload->>'reply_delay_hours')::float8)
            FILTER (WHERE e.event_type = 'email_replied') AS median_reply_hours,
        count(*) FILTER (WHERE e.event_type = 'email_replied' AND e.payload->>'sentiment' = 'negative') AS negative_replies,
        count(*) FILTER (WHERE e.event_type = 'contact_added') AS contacts_added,
        count(DISTINCT e.actor->>'id') FILTER (WHERE e.event_type = 'email_replied') AS buyers_replied,
        count(*) FILTER (WHERE e.event_type = 'meeting_no_show') AS no_shows,
        count(*) FILTER (WHERE e.event_type = 'close_date_changed') AS close_date_pushes
    FROM events e
    WHERE e.deal_id = h.deal_id
) f
-- The model was only trained on open deals at least 7 days past engagement.
WHERE h.deal_id = ANY($1)
  AND h.deal_closed = 0
  AND f.engaged_at <= h.last_event_at - interval '7 days'
