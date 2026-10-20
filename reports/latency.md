# Loan-purpose question, before and after

Question: "What loan purpose is on the loan instance that the automated underwriting system response message points to?"

Both runs answered Purchase and cited `mare_lat_hop.au_system_response_messages:da13d9c6-75b1-5289-8336-2be1f807a8e9` and `mare_lat_hop.api_loan_instances:415c5349-d293-5e99-9e29-34949c4b8c54`. Same path: 4 turns, 3 tool calls.

The cluster used for the live UI was unreachable from this machine (TCP timeout to all three Atlas shard hosts). The comparison is a local mongod with those two documents and the same question. The index has 4 navigation nodes, not the 95-node `mi_transformation` index. Parallel tool execution stayed off, so this delta is the saved navigation vectors only.

| | Before | After |
| --- | ---: | ---: |
| Load saved index | 4,526 ms | 1 ms |
| Navigation embeds during the ask | 4 texts, 4,525 ms | 0 |
| Query embed | 1,141 ms | 1,269 ms |
| Answer model | 16,241 ms | 12,766 ms |
| Full request | 21,920 ms | 14,052 ms |

Building the vectors once, outside the ask, took 1,305 ms for the same 4 texts. Later asks reuse them.

The code change removes one embedding round trip from every question. On the before run that round trip was 4.5 seconds, so load time went from 4,526 ms to 1 ms. The full request fell from 21.9 s to 14.1 s. About 3.5 s of that gap is the answer model finishing faster (16.2 s vs 12.8 s), which this change does not control. The query embedding and the three tool calls are still inside the request.

On the real index the same change removes one or two embedding calls (95 texts, batches of 64) from each question. It does not shorten the read that pulls every id on the 76,912-id loan card. That read is still a follow-up.
