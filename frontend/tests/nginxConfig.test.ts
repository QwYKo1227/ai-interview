import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('frontend nginx configuration', () => {
  it('serves module worker files with a JavaScript MIME type', () => {
    const config = readFileSync('nginx.conf', 'utf8')

    expect(config).toMatch(
      /location\s+~\*\s+\\\.mjs\$\s*{[^}]*default_type\s+application\/javascript;/s,
    )
  })
})
