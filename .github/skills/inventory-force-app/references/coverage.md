# force-app extraction coverage

| Source artifact | Sanitized inventory | Governed claim candidates |
|---|---|---|
| Custom object | API name, labels, deployment/sharing values | positive object-existence |
| Custom field | API name, label, type, selected flags, formula, references | field-schema and object-relation |
| Flow | status, process/start configuration, named actions/subflows, referenced objects, fields read/written, invoked Apex, element counts | automation-inventory |
| Apex class/trigger | declaration, trigger object/events, custom-object tokens, SOQL objects, DML verbs, invoked classes | automation-inventory |
| Validation rule | owning object, active flag, error display field, custom fields referenced in the formula | automation-inventory |
| Permission set | label, activation flag, object/field permission counts, object/field grants | inventory only |
| Layout | owning object, placed fields, related lists | inventory only |
| LWC/Aura | exposure/targets and source-declared references | inventory only |
| Named/external credential, remote site | component name, label, endpoint host only | integration |
| Other files | path, category, SHA-256 | inventory only |

Object/field usage for Apex and validation rules is a source-token heuristic (dynamic references,
standard-field usage, and unresolved variable types may be missing or approximate); the drafted
claim records this limitation. Never extract credential values, raw record data, private keys,
tokens, complete source content, or inferred business semantics. Repository evidence does not prove
deployed org state.
