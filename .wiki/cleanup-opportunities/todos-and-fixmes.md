# TODOs and FIXMEs

The 360Ghar backend has only two `TODO` comments across all of `app/`. This is well below average for a codebase of 67,000 lines. Both are documented below with their context.

Active contributors: Saksham, Ravi

## TODO 1: Email integration for data hub alerts

File: `app/services/data_hub/alerts.py`, line 113

```python
# TODO: integrate with email service when EMAIL_SMTP_HOST is configured
```

The data hub alert system (`AuctionAlert` model) currently stores alerts in the database but does not email them to subscribed users. The notification dispatcher (`app/services/notification_dispatcher.py`) and email service (`app/services/email.py`) already exist and support email as a channel - the alert flow just has not been wired into them yet. The `EMAIL_SMTP_HOST` setting gates email delivery, so the integration should no-op when SMTP is not configured.

**Effort:** Small. Call `dispatch_notification_to_user` from the alert creation path with a new `auction_alert` notification type registered in `app/services/notification_config.py`.

## TODO 2: Property recommendation algorithm

File: `app/services/property/recommendations.py`, line 64

```python
# TODO: Implement proper recommendation algorithm based on user preferences
```

The recommendations endpoint currently returns a heuristic-based feed (recently added, popular, geographically close) rather than a personalized ranking. The `User.preferences` JSON column and the `property_embeddings` table (pgvector) are available for a proper implementation - the embedding similarity could power a content-based recommender, and the swipe history (`UserSwipe`) could power a collaborative filter.

**Effort:** Medium. A content-based recommender using pgvector cosine similarity against the user's liked-property embeddings is the natural first step. The vector sync scheduler (`app/services/vector_sync_scheduler.py`) already keeps embeddings fresh.

## Why there are so few TODOs

The codebase uses AI-assisted development heavily (single primary contributor using AI tooling, per the git history). This tends to produce complete implementations rather than stubbed ones - the AI completes the task in one pass rather than leaving a TODO for later. The two remaining TODOs are both "feature not yet built" rather than "code quality debt".
