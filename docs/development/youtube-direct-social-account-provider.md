# YouTube Direct Social Account Provider

LabelOS uses YouTube as the reference direct social account provider. The
adapter is limited to connection lifecycle behavior: OAuth authorization, token
exchange, credential storage, channel identity retrieval, scope parsing,
capability resolution, refresh, health checks, and disconnect revocation.

It does not publish content or fetch analytics reports. The separate
[Stage 5 publishing adapter](youtube-publishing-adapter.md) reuses this provider's
credential store and refresh implementation for video delivery.

## Official Endpoints

- Authorization: `https://accounts.google.com/o/oauth2/v2/auth`
- Token exchange and refresh: `https://oauth2.googleapis.com/token`
- Channel identity: `GET https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true`
- Revocation: `POST https://oauth2.googleapis.com/revoke`

## Scopes

- `https://www.googleapis.com/auth/youtube.readonly` identifies the
  authenticated channel. It is required for connection setup, but does not map
  to a LabelOS publishing or analytics capability by itself.
- `https://www.googleapis.com/auth/youtube.upload` maps to
  `content_publish`. LabelOS records the capability only when Google returns the
  scope. The connection layer does not upload videos.
- `https://www.googleapis.com/auth/yt-analytics.readonly` maps to
  `account_analytics_read` and `post_analytics_read`. The connection layer does
  not retrieve analytics reports.

## Provider Limitations

Google OAuth refresh tokens require `access_type=offline`; Google may only
return a refresh token on the first consent for a client/user combination.

Public apps requesting Google scopes that access user data may require OAuth app
verification. Scopes categorized by Google as sensitive or restricted must not
be treated as approved until the Google Cloud project has completed the
required review. LabelOS therefore resolves capabilities from scopes actually
returned by the token endpoint, not from requested scopes.

Google revocation invalidates OAuth scopes previously granted to the project and
can invalidate access or refresh tokens for clients registered under that
project.

## Production Enablement Checklist

Keep `NEXT_PUBLIC_YOUTUBE_DIRECT_OAUTH_ENABLED=false` until the backend has both
`YOUTUBE_OAUTH_CLIENT_ID` and `YOUTUBE_OAUTH_CLIENT_SECRET` configured. In
production-like environments, LabelOS startup rejects a partial YouTube OAuth
configuration so the direct provider cannot be accidentally half-enabled.

Register this Authorized redirect URI on the Google OAuth web client before
turning on the web feature flag:

```text
https://<your-web-domain>/api/social-account-connections/oauth/youtube/callback
```

Local testing uses the same path under `http://localhost:3000`. The callback
route resolves the LabelOS workspace from the OAuth state record; the workspace
id is intentionally not part of the registered provider redirect URI.

The Marketing Accounts UI starts OAuth with
`safe_redirect_path=/marketing?tab=accounts`. Successful and expected failed
callbacks append only `oauth=connected` or `oauth=failed` to that safe relative
path; provider codes, tokens, and error descriptions are not placed in the
redirect URL.
