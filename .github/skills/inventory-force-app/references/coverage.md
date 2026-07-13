# force-app extraction coverage

| Source artifact | Sanitized inventory | Governed claim candidates |
|---|---|---|
| Custom object | API name, labels, deployment/sharing values | positive object-existence |
| Custom field | API name, label, type, selected flags, formula, references | field-schema and object-relation |
| Flow | status, process/start configuration, named actions/subflows | automation-inventory |
| Apex class/trigger | declaration, trigger object/events, custom-object tokens | automation-inventory |
| LWC/Aura | exposure/targets and source-declared references | inventory only |
| Named/external credential, remote site | component name, label, endpoint host only | integration |
| Other files | path, category, SHA-256 | inventory only |

Never extract credential values, raw record data, private keys, tokens, complete source content,
or inferred business semantics. Repository evidence does not prove deployed org state.
