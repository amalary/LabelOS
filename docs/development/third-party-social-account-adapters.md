# Third-Party Social Account Adapters

LabelOS keeps social account connections vendor-neutral. Downstream product code
should depend on `SocialAccountConnection` fields only:

- `provider`
- `connection_method`
- `capabilities`
- account identity fields
- `status`

The third-party connection path is:

```text
LabelOS -> third-party adapter -> social integration vendor -> social network
```

The adapter owns vendor-specific details. External integration service account
IDs, vendor connection IDs, tenant IDs, and similar values belong in
`provider_metadata["third_party"]` or in adapter-owned credential/config storage.
They must not be added to Draft Posts, calendars, core
`SocialAccountConnection` fields, or future scheduling engine contracts unless
the concept is genuinely generic across connection methods.

## Current Implementation

No commercial social integration vendor is selected for LabelOS yet.

`ThirdPartySocialAccountConnectionProvider` defines the vendor-neutral adapter
boundary. It normalizes account identity and capabilities into the canonical
`SocialAccountConnection` shape and stores adapter details under
`provider_metadata["third_party"]`.

`FakeThirdPartySocialAccountConnectionProvider` is the deterministic test
implementation. It uses fake URLs and credential payloads so tests can exercise
the architecture without introducing a SaaS dependency.

## Adding A Vendor

To add a real vendor:

1. Implement a subclass of `ThirdPartySocialAccountConnectionProvider`.
2. Map vendor authorization/connection results into `SocialAccountIdentity`.
3. Map vendor permissions into canonical capabilities such as
   `content_publish`, `account_analytics_read`, and `post_analytics_read`.
4. Store vendor-specific IDs/configuration in `provider_metadata["third_party"]`
   or adapter-owned credential/config storage.
5. Register the adapter in `social_account_provider_registry_from_settings`
   only when intentional LabelOS configuration for that vendor is present.

Do not add vendor package dependencies or enable a vendor adapter merely because
one is available.
