---
name: update-relations
description: Sweep force-app for reference edges not yet captured as governed relation claims and propose the new ones in batches; safe to rerun as the Knowledge base is built out incrementally.
argument-hint: "[type=<MetadataType>] [limit=<N, default 200>] [recordId=<ID>]"
agent: config-investigator
tools: ['read', 'search', 'execute/runInTerminal', 'vscode/askQuestions']
---

Use the [update-relations skill](../skills/update-relations/SKILL.md).

If a `type` argument is given, scope the whole run to that metadata type
(`--metadata-type <Type>` on every `relations-worklist`/`relations-draft` call). If `limit` is
given, use it in place of the default 200 for `relations-draft --limit`. If this is governed work,
require and validate `recordId` and attach the resulting report/claim references to that record;
otherwise state that the run is not tied to a work record.

For entry-home metadata types the relation graph lives in the entries themselves
(`typeFacts.references`): query it with `knowledge_search.py search --relation-anchor ...`
or `impact --identity ...` rather than drafting relation claims for them.
