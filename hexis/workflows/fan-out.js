export const meta = {
  name: 'fan-out',
  description: 'Trial one item per tier, then run the batch through the chosen model with one review pass',
  whenToUse: 'Same task over many items (characters, files, tickets). args = {items: [...], brief: "prompt template with {item}", trialModel: "sonnet", batchModel: "opus", trialEffort: "medium", batchEffort: "medium", schema: {...}}',
  phases: [
    { title: 'Trial', detail: 'one item on each candidate tier' },
    { title: 'Batch', detail: 'remaining items on the chosen tier' },
  ],
}

const { items, brief, trialModel = 'sonnet', batchModel = 'opus', trialEffort = 'medium', batchEffort = 'medium', schema } = args
const render = (item) => brief.replace(/\{item\}/g, typeof item === 'string' ? item : JSON.stringify(item))
const extra = schema ? { schema } : {}

phase('Trial')
const [trialCheap, trialStrong] = await parallel([
  () => agent(render(items[0]), { model: trialModel, effort: trialEffort, label: `trial:${trialModel}`, phase: 'Trial', ...extra }),
  () => agent(render(items[1] ?? items[0]), { model: batchModel, effort: batchEffort, label: `trial:${batchModel}`, phase: 'Trial', ...extra }),
])
log(`Trial done. Review both before trusting the batch; error patterns go back into the brief.`)

phase('Batch')
const rest = items.slice(2)
log(`Batch: ${rest.length} items on ${batchModel} at effort ${batchEffort}`)
const batch = await pipeline(rest, (item, _, i) => agent(render(item), { model: batchModel, effort: batchEffort, label: `item:${i + 2}`, phase: 'Batch', ...extra }))

return { trial: { [trialModel]: trialCheap, [batchModel]: trialStrong }, batch: batch.filter(Boolean), dropped: batch.filter(r => !r).length }
