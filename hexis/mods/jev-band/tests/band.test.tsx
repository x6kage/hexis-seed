import { expect, test } from 'claude-code/testing'

const LINE = 'Jev 1.14.0 · instruction 0.98 · new_topic 0.49 · clear 0.47'
const COST =
  'Cost: $1.00 | main $1.00 (opus-5-5 $1.00 now) | agents $0.00 | turn $0.10 | avg $0.07/req | context 12k | cold 0 = $0.00'

const BAND = {
  plugin: 'jev-band',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 200,
    scroll: { offset: 0, bodyRows: 10 },
    view: {},
  },
} as const

const FILES: Record<string, string> = {
  '~/.claude/logs/jev-readings/s1.json': JSON.stringify([
    { kind: null, error: true },
    { kind: 'instruction', clear: 0.47, line: LINE },
  ]),
  '~/.claude/logs/jev-readings/s2.json': JSON.stringify([
    { kind: 'instruction', clear: 0.47, line: LINE },
    { kind: null, error: true },
  ]),
  '~/.claude/logs/cost-meter/s1.txt': COST + '\n',
  '~/.claude/logs/cost-meter/s2.txt': COST + '\n',
}

function files(on: Parameters<Parameters<typeof test>[1]>[1]) {
  on('fs.read', (_, e) => {
    const text = FILES[e.path.replaceAll('\\', '/').replace(/^.*\/\.claude\/logs\//, '~/.claude/logs/')]
    if (text === undefined) throw new Error('ENOENT')
    return { value: text }
  })
}

test('the band draws the reading line and the cost line, on both band surfaces', async ($, on) => {
  on('session.id', () => ({ value: 's1' }))
  files(on)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })

    expect((await ui.find({ type: 'Text', text: /^Jev / }))?.text).toBe(LINE)
    expect((await ui.find({ type: 'Text', text: /^Cost: / }))?.text).toBe(COST)
    await ui.unmount()
  }
})

test('a prompt Jev failed to read shows no older reading line', async ($, on) => {
  on('session.id', () => ({ value: 's2' }))
  files(on)

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })

  expect(await ui.find({ type: 'Text', text: /^Jev / })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /^Cost: / }))?.text).toBe(COST)
  await ui.unmount()
})

test('a surface with no band gets both lines in full as the status line', async ($, on) => {
  const statuses: (string | undefined)[] = []
  on('session.id', () => ({ value: 's1' }))
  on('session.surfaces', () => ({ value: ['mobile'] }))
  files(on)
  on('ui.invalidate', () => ({ value: undefined }))
  on('ui.status', (_, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/', surface: 'mobile', isInteractive: true })

  expect(statuses.at(-1)).toBe(`${LINE}  |  ${COST}`)
})
