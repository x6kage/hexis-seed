import type { EngineInterface, Register } from 'claude-code'

const LOGS = '~/.claude/logs'
const BAND_SURFACES: readonly string[] = ['terminal', 'desktop']

type Reading = { line?: string; kind?: string | null; clear?: number }

// The newest reading only: a prompt Jev failed to read (or a peer / notification turn) saves an entry without a line,
// and rules/output.md says such a prompt gets no line - an older line would read as this prompt's (Fable audit).
async function latest($: EngineInterface) {
  const session = await $.session.id()
  const readings = await $.fs
    .read(`${LOGS}/jev-readings/${session}.json`)
    .then(text => JSON.parse(text) as Reading[])
    .catch(() => [] as Reading[])
  const newest = readings.at(-1)
  const line = typeof newest?.line === 'string' ? newest.line : undefined
  const cost = await $.fs
    .read(`${LOGS}/cost-meter/${session}.txt`)
    .then(text => text.trim() || undefined)
    .catch(() => undefined)

  return { line, cost }
}

// Surfaces without a band (mobile, vscode) get both lines in full as the status line (up to 2000 chars).
// The session's attached surfaces, for the Python hooks: while a surface without a band (a phone) is attached, the
// replies carry the two lines again (the mod cannot be seen on a phone). Written before the prompt
// hooks run, so the prompt that a phone sent already gets them.
let roster = false

async function writeSurfaces($: EngineInterface) {
  roster = true
  try {
    const session = await $.session.id()
    const surfaces = await $.session.surfaces()
    await $.fs.write(`${LOGS}/jev-band/${session}.json`, JSON.stringify({ surfaces }))
  } catch {
    // Without the file the hooks treat the band as absent and ask for the copy: the lines are never lost.
  }
}

async function refresh($: EngineInterface) {
  try {
    $.ui.invalidate('ui.render')
    const surfaces = await $.session.surfaces()
    const hasNoBand = surfaces.some(s => !BAND_SURFACES.includes(s))
    const { line, cost } = await latest($)
    const text = [line, cost].filter((l): l is string => l !== undefined).join('  |  ')

    $.ui.status(hasNoBand && text ? text : undefined)
  } catch {
    // A failed refresh leaves the band as last drawn; the prompt itself is never held up by it.
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await writeSurfaces($)
    await refresh($)

    return started
  })

  on('session.attach', async ($, e, next) => {
    const attached = await next(e)
    await writeSurfaces($)

    return attached
  })

  on('session.detach', async ($, e, next) => {
    const detached = await next(e)
    await writeSurfaces($)

    return detached
  })

  on('prompt.submit', async ($, e, next) => {
    await writeSurfaces($)
    const submitted = await next(e)
    await refresh($)

    return submitted
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) {
      return next(e)
    }

    // The band draws before any prompt after a load: write the roster now too, or the first reply after a reload is
    // checked as if no band were shown (the Stop check blocked a reply while the band was on screen).
    if (!roster) {
      await writeSurfaces($)
    }
    const { line, cost } = await latest($)
    const lines = [line, cost].filter((l): l is string => l !== undefined)

    if (lines.length === 0) {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)

    return (
      <Box flexDirection="column">
        {lines.map(l => (
          <Text wrap="wrap">{l}</Text>
        ))}
      </Box>
    )
  })
}
