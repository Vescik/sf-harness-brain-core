---
approval:
  mechanism: null
  reviewedAt: null
  reviewedBy: null
  reviewedContentDigest: null
assurance:
  typeFacts: source-exact
candidateKeywords: []
extractionCoverage:
  typeFacts: full
keywords: []
lifecycle:
  contentDigest: sha256:d147a1aa8bfb36d30047c922a8a6d62edf638114a31f57ea1ec9187639a517bf
  state: draft
limitations: []
profile:
  digest: sha256:4079767dca7e9e993e95ed4b123539dda1e3554890aa28d7ff72224e5344aa64
  id: salesforce.lightning-component
  version: 1.0.0
schemaVersion: 1
scope:
  packageVersionId: null
  sourceApiVersion: '64.0'
  sourceTreeDigest: sha256:185d0dd4ab3585917aadff756f5a3a9dba44d720c25ab3c9f6ae7fce01a6959a
sensitivity: internal-sanitized
source:
  fragments:
  - path: force-app/main/default/lwc/mpsaCard/mpsaCard.js-meta.xml
    sourceDigest: sha256:43b572b25429496d6bbe5fd90c20efcaf1f5214d1a626d3356fe5b5b6f99bb33
subject:
  fullName: mpsaCard
  metadataType: LightningComponentBundle
  namespace: null
typeFacts:
  apiProperties:
  - iconName
  - title
  isExposed: false
---

## Purpose

A presentation-only wrapper that renders a standard Lightning card with a caller-supplied heading and icon and drops whatever the consumer nests inside it into a slot with consistent padding. Its own comment describes it as the shared base card for Meridian PSA feature components, kept internal rather than surfaced to page builders so that the styling and structure of those cards stay uniform. It holds no data, makes no server call and is wired to nothing on its own; the component that supplies the heading, icon and body content is whichever component embeds it. No other bundle in this repo references it today, so the feature cards it was written to back are not present here.
